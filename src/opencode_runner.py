"""
OpenCode Runner
Manages OpenCode container lifecycle, SSE streaming, and result extraction
"""
import os
import json
import asyncio
import logging
import time
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, AsyncIterator
from datetime import datetime, timezone, timedelta

import docker
from docker.errors import NotFound, APIError, ImageNotFound
import httpx
from httpx_sse import aconnect_sse, SSEError

logger = logging.getLogger(__name__)

# SSE retry configuration
SSE_MAX_RETRIES = 3
SSE_INITIAL_BACKOFF = 1.0  # seconds
SSE_MAX_BACKOFF = 30.0  # seconds
SSE_BACKOFF_MULTIPLIER = 2.0

# Container name prefix for identification
CONTAINER_NAME_PREFIX = "augment-opencode-"


class OpenCodeError(Exception):
    """Base exception for OpenCode-related errors"""
    pass


class DockerUnavailableError(OpenCodeError):
    """Raised when Docker is not available"""
    pass


class ContainerError(OpenCodeError):
    """Raised when container operations fail"""
    pass


class OpenCodeTimeoutError(OpenCodeError):
    """Raised when OpenCode execution times out"""
    pass


class ResultError(OpenCodeError):
    """Raised when result extraction fails"""
    pass


class ImagePullError(ContainerError):
    """Raised when Docker image pull fails"""
    pass


class OpenCodeRunner:
    """
    Manages OpenCode container lifecycle and execution.
    
    Handles:
    - Spawning OpenCode containers
    - Sending prompts via HTTP API
    - Streaming responses via SSE
    - Reading result files
    - Container cleanup
    """
    
    def __init__(
        self,
        docker_image: str = "ghcr.io/anomalyco/opencode",
        job_timeout_minutes: int = 20,
        max_result_size_mb: int = 10,
        result_file: str = "result.json",
        llm_config: Optional[Dict[str, Any]] = None,
        mcp_network_name: Optional[str] = None,
        debug_conversation_logging: bool = False,
        conversation_log_dir: Optional[str] = None
    ):
        """
        Initialize the OpenCode runner.
        
        Args:
            docker_image: OpenCode Docker image to use
            job_timeout_minutes: Maximum job execution time
            max_result_size_mb: Maximum result file size
            result_file: Name of the result file to read
            llm_config: LLM configuration dict with API keys and settings
            mcp_network_name: Docker network name to connect containers to (for MCP server access)
            debug_conversation_logging: Enable conversation logging for debugging
            conversation_log_dir: Directory for conversation log files (default: logs/opencode)
        """
        self.docker_image = docker_image
        self.job_timeout_seconds = job_timeout_minutes * 60
        self.max_result_size_bytes = max_result_size_mb * 1024 * 1024
        self.result_file = result_file
        self.llm_config = llm_config or {}
        self.mcp_network_name = mcp_network_name
        self.debug_conversation_logging = debug_conversation_logging
        self.conversation_log_dir = conversation_log_dir or 'logs/opencode'
        
        self._docker_client: Optional[docker.DockerClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._last_json_response: Optional[Dict[str, Any]] = None
        self._current_container: Any = None  # docker.models.containers.Container
        self._conversation_logs: List[Dict[str, Any]] = []
        self._conversation_start_time: Optional[float] = None
        self._conversation_prompt: Optional[str] = None
    
    def set_llm_config(self, llm_config: Dict[str, Any]):
        """Set LLM configuration for container environment"""
        self.llm_config = llm_config
    
    def _build_container_environment(self) -> Dict[str, str]:
        """
        Build environment variables for the OpenCode container.
        
        Includes:
        - OPENCODE_WORKSPACE: Always set to /workspace
        - LLM API keys: From config or host environment
        - LLM provider/model settings
        """
        env = {
            "OPENCODE_WORKSPACE": "/workspace"
        }
        
        # LLM API Keys - ONLY from config (no environment fallback for OpenCode)
        # Support both formats: provider-specific keys (openai_api_key) and generic (api_key)
        provider = self.llm_config.get('provider')
        
        if not provider:
            logger.error("[OpenCode] No LLM provider specified in config - OpenCode requires OPENCODE_LLM_PROVIDER to be set")
        
        api_key_mappings = [
            ('openai_api_key', 'OPENAI_API_KEY'),
            ('anthropic_api_key', 'ANTHROPIC_API_KEY'),
            ('google_api_key', 'GOOGLE_API_KEY'),
            ('gemini_api_key', 'GEMINI_API_KEY'),
            ('moonshot_api_key', 'MOONSHOT_API_KEY'),
        ]
        
        # First, try provider-specific keys from config ONLY (no environment fallback for OpenCode)
        # Only set non-empty API keys to avoid passing empty strings to OpenCode
        for config_key, env_key in api_key_mappings:
            value = self.llm_config.get(config_key)  # Only from config, no os.getenv() fallback
            # Validate that the value is not empty (not None, not empty string, not just whitespace)
            if value and isinstance(value, str) and value.strip():
                env[env_key] = value.strip()
                logger.debug(f"[OpenCode] Found API key for {env_key} from config key {config_key}")
            elif value:
                # Value exists but is empty/whitespace - log warning
                logger.warning(f"[OpenCode] API key for {env_key} is empty or whitespace, skipping")
        
        # If provider is set and we have a generic 'api_key', map it to the provider-specific key
        if provider and 'api_key' in self.llm_config:
            provider_to_env_key = {
                'openai': 'OPENAI_API_KEY',
                'claude': 'ANTHROPIC_API_KEY',
                'gemini': 'GOOGLE_API_KEY',
                'kimi': 'MOONSHOT_API_KEY',
            }
            env_key = provider_to_env_key.get(provider)
            if env_key:
                if env_key not in env:
                    api_key_value = self.llm_config['api_key']
                    # Validate that the API key is not empty
                    if api_key_value and isinstance(api_key_value, str) and api_key_value.strip():
                        env[env_key] = api_key_value.strip()
                        logger.debug(f"[OpenCode] Mapped generic api_key to {env_key} for provider {provider}")
                    else:
                        logger.warning(f"[OpenCode] Generic api_key found in config but is empty or invalid for provider {provider}")
                else:
                    logger.debug(f"[OpenCode] {env_key} already set, skipping generic api_key mapping")
            else:
                logger.warning(f"[OpenCode] Unknown provider '{provider}', cannot map generic api_key")
        
        # Validate that we have an API key for the provider
        if provider:
            provider_to_env_key = {
                'openai': 'OPENAI_API_KEY',
                'claude': 'ANTHROPIC_API_KEY',
                'gemini': 'GOOGLE_API_KEY',
                'kimi': 'MOONSHOT_API_KEY',
            }
            required_env_key = provider_to_env_key.get(provider)
            if required_env_key and required_env_key not in env:
                logger.error(
                    f"[OpenCode] Missing API key for provider '{provider}'. "
                    f"Expected environment variable: {required_env_key}. "
                    f"Config keys checked: {[k for k, _ in api_key_mappings]}, generic 'api_key'. "
                    f"Available config keys: {list(self.llm_config.keys())}"
                )
                raise OpenCodeError(
                    f"Missing API key for LLM provider '{provider}'. "
                    f"Please configure {required_env_key} or set the appropriate API key in the LLM configuration."
                )
        
        # LLM Provider and Model settings
        if provider:
            env['LLM_PROVIDER'] = provider
            
            # Get model for the provider - ONLY from config (no environment fallback for OpenCode)
            model_key = f'{provider}_model'
            model = self.llm_config.get(model_key) or self.llm_config.get('model')
            if model:
                env['LLM_MODEL'] = model
                logger.info(f"[OpenCode] Using provider: {provider}, model: {model}")
            else:
                logger.error(f"[OpenCode] No model specified for provider {provider} - OpenCode requires model to be set in config")
        else:
            logger.warning("[OpenCode] No LLM provider specified - OpenCode may not know which API to use")
        
        # Filter out None/empty values
        filtered_env = {k: v for k, v in env.items() if v and (not isinstance(v, str) or v.strip())}
        
        # Log which API keys are being set (without exposing the actual keys)
        api_keys_set = [k for k in filtered_env.keys() if 'API_KEY' in k]
        if api_keys_set:
            logger.info(f"[OpenCode] Setting API keys: {', '.join(api_keys_set)}")
        else:
            logger.warning("[OpenCode] No API keys found in environment configuration")
        
        # Log provider/model info for debugging
        if provider:
            provider_to_env_key = {
                'openai': 'OPENAI_API_KEY',
                'claude': 'ANTHROPIC_API_KEY',
                'gemini': 'GOOGLE_API_KEY',
                'kimi': 'MOONSHOT_API_KEY',
            }
            required_key = provider_to_env_key.get(provider)
            if required_key:
                if required_key in filtered_env:
                    # Check if the key is actually set (not just present but empty)
                    key_value = filtered_env[required_key]
                    if key_value and len(key_value.strip()) > 0:
                        logger.info(f"[OpenCode] Provider '{provider}' API key is configured (length: {len(key_value)} chars)")
                    else:
                        logger.error(f"[OpenCode] Provider '{provider}' API key is empty or invalid!")
                else:
                    logger.error(f"[OpenCode] Provider '{provider}' requires {required_key} but it's not set!")
        
        return filtered_env
    
    @property
    def docker_client(self) -> docker.DockerClient:
        """Get or create Docker client"""
        if self._docker_client is None:
            try:
                self._docker_client = docker.from_env()
                # Test connection
                self._docker_client.ping()
            except Exception as e:
                raise DockerUnavailableError(f"Docker is not available: {e}")
        return self._docker_client
    
    def is_docker_available(self) -> bool:
        """Check if Docker is available"""
        try:
            client = docker.from_env()
            client.ping()
            return True
        except Exception:
            return False
    
    def set_concurrency_limit(self, max_concurrent: int):
        """Set the maximum number of concurrent OpenCode containers"""
        self._semaphore = asyncio.Semaphore(max_concurrent)
    
    async def ensure_image_available(self, timeout_seconds: int = 300) -> bool:
        """
        Pre-validate that the Docker image is available, pulling if necessary.
        
        This should be called during worker startup to ensure the image is ready
        before any jobs are processed. This avoids pull delays during job execution.
        
        Args:
            timeout_seconds: Maximum time to wait for image pull
            
        Returns:
            True if image is available
            
        Raises:
            DockerUnavailableError: If Docker is not available
            ContainerError: If image pull fails
        """
        try:
            # Check if image already exists locally
            try:
                self.docker_client.images.get(self.docker_image)
                logger.info(f"[OpenCode] Docker image {self.docker_image} is available locally")
                return True
            except ImageNotFound:
                pass
            
            # Image not found, need to pull
            logger.info(f"[OpenCode] Pulling Docker image: {self.docker_image} (timeout: {timeout_seconds}s)")
            
            # Use low-level API for progress tracking
            pull_start = time.time()
            
            # Pull with streaming to show progress
            for line in self.docker_client.api.pull(
                self.docker_image,
                stream=True,
                decode=True
            ):
                # Check timeout
                if time.time() - pull_start > timeout_seconds:
                    raise ContainerError(
                        f"Docker image pull timed out after {timeout_seconds}s"
                    )
                
                # Log progress
                if 'status' in line:
                    status = line.get('status', '')
                    progress = line.get('progress', '')
                    if progress:
                        logger.debug(f"[OpenCode] Pull: {status} {progress}")
                    elif 'error' in line:
                        raise ContainerError(f"Image pull error: {line.get('error')}")
            
            pull_duration = time.time() - pull_start
            logger.info(
                f"[OpenCode] Successfully pulled {self.docker_image} in {pull_duration:.1f}s"
            )
            
            return True
            
        except DockerUnavailableError:
            raise
        except ContainerError:
            raise
        except Exception as e:
            raise ContainerError(f"Failed to ensure image availability: {e}")
    
    def get_image_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the Docker image.
        
        Returns:
            Dict with image info (id, tags, size, created) or None if not found
        """
        try:
            image = self.docker_client.images.get(self.docker_image)
            return {
                'id': image.short_id,
                'tags': image.tags,
                'size_mb': image.attrs.get('Size', 0) / (1024 * 1024),
                'created': image.attrs.get('Created', '')
            }
        except ImageNotFound:
            return None
        except Exception as e:
            logger.warning(f"[OpenCode] Could not get image info: {e}")
            return None
    
    async def execute(
        self,
        job_id: str,
        workspace_path: Path,
        prompt: str,
        job_type: str,
        cancellation_event: Optional[asyncio.Event] = None,
        repos: Optional[List[Dict[str, Any]]] = None,
        mcp_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute an OpenCode job.
        
        Args:
            job_id: Unique job identifier
            workspace_path: Path to the workspace with cloned repos
            prompt: The prompt to send to OpenCode
            job_type: Type of job for result validation
            cancellation_event: Optional event to signal cancellation
            
        Returns:
            Parsed result from OpenCode
            
        Raises:
            DockerUnavailableError: If Docker is not available
            ContainerError: If container operations fail
            OpenCodeTimeoutError: If execution times out
            ResultError: If result extraction fails
            asyncio.CancelledError: If job was cancelled
        """
        container = None
        container_id = None
        
        # Use semaphore if configured
        if self._semaphore:
            async with self._semaphore:
                return await self._execute_internal(
                    job_id, workspace_path, prompt, job_type, cancellation_event, repos, mcp_config
                )
        else:
            return await self._execute_internal(
                job_id, workspace_path, prompt, job_type, cancellation_event, repos, mcp_config
            )
    
    async def _execute_internal(
        self,
        job_id: str,
        workspace_path: Path,
        prompt: str,
        job_type: str,
        cancellation_event: Optional[asyncio.Event] = None,
        repos: Optional[List[Dict[str, Any]]] = None,
        mcp_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Internal execution logic"""
        container = None
        container_id = None
        start_time = time.time()
        
        try:
            # Check cancellation before starting
            if cancellation_event and cancellation_event.is_set():
                raise asyncio.CancelledError("Job cancelled before container spawn")
            
            # Spawn container
            container, port = await self._spawn_container(job_id, workspace_path, repos, mcp_config)
            container_id = container.id
            self._current_container = container  # Store for diagnostics
            
            logger.info(f"[OpenCode] Job {job_id}: Container started on port {port}")
            
            # Check cancellation after spawn
            if cancellation_event and cancellation_event.is_set():
                raise asyncio.CancelledError("Job cancelled after container spawn")
            
            # Wait for OpenCode to be ready
            await self._wait_for_ready(port)
            
            logger.info(f"[OpenCode] Job {job_id}: OpenCode is ready, sending prompt")
            
            # Create session and send prompt
            session_id = await self._create_session(port)
            
            # Check cancellation before sending prompt
            if cancellation_event and cancellation_event.is_set():
                raise asyncio.CancelledError("Job cancelled before prompt send")
            
            # Send prompt and stream response
            await self._send_prompt_and_stream(port, session_id, prompt, job_id, cancellation_event)
            
            # Check cancellation after streaming
            if cancellation_event and cancellation_event.is_set():
                raise asyncio.CancelledError("Job cancelled after streaming")
            
            # Small delay to allow file system writes to complete
            await asyncio.sleep(1.0)
            
            # Read result file
            result = await self._read_result(workspace_path, job_type, job_id)
            
            execution_time = time.time() - start_time
            logger.info(
                f"[OpenCode] Job {job_id}: Completed in {execution_time:.1f}s"
            )
            
            return result
            
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            logger.error(
                f"[OpenCode] Job {job_id}: Timeout after {execution_time:.1f}s"
            )
            raise OpenCodeTimeoutError(
                f"OpenCode execution timeout after {self.job_timeout_seconds}s"
            )
            
        finally:
            # Always cleanup container
            if container_id:
                await self._stop_container(container_id)
            # Clear container reference
            self._current_container = None
    
    def _check_mcp_network(self) -> bool:
        """
        Check if the MCP network exists.
        
        Returns:
            True if network exists, False otherwise
        """
        if not self.mcp_network_name:
            return False
        
        try:
            networks = self.docker_client.networks.list(names=[self.mcp_network_name])
            return len(networks) > 0
        except Exception as e:
            logger.warning(f"[OpenCode] Failed to check MCP network {self.mcp_network_name}: {e}")
            return False
    
    def _extract_workspace_from_url(self, url: str) -> Optional[str]:
        """
        Extract workspace name from Bitbucket repository URL.
        
        Supports formats:
        - https://bitbucket.org/{workspace}/{repo}.git
        - git@bitbucket.org:{workspace}/{repo}.git
        - https://{workspace}@bitbucket.org/{workspace}/{repo}.git
        
        Args:
            url: Repository URL
            
        Returns:
            Workspace name or None if not a Bitbucket URL or cannot be extracted
        """
        if not url or 'bitbucket' not in url.lower():
            return None
        
        try:
            # Remove .git suffix
            url = url.rstrip('.git')
            
            # Handle git@ format: git@bitbucket.org:workspace/repo
            if url.startswith('git@'):
                parts = url.split(':')
                if len(parts) >= 2:
                    path_parts = parts[1].split('/')
                    if len(path_parts) >= 2:
                        return path_parts[0]
            
            # Handle https:// format: https://bitbucket.org/workspace/repo
            # or https://workspace@bitbucket.org/workspace/repo
            if '://' in url:
                # Remove protocol and any auth
                url_part = url.split('://', 1)[1]
                # Remove username@ if present
                if '@' in url_part:
                    url_part = url_part.split('@', 1)[1]
                # Split by / and get workspace (second part after domain)
                parts = url_part.split('/')
                # Find bitbucket.org and get next part
                for i, part in enumerate(parts):
                    if 'bitbucket' in part.lower() and i + 1 < len(parts):
                        return parts[i + 1]
            
            return None
        except Exception as e:
            logger.warning(f"Could not extract workspace from URL {url}: {e}")
            return None
    
    def _sanitize_workspace_for_docker(self, workspace: str) -> str:
        """
        Sanitize workspace name for use in Docker service/container names.
        
        This matches the sanitization used in generate-mcp-compose.py to ensure
        hostnames in opencode.json match the actual Docker service names.
        
        Docker naming rules:
        - Must start with a letter or number
        - Can contain letters, numbers, underscores, and hyphens
        - Cannot contain special characters that break YAML or Docker
        
        Args:
            workspace: Workspace name to validate
            
        Returns:
            Sanitized workspace name safe for Docker
        """
        if not workspace:
            return "workspace"
        
        # Remove any characters that could break Docker naming or YAML
        # Allow: alphanumeric, hyphens, underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '-', workspace)
        
        # Ensure it starts with alphanumeric (Docker requirement)
        if sanitized and not sanitized[0].isalnum():
            sanitized = 'w' + sanitized
        
        # Remove consecutive hyphens/underscores
        sanitized = re.sub(r'[-_]{2,}', '-', sanitized)
        
        # Remove leading/trailing hyphens/underscores
        sanitized = sanitized.strip('-_')
        
        # If empty after sanitization, use a default
        if not sanitized:
            sanitized = 'workspace'
        
        return sanitized
    
    def _sanitize_workspace_for_json_key(self, workspace: Optional[str]) -> str:
        """
        Sanitize workspace name for use as JSON key.
        
        For Docker hostname matching, we use the same sanitization as Docker service names.
        This ensures hostnames in opencode.json match the actual Docker service names.
        
        Args:
            workspace: Workspace name (may be None or empty)
            
        Returns:
            Sanitized workspace name safe for JSON keys and Docker hostnames
        """
        if not workspace:
            return "default"
        
        # Strip whitespace first
        workspace = workspace.strip()
        
        # If empty after stripping, use default
        if not workspace:
            return "default"
        
        # Use Docker sanitization to ensure hostnames match service names
        return self._sanitize_workspace_for_docker(workspace)
    
    def _generate_opencode_json(
        self,
        repos: Optional[List[Dict[str, Any]]] = None,
        mcp_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate opencode.json configuration based on repos and MCP configuration.
        
        Args:
            repos: List of repo specs with 'url' and optional 'branch'
            mcp_config: MCP configuration from config.yaml
            
        Returns:
            opencode.json configuration dict
        """
        if not mcp_config:
            mcp_config = {}
        
        # Extract unique workspaces from repos
        workspaces = set()
        if repos:
            for repo in repos:
                url = repo.get('url', '')
                if url:
                    workspace = self._extract_workspace_from_url(url)
                    if workspace:
                        workspaces.add(workspace)
        
        # Get configured workspaces from config
        configured_workspaces = []
        try:
            from .config import Config
            config = Config()
            configured_workspaces = config.get_bitbucket_workspaces()
        except Exception:
            pass
        
        # Build Bitbucket MCP URLs
        bitbucket_mcp_urls = []
        bitbucket_mcp_config = mcp_config.get('bitbucket', {})
        
        if workspaces and configured_workspaces:
            # For each workspace found in repos, find corresponding MCP instance
            # Note: We need to match using original workspace names, but sanitize for hostnames
            # to match Docker service names created by generate-mcp-compose.py
            base_port = bitbucket_mcp_config.get('port', 7001)
            for workspace in sorted(workspaces):
                if workspace in configured_workspaces:
                    index = configured_workspaces.index(workspace)
                    port = base_port + index
                    # Sanitize workspace name for Docker hostname to match service names
                    sanitized_workspace = self._sanitize_workspace_for_docker(workspace)
                    hostname = f"bitbucket-mcp-{sanitized_workspace}"
                    bitbucket_mcp_urls.append({
                        "workspace": workspace,  # Keep original for JSON key sanitization
                        "url": f"http://{hostname}:{port}/mcp",
                        "enabled": True,
                        "read_only": True
                    })
                else:
                    # Workspace found in repos but not configured - log warning
                    logger.warning(
                        f"[OpenCode] Workspace '{workspace}' found in repo URLs but not in configured workspaces. "
                        f"Configured workspaces: {configured_workspaces}. This workspace will not have MCP access."
                    )
        elif configured_workspaces:
            # If no repos provided or workspaces not found, use first configured workspace
            # (fallback behavior)
            base_port = bitbucket_mcp_config.get('port', 7001)
            workspace = configured_workspaces[0]
            # Sanitize workspace name for Docker hostname to match service names
            sanitized_workspace = self._sanitize_workspace_for_docker(workspace)
            hostname = f"bitbucket-mcp-{sanitized_workspace}"
            port = base_port
            bitbucket_mcp_urls.append({
                "workspace": workspace,  # Keep original for JSON key sanitization
                "url": f"http://{hostname}:{port}/mcp",
                "enabled": True,
                "read_only": True
            })
        else:
            # Fallback to default single Bitbucket MCP
            bitbucket_mcp_url = bitbucket_mcp_config.get('url', 'http://bitbucket-mcp:7001/mcp')
            # Try to extract workspace from URL if possible, otherwise use None (will be sanitized to "default")
            fallback_workspace = None
            if 'bitbucket-mcp-' in bitbucket_mcp_url:
                # Extract workspace from hostname like "bitbucket-mcp-workspace1"
                try:
                    hostname_part = bitbucket_mcp_url.split('//')[1].split(':')[0] if '//' in bitbucket_mcp_url else bitbucket_mcp_url
                    if 'bitbucket-mcp-' in hostname_part:
                        fallback_workspace = hostname_part.split('bitbucket-mcp-')[1]
                except Exception:
                    pass
            bitbucket_mcp_urls.append({
                "url": bitbucket_mcp_url,
                "workspace": fallback_workspace,  # Include workspace if we can extract it
                "enabled": bitbucket_mcp_config.get('enabled', True),
                "read_only": True
            })
        
        # Build Atlassian MCP config
        atlassian_mcp_config = mcp_config.get('atlassian', {})
        # Calculate Atlassian MCP port based on number of configured Bitbucket MCP instances
        # If 0 or 1 Bitbucket instances, use port 7002. Otherwise use base_port + count
        base_port = bitbucket_mcp_config.get('port', 7001)
        configured_count = len(configured_workspaces) if configured_workspaces else 0
        if configured_count > 1:
            atlassian_port = base_port + configured_count
        else:
            atlassian_port = 7002
        atlassian_mcp_url = atlassian_mcp_config.get('url', f'http://atlassian-mcp:{atlassian_port}/mcp')
        
        # Build opencode.json structure
        # OpenCode supports multiple MCP servers as separate keys in the mcp object
        mcp_dict = {}
        
        # Add Bitbucket MCP instances (always use bitbucket-{workspace} format)
        if bitbucket_mcp_urls:
            workspaces_used = []
            for mcp_url_config in bitbucket_mcp_urls:
                workspace = mcp_url_config.get("workspace")
                sanitized_workspace = self._sanitize_workspace_for_json_key(workspace)
                mcp_dict[f"bitbucket-{sanitized_workspace}"] = {
                    "url": mcp_url_config["url"],
                    "enabled": mcp_url_config.get("enabled", True),
                    "read_only": mcp_url_config.get("read_only", True)
                }
                workspaces_used.append(sanitized_workspace)
            
            if len(bitbucket_mcp_urls) == 1:
                logger.debug(
                    f"[OpenCode] Single Bitbucket MCP instance configured: "
                    f"{workspaces_used[0]}"
                )
            else:
                logger.info(
                    f"[OpenCode] Multiple Bitbucket MCP instances enabled ({len(bitbucket_mcp_urls)}): "
                    f"{', '.join(workspaces_used)}"
                )
        else:
            # No Bitbucket MCP URLs configured
            logger.warning("[OpenCode] No Bitbucket MCP instances configured")
        
        # Add Atlassian MCP
        mcp_dict["atlassian"] = {
            "enabled": atlassian_mcp_config.get('enabled', True),
            "url": atlassian_mcp_url,
            "read_only": True
        }
        
        return {
            "mcp": mcp_dict,
            "policy": {
                "max_calls_per_run": mcp_config.get('policy', {}).get('max_calls_per_run', 50)
            }
        }
    
    async def _spawn_container(
        self,
        job_id: str,
        workspace_path: Path,
        repos: Optional[List[Dict[str, Any]]] = None,
        mcp_config: Optional[Dict[str, Any]] = None
    ) -> tuple:
        """
        Spawn an OpenCode container.
        
        Note: ensure_image_available() should be called during startup to pre-pull
        the image. This method will fail fast if the image is not available.
        
        Returns:
            Tuple of (container, host_port)
        """
        container_name = f"{CONTAINER_NAME_PREFIX}{job_id}"
        
        try:
            # Check if image exists (should be pre-pulled during startup)
            try:
                self.docker_client.images.get(self.docker_image)
            except ImageNotFound:
                # Try to pull as fallback
                logger.warning(
                    f"[OpenCode] Image {self.docker_image} not found locally, "
                    "attempting pull (this should have been done during startup)"
                )
                try:
                    self.docker_client.images.pull(self.docker_image)
                except Exception as pull_error:
                    raise ImagePullError(
                        f"Docker image '{self.docker_image}' not found and pull failed: {pull_error}. "
                        "Ensure the image is pulled before running jobs (call ensure_image_available() on startup)."
                    )
            
            # Check MCP network if configured
            network_config = None
            if self.mcp_network_name:
                if self._check_mcp_network():
                    network_config = self.mcp_network_name
                    logger.info(f"[OpenCode] Connecting container to MCP network: {self.mcp_network_name}")
                else:
                    logger.warning(
                        f"[OpenCode] MCP network '{self.mcp_network_name}' not found. "
                        "Container will not be able to access MCP servers. "
                        "Start MCP services with: python main.py mcp start"
                    )
            
            # Build environment variables for container
            container_env = self._build_container_environment()
            
            # Prepare volumes - workspace is always mounted
            volumes = {
                str(workspace_path): {"bind": "/workspace", "mode": "rw"}
            }
            
            # Generate opencode.json dynamically based on repos and MCP config
            opencode_json_content = self._generate_opencode_json(repos, mcp_config)
            
            # Create temporary opencode.json file in workspace
            opencode_json_path = workspace_path / "opencode.json"
            try:
                with open(opencode_json_path, 'w') as f:
                    json.dump(opencode_json_content, f, indent=2)
            except (IOError, OSError) as e:
                raise ContainerError(
                    f"Failed to create opencode.json in workspace: {e}. "
                    "Ensure workspace directory is writable."
                )
            
            # Mount the generated opencode.json
            volumes[str(opencode_json_path)] = {
                "bind": "/app/opencode.json",
                "mode": "ro"
            }
            logger.debug(f"[OpenCode] Generated and mounting opencode.json to /app/opencode.json")
            # Log MCP config (all bitbucket instances use bitbucket-{workspace} format)
            bitbucket_keys = [k for k in opencode_json_content['mcp'].keys() if k.startswith('bitbucket-')]
            if bitbucket_keys:
                bitbucket_info = f"{len(bitbucket_keys)} workspace(s): {', '.join(bitbucket_keys)}"
            else:
                bitbucket_info = "N/A"
            atlassian_info = opencode_json_content['mcp'].get('atlassian', {}).get('url', 'N/A')
            logger.debug(f"[OpenCode] MCP config: Bitbucket={bitbucket_info}, Atlassian={atlassian_info}")
            
            # Create and start container
            container_kwargs = {
                "image": self.docker_image,
                "name": container_name,
                "command": ["serve", "--hostname", "0.0.0.0", "--port", "4096"],
                "volumes": volumes,
                "ports": {"4096/tcp": None},  # Random host port
                "detach": True,
                "remove": False,  # We remove manually after getting result
                "working_dir": "/workspace",
                "environment": container_env
            }
            
            # Add network if MCP network is configured and exists
            if network_config:
                container_kwargs["network"] = network_config
            
            container = self.docker_client.containers.run(**container_kwargs)
            
            # Get the mapped port
            container.reload()
            port_bindings = container.attrs['NetworkSettings']['Ports']
            host_port = int(port_bindings['4096/tcp'][0]['HostPort'])
            
            logger.info(
                f"[OpenCode] Container {container_name} started, "
                f"port 4096 -> {host_port}"
            )
            
            return container, host_port
            
        except Exception as e:
            logger.error(f"Failed to spawn container: {e}")
            raise ContainerError(f"Failed to spawn OpenCode container: {e}")
    
    async def _wait_for_ready(
        self,
        port: int,
        timeout: int = 60,
        interval: float = 1.0
    ):
        """Wait for OpenCode to be ready to accept requests"""
        url = f"http://localhost:{port}/session"
        headers = {"Accept": "application/json"}
        deadline = time.time() + timeout
        
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                try:
                    response = await client.get(url, headers=headers, timeout=5.0)
                    if response.status_code == 200:
                        return
                except Exception:
                    pass
                await asyncio.sleep(interval)
        
        raise ContainerError(
            f"OpenCode container not ready after {timeout}s"
        )
    
    async def _create_session(self, port: int) -> str:
        """Create an OpenCode session and return session ID"""
        url = f"http://localhost:{port}/session"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=headers,
                json={},
                timeout=30.0
            )
            response.raise_for_status()
            content = response.text
            if not content:
                raise OpenCodeError(f"Empty response from /session endpoint")
            data = response.json()
            session_id = data.get("session_id") or data.get("id")
            if not session_id:
                raise OpenCodeError(f"No session_id in response: {data}")
            return session_id
    
    async def _send_prompt_and_stream(
        self,
        port: int,
        session_id: str,
        prompt: str,
        job_id: str,
        cancellation_event: Optional[asyncio.Event] = None
    ):
        """
        Send prompt and stream SSE response with retry logic.
        
        Uses httpx-sse for proper SSE handling and implements exponential
        backoff for transient failures. Supports cancellation via event.
        """
        url = f"http://localhost:{port}/session/{session_id}/message"
        headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
        payload = {"parts": [{"type": "text", "text": prompt}]}
        
        logger.debug(f"[OpenCode] Job {job_id}: Sending prompt ({len(prompt)} chars)")
        
        # Initialize conversation logging if debug mode enabled
        if self.debug_conversation_logging:
            self._conversation_logs = []
            self._conversation_start_time = time.time()
            self._conversation_prompt = prompt
        
        last_error = None
        backoff = SSE_INITIAL_BACKOFF
        
        try:
            for attempt in range(SSE_MAX_RETRIES):
            # Check cancellation before each attempt
            if cancellation_event and cancellation_event.is_set():
                raise asyncio.CancelledError("Job cancelled during SSE streaming")
            
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.job_timeout_seconds, connect=30.0)
                ) as client:
                    # First, make the request and check Content-Type
                    response = await client.post(url, headers=headers, json=payload)
                    content_type = response.headers.get("content-type", "")
                    
                    # If response is JSON, OpenCode completed synchronously or returned an error
                    if "application/json" in content_type:
                        try:
                            data = response.json()
                            # Log the response for debugging
                            logger.debug(f"[OpenCode] Job {job_id}: JSON response: {json.dumps(data, indent=2)[:500]}")
                            
                            # Store response data for later diagnostics (before error checking)
                            self._last_json_response = data
                            
                            # Check for error in various possible locations in the response
                            error_info = None
                            error_location = None
                            
                            # Check direct "error" key
                            if "error" in data:
                                error_info = data.get('error', {})
                                error_location = "root"
                            # Check nested "info.error" structure (common in OpenCode responses)
                            elif "info" in data and isinstance(data.get('info'), dict) and "error" in data['info']:
                                error_info = data['info'].get('error', {})
                                error_location = "info.error"
                            
                            if error_info:
                                # Extract error details
                                error_msg = 'Unknown error'
                                error_name = ''
                                status_code = None
                                
                                if isinstance(error_info, dict):
                                    error_msg = error_info.get('message', error_info.get('data', {}).get('message', 'Unknown error'))
                                    error_name = error_info.get('name', '')
                                    # Check both direct statusCode and nested in data
                                    status_code = error_info.get('statusCode') or error_info.get('data', {}).get('statusCode')
                                else:
                                    # Error is a string
                                    error_msg = str(error_info)
                                
                                # Check for authentication errors
                                if status_code == 401 or 'authentication' in error_msg.lower() or 'invalid auth' in error_msg.lower():
                                    provider = self.llm_config.get('provider', 'unknown')
                                    provider_to_env_key = {
                                        'openai': 'OPENAI_API_KEY',
                                        'claude': 'ANTHROPIC_API_KEY',
                                        'gemini': 'GOOGLE_API_KEY',
                                        'kimi': 'MOONSHOT_API_KEY',
                                    }
                                    required_key = provider_to_env_key.get(provider, 'API_KEY')
                                    
                                    # Map provider to OpenCode-specific env var names (ONLY OpenCode keys are used)
                                    opencode_env_var_map = {
                                        'openai': 'OPENCODE_OPENAI_API_KEY',
                                        'claude': 'OPENCODE_ANTHROPIC_API_KEY',
                                        'gemini': 'OPENCODE_GOOGLE_API_KEY',
                                        'kimi': 'OPENCODE_MOONSHOT_API_KEY',
                                    }
                                    opencode_env_var = opencode_env_var_map.get(provider, '')
                                    
                                    logger.error(
                                        f"[OpenCode] Job {job_id}: Authentication error (401) from OpenCode. "
                                        f"Location: {error_location}, Provider: {provider}, Required env var: {opencode_env_var}. "
                                        f"Error: {error_msg}"
                                    )
                                    raise ContainerError(
                                        f"OpenCode authentication failed (401). "
                                        f"The LLM API key for provider '{provider}' may be missing, invalid, or expired. "
                                        f"Please set {opencode_env_var} in your .env file. "
                                        f"OpenCode ONLY uses OpenCode-specific API keys and does not fall back to main LLM configuration."
                                    )
                                
                                logger.error(f"[OpenCode] Job {job_id}: OpenCode returned error ({error_location}): {error_name} - {error_msg}")
                                raise ContainerError(f"OpenCode returned error: {error_name} - {error_msg}")
                            
                            # Otherwise, assume it completed successfully
                            logger.info(f"[OpenCode] Job {job_id}: Received JSON response (non-streaming completion)")
                            # For non-streaming responses, record the JSON response as an event
                            if self.debug_conversation_logging:
                                event_record = {
                                    "timestamp": time.time(),
                                    "event_type": "json_response",
                                    "data": json.dumps(data),
                                    "raw_event": data
                                }
                                self._conversation_logs.append(event_record)
                                await self._save_conversation_logs(job_id)
                            return
                        except json.JSONDecodeError as e:
                            logger.warning(f"[OpenCode] Job {job_id}: Invalid JSON in response: {e}")
                            logger.warning(f"[OpenCode] Job {job_id}: Response text: {response.text[:500]}")
                            raise ContainerError("Invalid JSON response from OpenCode")
                    
                    # For SSE responses, use httpx-sse
                    if "text/event-stream" not in content_type:
                        raise SSEError(f"Unexpected Content-Type: {content_type}")
                    
                    # Re-make request for SSE streaming
                    async with aconnect_sse(
                        client,
                        "POST",
                        url,
                        headers=headers,
                        json=payload
                    ) as event_source:
                        async for event in event_source.aiter_sse():
                            # Check cancellation periodically during streaming
                            if cancellation_event and cancellation_event.is_set():
                                logger.info(f"[OpenCode] Job {job_id}: Cancellation requested during streaming")
                                raise asyncio.CancelledError("Job cancelled during SSE streaming")
                            
                            self._process_sse_event_obj(event, job_id)
                            
                            # Check for done event
                            if event.event == "done":
                                logger.info(f"[OpenCode] Job {job_id}: Prompt streaming completed")
                                return
                
                # If we get here without 'done', streaming completed normally
                logger.info(f"[OpenCode] Job {job_id}: Prompt streaming completed")
                return
                
            except asyncio.CancelledError:
                raise  # Re-raise cancellation errors
                
            except SSEError as e:
                last_error = e
                logger.warning(
                    f"[OpenCode] Job {job_id}: SSE error on attempt {attempt + 1}/{SSE_MAX_RETRIES}: {e}"
                )
                
            except httpx.ConnectError as e:
                last_error = e
                logger.warning(
                    f"[OpenCode] Job {job_id}: Connection error on attempt {attempt + 1}/{SSE_MAX_RETRIES}: {e}"
                )
                
            except httpx.ReadError as e:
                last_error = e
                logger.warning(
                    f"[OpenCode] Job {job_id}: Read error on attempt {attempt + 1}/{SSE_MAX_RETRIES}: {e}"
                )
            
            # Exponential backoff before retry
            if attempt < SSE_MAX_RETRIES - 1:
                logger.info(f"[OpenCode] Job {job_id}: Retrying in {backoff:.1f}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * SSE_BACKOFF_MULTIPLIER, SSE_MAX_BACKOFF)
        
        # All retries exhausted
        raise ContainerError(
            f"SSE streaming failed after {SSE_MAX_RETRIES} attempts: {last_error}"
        )
        finally:
            # Save conversation logs even on failure if debug mode enabled
            if self.debug_conversation_logging:
                await self._save_conversation_logs(job_id)
    
    def _process_sse_event_obj(self, event, job_id: str):
        """Process an SSE event object from httpx-sse"""
        event_type = event.event or "message"
        data = event.data or ""
        timestamp = time.time()
        
        # Capture full event for debug logging if enabled
        if self.debug_conversation_logging:
            event_record = {
                "timestamp": timestamp,
                "event_type": event_type,
                "data": data,
                "raw_event": {
                    "event": event.event,
                    "data": event.data,
                    "id": getattr(event, 'id', None),
                }
            }
            self._conversation_logs.append(event_record)
        
        if event_type == "error":
            logger.error(f"[OpenCode] Job {job_id} SSE error: {data}")
        elif event_type == "done":
            logger.debug(f"[OpenCode] Job {job_id} SSE done")
        else:
            # Log truncated data for debugging
            if len(data) > 100:
                logger.debug(f"[OpenCode] Job {job_id} SSE {event_type}: {data[:100]}...")
            else:
                logger.debug(f"[OpenCode] Job {job_id} SSE {event_type}: {data}")
    
    def _process_sse_event(self, event_str: str, job_id: str):
        """Process an SSE event"""
        event_type = "message"
        data = ""
        
        for line in event_str.split("\n"):
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        
        if event_type == "error":
            logger.error(f"[OpenCode] Job {job_id} SSE error: {data}")
        elif event_type == "done":
            logger.debug(f"[OpenCode] Job {job_id} SSE done")
        else:
            # Log truncated data for debugging
            logger.debug(
                f"[OpenCode] Job {job_id} SSE {event_type}: {data[:100]}..."
                if len(data) > 100 else
                f"[OpenCode] Job {job_id} SSE {event_type}: {data}"
            )
    
    async def _save_conversation_logs(self, job_id: str):
        """
        Save conversation logs to JSON and text files.
        
        Args:
            job_id: Job identifier for file naming
        """
        if not self.debug_conversation_logging:
            return
        
        if not self._conversation_start_time:
            logger.warning(f"[OpenCode] Job {job_id}: Cannot save conversation logs - no start time recorded")
            return
        
        end_time = time.time()
        duration = end_time - self._conversation_start_time
        
        # Create log directory if it doesn't exist
        log_dir = Path(self.conversation_log_dir)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[OpenCode] Job {job_id}: Failed to create log directory {log_dir}: {e}")
            return
        
        # Prepare log data
        start_time_str = datetime.fromtimestamp(self._conversation_start_time, tz=timezone.utc).isoformat()
        end_time_str = datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat()
        
        log_data = {
            "job_id": job_id,
            "start_time": start_time_str,
            "end_time": end_time_str,
            "duration_seconds": round(duration, 3),
            "prompt": self._conversation_prompt or "",
            "events": self._conversation_logs
        }
        
        # Save JSON file
        json_path = log_dir / f"{job_id}.json"
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(log_data, f, indent=2, ensure_ascii=False)
            logger.info(f"[OpenCode] Job {job_id}: Saved conversation log to {json_path}")
        except Exception as e:
            logger.error(f"[OpenCode] Job {job_id}: Failed to save JSON log file: {e}")
        
        # Save human-readable text file
        text_path = log_dir / f"{job_id}.log"
        try:
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(f"OpenCode Conversation Log - Job: {job_id}\n")
                f.write(f"Started: {start_time_str}\n")
                f.write(f"Ended: {end_time_str}\n")
                f.write(f"Duration: {duration:.3f}s\n")
                f.write(f"\n{'='*80}\n")
                f.write("PROMPT\n")
                f.write(f"{'='*80}\n")
                f.write(f"{self._conversation_prompt or '(no prompt recorded)'}\n")
                f.write(f"\n{'='*80}\n")
                f.write("EVENTS\n")
                f.write(f"{'='*80}\n")
                
                for event in self._conversation_logs:
                    event_time = datetime.fromtimestamp(event['timestamp'], tz=timezone.utc)
                    event_time_str = event_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    event_type = event.get('event_type', 'unknown')
                    event_data = event.get('data', '')
                    
                    f.write(f"[{event_time_str}] [{event_type}] {event_data}\n")
            
            logger.info(f"[OpenCode] Job {job_id}: Saved conversation log to {text_path}")
        except Exception as e:
            logger.error(f"[OpenCode] Job {job_id}: Failed to save text log file: {e}")
    
    async def _read_result(
        self,
        workspace_path: Path,
        job_type: str,
        job_id: str
    ) -> Dict[str, Any]:
        """
        Read and validate result.json from workspace.
        
        Args:
            workspace_path: Path to workspace
            job_type: Type of job for validation
            job_id: Job ID for logging
            
        Returns:
            Parsed and validated result
            
        Raises:
            ResultError: If result cannot be read or validated
        """
        result_path = workspace_path / self.result_file
        
        # Check if file exists
        if not result_path.exists():
            logger.error(f"Result file not found: {result_path}")
            
            # Enhanced diagnostics: list all files in workspace
            try:
                all_files = []
                for root, dirs, files in os.walk(workspace_path):
                    for file in files:
                        rel_path = os.path.relpath(os.path.join(root, file), workspace_path)
                        all_files.append(rel_path)
                
                logger.error(f"[OpenCode] Job {job_id}: Workspace contents ({len(all_files)} files):")
                # Log first 50 files to avoid log spam
                for file_path in sorted(all_files)[:50]:
                    logger.error(f"  - {file_path}")
                if len(all_files) > 50:
                    logger.error(f"  ... and {len(all_files) - 50} more files")
                
                # Check for similar filenames
                similar_files = [f for f in all_files if 'result' in f.lower() or 'json' in f.lower()]
                if similar_files:
                    logger.error(f"[OpenCode] Job {job_id}: Found similar files: {similar_files}")
                    
            except Exception as e:
                logger.warning(f"[OpenCode] Job {job_id}: Could not list workspace files: {e}")
            
            # Log JSON response if available
            if self._last_json_response:
                logger.error(f"[OpenCode] Job {job_id}: Last JSON response from OpenCode: {json.dumps(self._last_json_response, indent=2)[:1000]}")
            
            # Try to get container logs for diagnostics
            try:
                container_to_check = self._current_container
                if not container_to_check:
                    # Fallback: try to get by name
                    container_name = f"{CONTAINER_NAME_PREFIX}{job_id}"
                    try:
                        container_to_check = self.docker_client.containers.get(container_name)
                    except NotFound:
                        logger.warning(f"[OpenCode] Job {job_id}: Container {container_name} not found for log inspection")
                        container_to_check = None
                
                if container_to_check:
                    try:
                        logs = container_to_check.logs(tail=50).decode('utf-8', errors='replace')
                        logger.error(f"[OpenCode] Job {job_id}: Container logs (last 50 lines):\n{logs}")
                    except Exception as log_error:
                        logger.warning(f"[OpenCode] Job {job_id}: Could not read container logs: {log_error}")
            except Exception as e:
                logger.warning(f"[OpenCode] Job {job_id}: Could not retrieve container logs: {e}")
            
            raise ResultError(
                f"OpenCode did not produce {self.result_file}. "
                "The LLM may not have followed instructions to write the result file. "
                f"Check logs above for workspace contents and container logs."
            )
        
        # Check file size
        file_size = result_path.stat().st_size
        if file_size > self.max_result_size_bytes:
            raise ResultError(
                f"Result file too large: {file_size / 1024 / 1024:.1f}MB "
                f"(max: {self.max_result_size_bytes / 1024 / 1024}MB)"
            )
        
        # Read and parse JSON
        try:
            with open(result_path, 'r') as f:
                content = f.read()
            
            # Try to extract JSON if wrapped in markdown code block
            content = self._extract_json(content)
            
            result = json.loads(content)
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in result file: {e}")
            raise ResultError(f"Invalid JSON in {self.result_file}: {e}")
        
        # Validate against schema
        try:
            from .opencode_schemas import validate_opencode_result, validate_result_content
            validate_opencode_result(result, job_type)
            
            if not validate_result_content(result, job_type):
                raise ResultError("Result has valid schema but empty/meaningless content")
                
        except ImportError:
            logger.warning("Schema validation skipped - opencode_schemas not available")
        except Exception as e:
            raise ResultError(f"Result validation failed: {e}")
        
        logger.info(f"Successfully read result: {len(content)} bytes")
        return result
    
    def _extract_json(self, content: str) -> str:
        """Extract JSON from content, handling markdown code blocks"""
        content = content.strip()
        
        # If already valid JSON, return as-is
        if content.startswith('{') or content.startswith('['):
            return content
        
        # Try to extract from markdown code block
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', content)
        if json_match:
            return json_match.group(1).strip()
        
        return content
    
    async def _stop_container(self, container_id: str):
        """Stop and remove a container"""
        try:
            container = self.docker_client.containers.get(container_id)
            container.stop(timeout=5)
            container.remove(force=True)
            logger.info(f"[OpenCode] Container {container_id[:12]} stopped and removed")
        except NotFound:
            logger.debug(f"[OpenCode] Container {container_id[:12]} already removed")
        except Exception as e:
            logger.warning(f"[OpenCode] Error stopping container {container_id[:12]}: {e}")
    
    async def kill_container(self, container_id: str):
        """Force kill a container (for cancellation)"""
        try:
            container = self.docker_client.containers.get(container_id)
            container.kill()
            container.remove(force=True)
            logger.info(f"[OpenCode] Container {container_id[:12]} killed")
        except NotFound:
            pass
        except Exception as e:
            logger.warning(f"[OpenCode] Error killing container {container_id[:12]}: {e}")
    
    async def cleanup_orphaned_containers(self, max_age_minutes: int = 30) -> int:
        """
        Clean up orphaned OpenCode containers.
        
        Args:
            max_age_minutes: Maximum age of containers to keep
            
        Returns:
            Number of containers cleaned up
        """
        cleaned_count = 0
        
        try:
            containers = self.docker_client.containers.list(
                filters={"name": CONTAINER_NAME_PREFIX}
            )
            
            for container in containers:
                try:
                    # Parse creation time
                    created_str = container.attrs.get('Created', '')
                    if created_str:
                        # Docker returns ISO format with nanoseconds
                        created_str = created_str.split('.')[0] + 'Z'
                        created = datetime.fromisoformat(
                            created_str.replace('Z', '+00:00')
                        )
                        
                        age = datetime.now(timezone.utc) - created
                        if age > timedelta(minutes=max_age_minutes):
                            logger.info(
                                f"[OpenCode] Removing orphaned container: "
                                f"{container.name} (age: {age})"
                            )
                            container.stop(timeout=5)
                            container.remove(force=True)
                            cleaned_count += 1
                            
                except Exception as e:
                    logger.warning(
                        f"[OpenCode] Error checking container {container.name}: {e}"
                    )
                    
        except Exception as e:
            logger.error(f"[OpenCode] Error during orphan cleanup: {e}")
        
        if cleaned_count > 0:
            logger.info(f"[OpenCode] Cleaned up {cleaned_count} orphaned containers")
        
        return cleaned_count


# Factory function for creating runner from config
def create_opencode_runner(config: Dict[str, Any]) -> OpenCodeRunner:
    """
    Create an OpenCodeRunner from configuration.
    
    Args:
        config: Configuration dict with 'opencode' section
        
    Returns:
        Configured OpenCodeRunner instance
    """
    opencode_config = config.get('opencode', {})
    
    runner = OpenCodeRunner(
        docker_image=opencode_config.get('docker_image', 'ghcr.io/anomalyco/opencode'),
        job_timeout_minutes=int(opencode_config.get('job_timeout_minutes', 20)),
        max_result_size_mb=int(opencode_config.get('max_result_size_mb', 10)),
        result_file=opencode_config.get('result_file', 'result.json')
    )
    
    # Set concurrency limit
    max_concurrent = int(opencode_config.get('max_concurrent', 2))
    runner.set_concurrency_limit(max_concurrent)
    
    return runner
