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
import hashlib
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
        self._log_file_handle: Optional[Any] = None  # File handle for streaming log file
        self._log_file_path: Optional[Path] = None  # Path to streaming log file
        self._container_log_task: Optional[asyncio.Task] = None  # Background task for streaming container logs
        self._last_polled_message_length: Dict[str, int] = {}  # Track last seen message length per session_id (deprecated, kept for backward compatibility)
        self._last_polled_message_id: Dict[str, str] = {}  # Track last seen message ID per session_id
        self._last_message_parts_count: Dict[str, Dict[str, int]] = {}  # Track parts count per message per session_id: {session_id: {message_id: count}}
    
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

        # Enable OpenCode debug/verbose logging when debug_conversation_logging is enabled
        # This will make OpenCode output more details to stdout, which we capture
        if self.debug_conversation_logging:
            env["OPENCODE_LOG_LEVEL"] = "debug"
            env["OPENCODE_DEBUG"] = "true"
            logger.info("[OpenCode] Debug mode enabled in container (OPENCODE_LOG_LEVEL=debug, OPENCODE_DEBUG=true)")

        # LLM API Keys - ONLY from config (no environment fallback for OpenCode)
        # Support both formats: provider-specific keys (openai_api_key) and generic (api_key)
        provider = self.llm_config.get('provider')
        
        if not provider or (isinstance(provider, str) and not provider.strip()):
            logger.error("[OpenCode] No LLM provider specified in config - OpenCode requires OPENCODE_LLM_PROVIDER to be set")
            raise OpenCodeError(
                "OpenCode REQUIRES OPENCODE_LLM_PROVIDER to be set in your .env file. "
                "No provider found in LLM configuration. "
                "OpenCode does NOT use fallback values - the environment variable MUST be set."
            )
        
        # OpenCode MUST use OPENCODE_*_API_KEY environment variables
        # BUT OpenCode also expects standard provider environment variables (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
        # We set both to ensure compatibility
        api_key_mappings = [
            ('openai_api_key', 'OPENCODE_OPENAI_API_KEY', 'OPENAI_API_KEY'),
            ('anthropic_api_key', 'OPENCODE_ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEY'),
            ('google_api_key', 'OPENCODE_GOOGLE_API_KEY', 'GOOGLE_API_KEY'),
            ('gemini_api_key', 'OPENCODE_GOOGLE_API_KEY', 'GOOGLE_API_KEY'),  # Gemini uses GOOGLE_API_KEY
            ('moonshot_api_key', 'OPENCODE_MOONSHOT_API_KEY', 'MOONSHOT_API_KEY'),
        ]
        
        # First, try provider-specific keys from config ONLY (no environment fallback for OpenCode)
        # Only set non-empty API keys to avoid passing empty strings to OpenCode
        # Set both OPENCODE_* and standard provider environment variables
        for config_key, opencode_env_key, standard_env_key in api_key_mappings:
            value = self.llm_config.get(config_key)  # Only from config, no os.getenv() fallback
            # Validate that the value is not empty (not None, not empty string, not just whitespace)
            if value and isinstance(value, str) and value.strip():
                value_stripped = value.strip()
                # Set both OPENCODE_* version and standard provider variable
                env[opencode_env_key] = value_stripped
                env[standard_env_key] = value_stripped
                logger.debug(f"[OpenCode] Found API key for {opencode_env_key} and {standard_env_key} from config key {config_key}")
            elif value:
                # Value exists but is empty/whitespace - log warning
                logger.warning(f"[OpenCode] API key for {opencode_env_key} is empty or whitespace, skipping")
        
        # If provider is set and we have a generic 'api_key', map it to both OPENCODE_* and standard provider keys
        if provider and 'api_key' in self.llm_config:
            provider_to_keys = {
                'openai': ('OPENCODE_OPENAI_API_KEY', 'OPENAI_API_KEY'),
                'claude': ('OPENCODE_ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEY'),
                'gemini': ('OPENCODE_GOOGLE_API_KEY', 'GOOGLE_API_KEY'),
                'kimi': ('OPENCODE_MOONSHOT_API_KEY', 'MOONSHOT_API_KEY'),
            }
            keys = provider_to_keys.get(provider)
            if keys:
                opencode_env_key, standard_env_key = keys
                if opencode_env_key not in env:
                    api_key_value = self.llm_config['api_key']
                    # Validate that the API key is not empty
                    if api_key_value and isinstance(api_key_value, str) and api_key_value.strip():
                        value_stripped = api_key_value.strip()
                        # Set both OPENCODE_* version and standard provider variable
                        env[opencode_env_key] = value_stripped
                        env[standard_env_key] = value_stripped
                        logger.debug(f"[OpenCode] Mapped generic api_key to {opencode_env_key} and {standard_env_key} for provider {provider}")
                    else:
                        logger.warning(f"[OpenCode] Generic api_key found in config but is empty or invalid for provider {provider}")
                else:
                    logger.debug(f"[OpenCode] {opencode_env_key} already set, skipping generic api_key mapping")
            else:
                logger.warning(f"[OpenCode] Unknown provider '{provider}', cannot map generic api_key")
        
        # Validate that we have an API key for the provider
        # Check for both OPENCODE_* and standard provider environment variables
        if provider:
            provider_to_keys = {
                'openai': ('OPENCODE_OPENAI_API_KEY', 'OPENAI_API_KEY'),
                'claude': ('OPENCODE_ANTHROPIC_API_KEY', 'ANTHROPIC_API_KEY'),
                'gemini': ('OPENCODE_GOOGLE_API_KEY', 'GOOGLE_API_KEY'),
                'kimi': ('OPENCODE_MOONSHOT_API_KEY', 'MOONSHOT_API_KEY'),
            }
            keys = provider_to_keys.get(provider)
            if keys:
                opencode_env_key, standard_env_key = keys
                if opencode_env_key not in env:
                    config_keys_checked = [k for k, _, _ in api_key_mappings]
                    logger.error(
                        f"[OpenCode] Missing API key for provider '{provider}'. "
                        f"Expected environment variables: {opencode_env_key} or {standard_env_key}. "
                        f"Config keys checked: {config_keys_checked}, generic 'api_key'. "
                        f"Available config keys: {list(self.llm_config.keys())}"
                    )
                    raise OpenCodeError(
                        f"Missing API key for LLM provider '{provider}'. "
                        f"Please configure {opencode_env_key} or set the appropriate API key in the LLM configuration."
                    )
                else:
                    logger.info(f"[OpenCode] API key configured for {provider} (both {opencode_env_key} and {standard_env_key} set)")
        
        # LLM Provider and Model settings
        # OpenCode MUST use OPENCODE_* environment variables ONLY
        if provider:
            env['OPENCODE_LLM_PROVIDER'] = provider
            logger.info(f"[OpenCode] Setting OPENCODE_LLM_PROVIDER={provider} (OpenCode reads this)")
            
            # Get model for the provider - ONLY from OPENCODE_*_MODEL config (strict, no fallbacks)
            # We MUST use only the provider-specific key that comes from OPENCODE_*_MODEL env var
            model = None
            model_source = None
            if provider == 'claude':
                # For claude, ONLY check 'anthropic_model' (from OPENCODE_ANTHROPIC_MODEL)
                # NO fallback to 'claude_model' or 'model' - must be from OPENCODE_ANTHROPIC_MODEL
                model = self.llm_config.get('anthropic_model')
                model_source = 'anthropic_model'
                logger.debug(f"[OpenCode] Model lookup for 'claude': checking ONLY 'anthropic_model' (from OPENCODE_ANTHROPIC_MODEL): {repr(model)}")
            elif provider == 'openai':
                # For openai, ONLY check 'openai_model' (from OPENCODE_OPENAI_MODEL)
                model = self.llm_config.get('openai_model')
                model_source = 'openai_model'
                logger.debug(f"[OpenCode] Model lookup for 'openai': checking ONLY 'openai_model' (from OPENCODE_OPENAI_MODEL): {repr(model)}")
            elif provider == 'gemini':
                # For gemini, ONLY check 'google_model' (from OPENCODE_GOOGLE_MODEL)
                model = self.llm_config.get('google_model')
                model_source = 'google_model'
                logger.debug(f"[OpenCode] Model lookup for 'gemini': checking ONLY 'google_model' (from OPENCODE_GOOGLE_MODEL): {repr(model)}")
            elif provider == 'kimi':
                # For kimi, ONLY check 'moonshot_model' (from OPENCODE_MOONSHOT_MODEL)
                model = self.llm_config.get('moonshot_model')
                model_source = 'moonshot_model'
                logger.debug(f"[OpenCode] Model lookup for 'kimi': checking ONLY 'moonshot_model' (from OPENCODE_MOONSHOT_MODEL): {repr(model)}")
            else:
                # For unknown providers, try provider-specific key
                model_key = f'{provider}_model'
                model = self.llm_config.get(model_key)
                model_source = model_key
                logger.debug(f"[OpenCode] Model lookup for '{provider}': checking ONLY '{model_key}': {repr(model)}")
            
            if model:
                # OpenCode MUST use OPENCODE_*_MODEL environment variables ONLY
                # NOTE: Model is set in opencode.json, but we also set environment variables
                # as a fallback. OpenCode may read from either source.
                # Set provider-specific OPENCODE_*_MODEL environment variables (OpenCode may read these as fallback)
                if provider == 'claude':
                    env['OPENCODE_ANTHROPIC_MODEL'] = model
                    logger.info(f"[OpenCode] Setting OPENCODE_ANTHROPIC_MODEL={model} (fallback if opencode.json model not recognized)")
                elif provider == 'openai':
                    env['OPENCODE_OPENAI_MODEL'] = model
                    logger.info(f"[OpenCode] Setting OPENCODE_OPENAI_MODEL={model} (fallback if opencode.json model not recognized)")
                elif provider == 'gemini':
                    env['OPENCODE_GOOGLE_MODEL'] = model
                    logger.info(f"[OpenCode] Setting OPENCODE_GOOGLE_MODEL={model} (fallback if opencode.json model not recognized)")
                elif provider == 'kimi':
                    env['OPENCODE_MOONSHOT_MODEL'] = model
                    logger.info(f"[OpenCode] Setting OPENCODE_MOONSHOT_MODEL={model} (fallback if opencode.json model not recognized)")
                
                logger.info(f"[OpenCode] Using provider: {provider}, model: {model} (source: {model_source or 'unknown'})")
            else:
                # Model is REQUIRED - raise error, no fallback
                provider_model_var = {
                    'claude': 'OPENCODE_ANTHROPIC_MODEL',
                    'openai': 'OPENCODE_OPENAI_MODEL',
                    'gemini': 'OPENCODE_GOOGLE_MODEL',
                    'kimi': 'OPENCODE_MOONSHOT_MODEL'
                }.get(provider, 'OPENCODE_*_MODEL')
                
                logger.error(f"[OpenCode] No model specified for provider {provider} - OpenCode requires {provider_model_var} to be set")
                logger.error(f"[OpenCode] Available config keys: {list(self.llm_config.keys())}")
                raise OpenCodeError(
                    f"OpenCode REQUIRES {provider_model_var} to be set in your .env file. "
                    f"No model found in config for provider '{provider}'. "
                    "OpenCode does NOT use fallback values - the environment variable MUST be set."
                )
        else:
            # Provider is REQUIRED - this should have been caught earlier, but fail here too
            raise OpenCodeError(
                "OpenCode REQUIRES OPENCODE_LLM_PROVIDER to be set in your .env file. "
                "No provider found in LLM configuration. "
                "OpenCode does NOT use fallback values - the environment variable MUST be set."
            )
        
        # Filter out None/empty values
        filtered_env = {k: v for k, v in env.items() if v and (not isinstance(v, str) or v.strip())}
        
        # Log which API keys are being set (without exposing the actual keys)
        api_keys_set = [k for k in filtered_env.keys() if 'API_KEY' in k]
        if api_keys_set:
            # Separate OPENCODE_* keys from standard provider keys for clarity
            opencode_keys = [k for k in api_keys_set if k.startswith('OPENCODE_')]
            standard_keys = [k for k in api_keys_set if not k.startswith('OPENCODE_')]
            logger.info(f"[OpenCode] Setting API keys - OPENCODE_*: {', '.join(opencode_keys) if opencode_keys else 'none'}, Standard: {', '.join(standard_keys) if standard_keys else 'none'}")
        else:
            logger.warning("[OpenCode] No API keys found in environment configuration")
        
        # Log provider/model info for debugging
        if provider:
            provider_to_env_key = {
                'openai': 'OPENCODE_OPENAI_API_KEY',
                'claude': 'OPENCODE_ANTHROPIC_API_KEY',
                'gemini': 'OPENCODE_GOOGLE_API_KEY',
                'kimi': 'OPENCODE_MOONSHOT_API_KEY',
            }
            required_key = provider_to_env_key.get(provider)
            if required_key:
                if required_key in filtered_env:
                    # Check if the key is actually set (not just present but empty)
                    key_value = filtered_env[required_key]
                    if key_value and len(key_value.strip()) > 0:
                        logger.info(f"[OpenCode] Provider '{provider}' API key is configured ({required_key}, length: {len(key_value)} chars)")
                    else:
                        logger.error(f"[OpenCode] Provider '{provider}' API key ({required_key}) is empty or invalid!")
                else:
                    logger.error(f"[OpenCode] Provider '{provider}' requires {required_key} but it's not set!")
        
        # Log ALL environment variables being set (ONLY OPENCODE_* variables are set)
        llm_env_vars = {k: v for k, v in filtered_env.items() if 'OPENCODE' in k}
        if llm_env_vars:
            logger.info(f"[OpenCode] LLM environment variables being set in container: {list(llm_env_vars.keys())}")
            # Log values (but mask API keys)
            for key, value in llm_env_vars.items():
                if 'API_KEY' in key:
                    logger.info(f"[OpenCode]   {key}=*** (masked)")
                else:
                    logger.info(f"[OpenCode]   {key}={value}")
        else:
            logger.warning("[OpenCode] No LLM-related environment variables found!")
        
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
            
            # Initialize conversation tracking and streaming log file early (before container log streaming starts)
            if self.debug_conversation_logging:
                self._conversation_start_time = time.time()
                self._conversation_prompt = None  # Will be set later when prompt is available
                self._init_streaming_log_file(job_id)
                logger.info(f"[OpenCode] Job {job_id}: ✅ Streaming log file initialized at {self._log_file_path}. All SSE events and container logs will be written here.")
            else:
                logger.debug(f"[OpenCode] Job {job_id}: Debug conversation logging is disabled. No streaming log file will be created.")
            
            # Start streaming container logs if debug logging enabled
            if self.debug_conversation_logging:
                self._container_log_task = asyncio.create_task(
                    self._stream_container_logs(container_id, job_id, cancellation_event)
                )
            
            # Check cancellation after spawn
            if cancellation_event and cancellation_event.is_set():
                raise asyncio.CancelledError("Job cancelled after container spawn")
            
            # Wait for OpenCode to be ready
            logger.debug(f"[OpenCode] Job {job_id}: Waiting for container to be ready on port {port}...")
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
            error_msg = f"OpenCode execution timeout after {self.job_timeout_seconds}s"
            logger.error(f"[OpenCode] Job {job_id}: Timeout after {execution_time:.1f}s")
            
            # Write timeout error to log file before raising
            if self.debug_conversation_logging:
                self._write_error_to_log(job_id, "TIMEOUT", error_msg, execution_time)
            
            raise OpenCodeTimeoutError(error_msg)
        except asyncio.CancelledError:
            execution_time = time.time() - start_time if start_time else 0
            error_msg = "Job was cancelled"
            logger.warning(f"[OpenCode] Job {job_id}: Cancelled after {execution_time:.1f}s")
            
            # Write cancellation to log file before raising
            if self.debug_conversation_logging:
                self._write_error_to_log(job_id, "CANCELLED", error_msg, execution_time)
            
            raise
        except Exception as e:
            execution_time = time.time() - start_time if start_time else 0
            error_msg = f"Error during execution: {str(e)}"
            logger.error(f"[OpenCode] Job {job_id}: {error_msg} (after {execution_time:.1f}s)")
            
            # Write error to log file before raising
            if self.debug_conversation_logging:
                self._write_error_to_log(job_id, "ERROR", error_msg, execution_time)
            
            raise
            
        finally:
            # CRITICAL: Ensure all logs are written before cleanup
            # This MUST happen even if errors occurred or job was cancelled
            if self.debug_conversation_logging:
                # Stop container log streaming and give it time to write final logs
                if self._container_log_task:
                    logger.info(f"[OpenCode] Job {job_id}: Stopping container log streaming in cleanup")
                    # Give container logs a moment to catch up
                    await asyncio.sleep(1.0)
                    self._container_log_task.cancel()
                    try:
                        await self._container_log_task
                    except asyncio.CancelledError:
                        pass
                    self._container_log_task = None
                    # One more moment for any final writes
                    await asyncio.sleep(0.5)
                
                # Ensure log file handle is open before any final writes
                if not self._log_file_handle and self._log_file_path:
                    logger.warning(f"[OpenCode] Job {job_id}: Log file handle is None in cleanup, attempting to reopen")
                    try:
                        self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                    except Exception as e:
                        logger.error(f"[OpenCode] Job {job_id}: Failed to reopen log file in cleanup: {e}")
                
                # CRITICAL: Always finalize log file, even on errors/cancellations
                # This preserves the log for debugging
                try:
                    self._finalize_streaming_log(job_id)
                    await self._save_conversation_logs(job_id)
                except Exception as finalize_err:
                    logger.error(f"[OpenCode] Job {job_id}: Failed to finalize log file: {finalize_err}")
                    # Don't raise - we want to continue with container cleanup
            
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
                        "enabled": True
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
                "enabled": True
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
                "enabled": bitbucket_mcp_config.get('enabled', True)
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
                    "type": "remote",  # Required discriminator for OpenCode schema
                    "url": mcp_url_config["url"],
                    "enabled": mcp_url_config.get("enabled", True)
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
            "type": "remote",  # Required discriminator for OpenCode schema
            "enabled": atlassian_mcp_config.get('enabled', True),
            "url": atlassian_mcp_url
        }
        
        # OpenCode schema does not support "policy" key - remove it
        # The max_calls_per_run limit is not configurable via opencode.json
        
        # Build opencode.json structure with MCP config
        # Include $schema for OpenCode config validation (optional but recommended)
        opencode_json = {
            "$schema": "https://opencode.ai/config.json",
            "mcp": mcp_dict
        }
        
        # Add model configuration if available
        # Model must be specified in opencode.json for 'serve' command (--model flag is not supported)
        # OpenCode supports two formats:
        # 1. Simple: "model": "provider/model-id" (for basic usage)
        # 2. Advanced: "provider": { "models": { "model-id": { "options": {...} } } } (for model-specific options)
        # We use the advanced format to ensure proper model recognition and allow future customization
        provider = self.llm_config.get('provider')
        model = None
        if provider == 'claude':
            model = self.llm_config.get('anthropic_model')
        elif provider == 'openai':
            model = self.llm_config.get('openai_model')
        elif provider == 'gemini':
            model = self.llm_config.get('google_model')
        elif provider == 'kimi':
            model = self.llm_config.get('moonshot_model')
        
        if provider and model:
            # Map our provider names to OpenCode's expected provider names
            provider_mapping = {
                'claude': 'anthropic',
                'openai': 'openai',
                'gemini': 'google',
                'kimi': 'moonshot'
            }
            opencode_provider = provider_mapping.get(provider, provider)
            
            # Use the advanced provider.models format for better model recognition
            # This format is recommended in OpenCode docs and ensures the model is properly registered
            if 'provider' not in opencode_json:
                opencode_json['provider'] = {}
            if opencode_provider not in opencode_json['provider']:
                opencode_json['provider'][opencode_provider] = {}
            if 'models' not in opencode_json['provider'][opencode_provider]:
                opencode_json['provider'][opencode_provider]['models'] = {}
            
            # Configure the model (with empty options for now - can be extended later)
            opencode_json['provider'][opencode_provider]['models'][model] = {}
            
            # Also set the simple "model" field as fallback/default
            model_arg = f"{opencode_provider}/{model}"
            opencode_json["model"] = model_arg
            
            logger.info(f"[OpenCode] Configuring model using provider.models format: {opencode_provider}/{model}")
            logger.info(f"[OpenCode] Model breakdown - provider: {opencode_provider}, model_id: {model}, full: {model_arg}")
            
            # Log warning if using date-suffixed model that might not be recognized by older OpenCode versions
            if provider == 'claude' and '-' in model and any(char.isdigit() for char in model.split('-')[-1]) and len(model.split('-')[-1]) == 8:
                logger.warning(
                    f"[OpenCode] Using date-suffixed Claude model '{model}'. "
                    f"If you get ProviderModelNotFoundError, try using an alias like 'claude-sonnet-4-5' (without date) "
                    f"or ensure your OpenCode Docker image is up-to-date: docker pull {self.docker_image}"
                )
        else:
            logger.warning(f"[OpenCode] No model specified in LLM config, OpenCode will use its default model")
        
        return opencode_json
    
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
                # Log the full opencode.json content for debugging (especially model config)
                logger.info(f"[OpenCode] Generated opencode.json content: {json.dumps(opencode_json_content, indent=2)}")
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
            logger.info(f"[OpenCode] Generated and mounting opencode.json to /app/opencode.json")
            # Log MCP config (all bitbucket instances use bitbucket-{workspace} format)
            bitbucket_keys = [k for k in opencode_json_content['mcp'].keys() if k.startswith('bitbucket-')]
            if bitbucket_keys:
                bitbucket_info = f"{len(bitbucket_keys)} workspace(s): {', '.join(bitbucket_keys)}"
            else:
                bitbucket_info = "N/A"
            atlassian_info = opencode_json_content['mcp'].get('atlassian', {}).get('url', 'N/A')
            logger.debug(f"[OpenCode] MCP config: Bitbucket={bitbucket_info}, Atlassian={atlassian_info}")

            # Build command - NOTE: opencode serve does NOT accept --model flag
            # Model must be configured in opencode.json instead (handled in _generate_opencode_json)
            command = ["serve", "--hostname", "0.0.0.0", "--port", "4096"]
            logger.info(f"[OpenCode] Using serve command (model configured in opencode.json: {opencode_json_content.get('model', 'default')})")

            # Create and start container
            container_kwargs = {
                "image": self.docker_image,
                "name": container_name,
                "command": command,
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
            
            # Verify environment variables were actually set in the container
            container_actual_env = container.attrs.get('Config', {}).get('Env', [])
            llm_env_vars = {}
            for env_entry in container_actual_env:
                if '=' in env_entry:
                    key, value = env_entry.split('=', 1)
                    # Check for LLM-related variables (ONLY OPENCODE_* variables are set in container)
                    if 'OPENCODE' in key and ('LLM' in key or 'MODEL' in key or 'PROVIDER' in key or 'API_KEY' in key or 'WORKSPACE' in key):
                        llm_env_vars[key] = value
            
            if llm_env_vars:
                logger.info(f"[OpenCode] Verified container environment variables: {list(llm_env_vars.keys())}")
                for key, value in llm_env_vars.items():
                    if 'API_KEY' in key:
                        logger.info(f"[OpenCode]   {key}=*** (masked)")
                    else:
                        logger.info(f"[OpenCode]   {key}={value}")
            else:
                logger.warning(f"[OpenCode] WARNING: No LLM-related environment variables found in container! Container env vars: {[e.split('=', 1)[0] if '=' in e else e for e in container_actual_env[:10]]}")
            
            logger.info(
                f"[OpenCode] Container {container_name} started, "
                f"port 4096 -> {host_port}"
            )

            # Log container diagnostics to streaming log file if debug logging is enabled
            if self.debug_conversation_logging:
                # Extract MCP URLs from the generated opencode.json
                mcp_urls = []
                if 'mcp' in opencode_json_content:
                    for mcp_name, mcp_config_item in opencode_json_content['mcp'].items():
                        if isinstance(mcp_config_item, dict) and 'url' in mcp_config_item:
                            mcp_urls.append(f"{mcp_name}: {mcp_config_item['url']}")

                self._log_container_diagnostics(
                    job_id=job_id,
                    container_id=container.id,
                    container_env=container_env,
                    mcp_urls=mcp_urls,
                    network_name=network_config
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
        attempt = 0
        last_error = None
        last_status_code = None
        last_error_body = None
        
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                attempt += 1
                try:
                    response = await client.get(url, headers=headers, timeout=5.0)
                    if response.status_code == 200:
                        if attempt > 1:
                            logger.info(f"[OpenCode] Container ready after {attempt} attempts")
                        return
                    
                    # Log non-200 status codes
                    last_status_code = response.status_code
                    try:
                        last_error_body = response.text[:500]  # Limit to first 500 chars
                    except Exception:
                        last_error_body = "<unable to read response body>"
                    
                    # Log every 5 attempts to avoid spam, but always log first error
                    if attempt == 1 or attempt % 5 == 0:
                        logger.warning(
                            f"[OpenCode] Health check failed (attempt {attempt}): "
                            f"HTTP {last_status_code} - {last_error_body}"
                        )
                    
                except httpx.ConnectError as e:
                    last_error = f"Connection error: {str(e)}"
                    # Log connection errors every 5 attempts
                    if attempt == 1 or attempt % 5 == 0:
                        logger.debug(
                            f"[OpenCode] Connection error (attempt {attempt}): {last_error}"
                        )
                except httpx.TimeoutException as e:
                    last_error = f"Timeout: {str(e)}"
                    if attempt == 1 or attempt % 5 == 0:
                        logger.debug(
                            f"[OpenCode] Timeout (attempt {attempt}): {last_error}"
                        )
                except Exception as e:
                    last_error = f"Unexpected error: {type(e).__name__}: {str(e)}"
                    if attempt == 1 or attempt % 5 == 0:
                        logger.warning(
                            f"[OpenCode] Unexpected error (attempt {attempt}): {last_error}"
                        )
                
                await asyncio.sleep(interval)
        
        # Build comprehensive error message
        error_details = []
        if last_status_code:
            error_details.append(f"Last HTTP status: {last_status_code}")
        if last_error_body:
            error_details.append(f"Last error body: {last_error_body[:200]}")
        if last_error:
            error_details.append(f"Last connection error: {last_error}")
        
        error_msg = f"OpenCode container not ready after {timeout}s ({attempt} attempts)"
        if error_details:
            error_msg += f". Details: {'; '.join(error_details)}"
        
        logger.error(f"[OpenCode] {error_msg}")
        raise ContainerError(error_msg)
    
    async def _create_session(self, port: int) -> str:
        """Create an OpenCode session and return session ID"""
        url = f"http://localhost:{port}/session"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    json={},
                    timeout=30.0
                )
                
                # Log response details for debugging
                logger.debug(f"[OpenCode] Session creation response: HTTP {response.status_code}")
                
                if response.status_code != 200:
                    error_body = response.text[:500] if response.text else "<empty response>"
                    logger.error(
                        f"[OpenCode] Failed to create session: HTTP {response.status_code} - {error_body}"
                    )
                
                response.raise_for_status()
                content = response.text
                if not content:
                    raise OpenCodeError(f"Empty response from /session endpoint")
                
                try:
                    data = response.json()
                except Exception as e:
                    logger.error(f"[OpenCode] Failed to parse session response as JSON: {e}")
                    logger.error(f"[OpenCode] Response content: {content[:500]}")
                    raise OpenCodeError(f"Invalid JSON response from /session endpoint: {str(e)}")
                
                session_id = data.get("session_id") or data.get("id")
                if not session_id:
                    logger.error(f"[OpenCode] No session_id in response. Full response: {json.dumps(data, indent=2)}")
                    raise OpenCodeError(f"No session_id in response: {data}")
                
                logger.debug(f"[OpenCode] Session created successfully: {session_id}")
                return session_id
                
        except httpx.HTTPStatusError as e:
            error_body = e.response.text[:500] if e.response.text else "<empty response>"
            logger.error(
                f"[OpenCode] HTTP error creating session: {e.response.status_code} - {error_body}"
            )
            raise OpenCodeError(f"Failed to create session: HTTP {e.response.status_code} - {error_body}")
        except httpx.RequestError as e:
            logger.error(f"[OpenCode] Request error creating session: {type(e).__name__}: {str(e)}")
            raise OpenCodeError(f"Failed to create session: {str(e)}")
        except Exception as e:
            logger.error(f"[OpenCode] Unexpected error creating session: {type(e).__name__}: {str(e)}", exc_info=True)
            raise
    
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
        
        logger.info(f"[OpenCode] Job {job_id}: Sending prompt ({len(prompt)} chars) to {url}")
        
        # Initialize conversation logging if debug mode enabled
        if self.debug_conversation_logging:
            self._conversation_logs = []
            # Note: _conversation_start_time and log file are initialized earlier when container starts
            # Update prompt here since we now have it
            self._conversation_prompt = prompt
            # Update log file with prompt (it was initialized earlier with placeholder)
            # CRITICAL: We must NOT overwrite the file in write mode as it will lose events
            # Instead, we'll update the prompt section by reading, modifying, and writing back
            # BUT we need to ensure we don't lose any events that were already written
            if self._log_file_handle:
                try:
                    # Flush any pending writes first
                    self._log_file_handle.flush()
                    
                    # Close the current handle
                    self._log_file_handle.close()
                    self._log_file_handle = None
                    
                    # Read current content (may include events already written)
                    with open(self._log_file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Replace placeholder prompt - be careful to preserve events section
                    # Use the exact placeholder we set in _init_streaming_log_file
                    if "<PROMPT_PLACEHOLDER>" in content:
                        # Replace the placeholder with actual prompt, preserving newlines
                        content = content.replace("<PROMPT_PLACEHOLDER>", prompt)
                        logger.debug(f"[OpenCode] Job {job_id}: Replaced <PROMPT_PLACEHOLDER> with actual prompt")
                    else:
                        # Fallback: try other placeholder formats
                        if "(no prompt recorded - will be updated when prompt is sent)" in content:
                            content = content.replace(
                                "(no prompt recorded - will be updated when prompt is sent)",
                                prompt
                            )
                        elif "(no prompt recorded)" in content:
                            content = content.replace("(no prompt recorded)", prompt)
                        else:
                            logger.warning(f"[OpenCode] Job {job_id}: Could not find prompt placeholder in log file")
                    
                    # Write back the updated content
                    with open(self._log_file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    # Reopen in append mode for future events - CRITICAL: Must happen before logging prompt_sent
                    self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                    # Verify handle is valid by writing a test line
                    try:
                        test_line = f"[{datetime.now(tz=timezone.utc).isoformat()}] [system] Log file reopened after prompt update\n"
                        self._log_file_handle.write(test_line)
                        self._log_file_handle.flush()
                        logger.info(f"[OpenCode] Job {job_id}: ✅ Updated prompt in log file and reopened in append mode (handle verified)")
                    except Exception as verify_err:
                        logger.error(f"[OpenCode] Job {job_id}: CRITICAL: File handle verification failed after reopen: {verify_err}", exc_info=True)
                        # Try to reopen again
                        try:
                            self._log_file_handle.close()
                            self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                            logger.info(f"[OpenCode] Job {job_id}: Reopened file handle again after verification failure")
                        except Exception as retry_err:
                            logger.error(f"[OpenCode] Job {job_id}: CRITICAL: Failed to reopen file handle after verification failure: {retry_err}", exc_info=True)
                except Exception as e:
                    logger.error(f"[OpenCode] Job {job_id}: Failed to update prompt in log file: {e}", exc_info=True)
                    # Try to reopen in append mode even if update failed
                    try:
                        if not self._log_file_handle:
                            self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                            logger.info(f"[OpenCode] Job {job_id}: Reopened log file in append mode after error")
                    except Exception as e2:
                        logger.error(f"[OpenCode] Job {job_id}: Failed to reopen log file: {e2}", exc_info=True)
        
        # Log prompt sending to streaming log - MUST happen AFTER prompt update and file reopen
        if self.debug_conversation_logging:
            prompt_event = {
                "timestamp": time.time(),
                "event_type": "prompt_sent",
                "data": f"Prompt sent to OpenCode ({len(prompt)} characters)"
            }
            self._write_event_to_streaming_log(prompt_event)
            logger.debug(f"[OpenCode] Job {job_id}: Prompt sent event logged to streaming log")
        
        last_error = None
        backoff = SSE_INITIAL_BACKOFF

        # Start message polling task to provide visibility during hangs
        # This polls GET /session/{session_id}/message every 1-2 seconds
        poll_task = None
        if self.debug_conversation_logging:
            poll_task = asyncio.create_task(
                self._poll_messages(port, session_id, job_id, cancellation_event)
            )

        try:
            for attempt in range(SSE_MAX_RETRIES):
                # Check cancellation before each attempt
                if cancellation_event and cancellation_event.is_set():
                    raise asyncio.CancelledError("Job cancelled during SSE streaming")
                
                try:
                    # Log HTTP request details - MUST be logged before making request
                    if self.debug_conversation_logging:
                        try:
                            request_event = {
                                "timestamp": time.time(),
                                "event_type": "http_request",
                                "data": f"POST {url} | Headers: {dict(headers)} | Payload size: {len(json.dumps(payload))} bytes"
                            }
                            self._write_event_to_streaming_log(request_event)
                            logger.info(f"[OpenCode] Job {job_id}: Sending HTTP POST to {url} (attempt {attempt + 1}/{SSE_MAX_RETRIES})")
                        except Exception as e:
                            logger.error(f"[OpenCode] Job {job_id}: Failed to log HTTP request: {e}")
                    
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(self.job_timeout_seconds, connect=30.0)
                    ) as client:
                        # First, make the request and check Content-Type
                        response = await client.post(url, headers=headers, json=payload)
                        content_type = response.headers.get("content-type", "")
                        
                        # Log HTTP response details - MUST be logged immediately after response
                        # CRITICAL: This MUST happen - log to regular logger first, then to file
                        logger.info(f"[OpenCode] Job {job_id}: HTTP Response received - Status: {response.status_code}, Content-Type: {content_type}")
                        
                        # CRITICAL: Verify file handle exists before logging
                        if self.debug_conversation_logging:
                            if not self._log_file_handle:
                                logger.error(f"[OpenCode] Job {job_id}: CRITICAL: File handle is None when trying to log HTTP response! Attempting to reopen...")
                                if self._log_file_path:
                                    try:
                                        self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                                        logger.info(f"[OpenCode] Job {job_id}: Successfully reopened file handle for HTTP response logging")
                                    except Exception as reopen_err:
                                        logger.error(f"[OpenCode] Job {job_id}: CRITICAL: Failed to reopen file handle for HTTP response: {reopen_err}", exc_info=True)
                            
                            try:
                                response_event = {
                                    "timestamp": time.time(),
                                    "event_type": "http_response",
                                    "data": f"Status: {response.status_code} | Content-Type: {content_type} | Headers: {dict(response.headers)}"
                                }
                                self._write_event_to_streaming_log(response_event)
                                logger.info(f"[OpenCode] Job {job_id}: ✅ HTTP response event written to streaming log (handle valid: {self._log_file_handle is not None})")
                            except Exception as e:
                                logger.error(f"[OpenCode] Job {job_id}: CRITICAL: Failed to log HTTP response to streaming log: {e}", exc_info=True)
                                # Try to log the error to the file if possible
                                try:
                                    if self._log_file_handle:
                                        error_time = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                                        self._log_file_handle.write(f"[{error_time}] [system_error] Failed to log HTTP response: {e}\n")
                                        self._log_file_handle.flush()
                                except Exception:
                                    pass
                        
                        # If response is JSON, OpenCode completed synchronously or returned an error
                        if "application/json" in content_type:
                            # Check HTTP status code before parsing
                            if response.status_code != 200:
                                error_msg = f"Non-200 status code ({response.status_code}) with JSON Content-Type"
                                logger.error(f"[OpenCode] Job {job_id}: {error_msg}")
                                raise ContainerError(f"OpenCode returned HTTP {response.status_code}: {response.text[:500] if response.text else '<empty response>'}")
                            
                            # Check if response body is empty before parsing
                            if not response.text or len(response.text.strip()) == 0:
                                error_msg = "Empty response body with JSON Content-Type"
                                logger.error(f"[OpenCode] Job {job_id}: {error_msg}")
                                
                                # Get container status and logs for diagnostics
                                container_status = "unknown"
                                container_error = None
                                container_logs_preview = None
                                try:
                                    if self._current_container:
                                        self._current_container.reload()  # Refresh container state
                                        container_status = self._current_container.status
                                        
                                        # Always get container logs for diagnostics, even if running
                                        try:
                                            logs = self._current_container.logs(tail=100, stderr=True, stdout=True).decode('utf-8', errors='replace')
                                            if logs:
                                                # Extract last few lines for error message
                                                log_lines = logs.strip().split('\n')
                                                last_logs = '\n'.join(log_lines[-20:])  # Last 20 lines for more context
                                                container_logs_preview = last_logs
                                                
                                                # Check for common error patterns in logs
                                                error_indicators = []
                                                specific_error = None
                                                
                                                # Check for ProviderModelNotFoundError (most common issue)
                                                if 'ProviderModelNotFoundError' in logs or 'ModelNotFoundError' in logs:
                                                    # Extract model and provider info from error
                                                    import re
                                                    model_match = re.search(r'modelID[:\s]+"([^"]+)"', logs)
                                                    provider_match = re.search(r'providerID[:\s]+"([^"]+)"', logs)
                                                    if model_match and provider_match:
                                                        model_id = model_match.group(1)
                                                        provider_id = provider_match.group(1)
                                                        specific_error = f"Model '{model_id}' not found for provider '{provider_id}'. Please check your OpenCode LLM configuration (OPENCODE_{provider_id.upper()}_MODEL)."
                                                        error_indicators.append(f"Model not found: {model_id} for provider {provider_id}")
                                                    else:
                                                        error_indicators.append("Model not found error detected in container logs")
                                                
                                                if 'error' in logs.lower() or 'Error' in logs or 'ERROR' in logs:
                                                    if not specific_error:  # Only add generic error if we don't have specific one
                                                        error_indicators.append("Error messages found in container logs")
                                                if 'timeout' in logs.lower() or 'Timeout' in logs:
                                                    error_indicators.append("Timeout detected in container logs")
                                                if 'connection' in logs.lower() and ('refused' in logs.lower() or 'failed' in logs.lower()):
                                                    error_indicators.append("Connection issues detected in container logs")
                                                
                                                if container_status != 'running':
                                                    container_error = f"Container status: {container_status}. Last logs:\n{last_logs}"
                                                else:
                                                    if specific_error:
                                                        # Use specific error message if we found a model not found error
                                                        container_error = f"Container is running (status: {container_status}) but returned empty response. {specific_error}"
                                                        # Still include logs for full context
                                                        container_error += f"\n\nContainer logs (last 20 lines):\n{last_logs}"
                                                    else:
                                                        error_info = ". ".join(error_indicators) if error_indicators else "No obvious errors in recent logs"
                                                        container_error = f"Container is running (status: {container_status}) but returned empty response. {error_info}. Last logs:\n{last_logs}"
                                            else:
                                                container_error = f"Container status: {container_status}. No logs available."
                                        except Exception as log_err:
                                            container_error = f"Container status: {container_status}. Failed to get logs: {log_err}"
                                    else:
                                        container_error = "Container reference not available"
                                except Exception as e:
                                    container_error = f"Failed to check container status: {e}"
                                
                                # Build comprehensive error message
                                full_error_msg = "OpenCode returned empty response body with Content-Type: application/json"
                                if container_error:
                                    full_error_msg += f". {container_error}"
                                else:
                                    full_error_msg += ". Container diagnostics unavailable."
                                
                                # Log the full error with container logs for debugging
                                logger.error(f"[OpenCode] Job {job_id}: {full_error_msg}")
                                if container_logs_preview:
                                    logger.error(f"[OpenCode] Job {job_id}: Container logs (last 20 lines):\n{container_logs_preview}")
                                
                                raise ContainerError(full_error_msg)
                            
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
                                        # OpenCode uses OPENCODE_*_API_KEY environment variables ONLY
                                        opencode_env_var_map = {
                                            'openai': 'OPENCODE_OPENAI_API_KEY',
                                            'claude': 'OPENCODE_ANTHROPIC_API_KEY',
                                            'gemini': 'OPENCODE_GOOGLE_API_KEY',
                                            'kimi': 'OPENCODE_MOONSHOT_API_KEY',
                                        }
                                        opencode_env_var = opencode_env_var_map.get(provider, '')
                                        required_key = opencode_env_var  # Use OPENCODE_* key directly
                                        
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
                                
                                # Wait a moment for container logs to catch up before finalizing
                                if self.debug_conversation_logging:
                                    # Give container log streaming a chance to write any pending logs
                                    await asyncio.sleep(2.0)
                                
                                # For non-streaming responses, record the JSON response as an event
                                if self.debug_conversation_logging:
                                    # Log JSON response received
                                    event_record = {
                                        "timestamp": time.time(),
                                        "event_type": "json_response",
                                        "data": json.dumps(data),
                                        "raw_event": data
                                    }
                                    self._conversation_logs.append(event_record)
                                    # Write event to streaming log
                                    self._write_event_to_streaming_log(event_record)
                                    
                                    # Log that we're about to finalize
                                    finalize_event = {
                                        "timestamp": time.time(),
                                        "event_type": "finalizing",
                                        "data": "Finalizing streaming log - JSON response received, no SSE streaming"
                                    }
                                    self._write_event_to_streaming_log(finalize_event)
                                    
                                    # Stop container log streaming before finalizing - give it time to write
                                    if self._container_log_task:
                                        logger.info(f"[OpenCode] Job {job_id}: Stopping container log streaming before finalizing log")
                                        # Give container logs a moment to catch up
                                        await asyncio.sleep(2.0)
                                        self._container_log_task.cancel()
                                        try:
                                            await self._container_log_task
                                        except asyncio.CancelledError:
                                            pass
                                        self._container_log_task = None
                                        # One more moment for any final writes
                                        await asyncio.sleep(0.5)
                                    
                                    # Verify log file handle is still valid before finalizing
                                    if not self._log_file_handle:
                                        logger.warning(f"[OpenCode] Job {job_id}: Log file handle is None before finalizing, attempting to reopen")
                                        try:
                                            self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                                        except Exception as e:
                                            logger.error(f"[OpenCode] Job {job_id}: Failed to reopen log file for finalization: {e}")
                                    
                                    self._finalize_streaming_log(job_id)
                                    await self._save_conversation_logs(job_id)
                                return
                            except json.JSONDecodeError as e:
                                error_msg = f"Invalid JSON in response: {e}"
                                logger.warning(f"[OpenCode] Job {job_id}: {error_msg}")
                                logger.warning(f"[OpenCode] Job {job_id}: Response text: {response.text[:500]}")
                                # Log JSON decode error to streaming log if enabled
                                if self.debug_conversation_logging:
                                    try:
                                        error_event = {
                                            "timestamp": time.time(),
                                            "event_type": "json_decode_error",
                                            "data": f"{error_msg} | Response preview: {response.text[:200]}"
                                        }
                                        self._write_event_to_streaming_log(error_event)
                                    except Exception:
                                        pass  # Don't fail on logging errors
                                raise ContainerError("Invalid JSON response from OpenCode")
                        
                        # For SSE responses, use httpx-sse
                        if "text/event-stream" not in content_type:
                            error_msg = f"Unexpected Content-Type: {content_type}"
                            # Log unexpected content type to streaming log if enabled
                            if self.debug_conversation_logging:
                                try:
                                    error_event = {
                                        "timestamp": time.time(),
                                        "event_type": "unexpected_content_type",
                                        "data": error_msg
                                    }
                                    self._write_event_to_streaming_log(error_event)
                                except Exception:
                                    pass  # Don't fail on logging errors
                            raise SSEError(error_msg)
                        
                        # Log that we're establishing SSE connection
                        logger.info(f"[OpenCode] Job {job_id}: Establishing SSE connection for streaming")
                        if self.debug_conversation_logging:
                            # Log connection start to streaming log
                            connection_event = {
                                "timestamp": time.time(),
                                "event_type": "connection_start",
                                "data": "Establishing SSE connection"
                            }
                            self._write_event_to_streaming_log(connection_event)
                        
                        # Re-make request for SSE streaming
                        async with aconnect_sse(
                            client,
                            "POST",
                            url,
                            headers=headers,
                            json=payload
                        ) as event_source:
                            logger.info(f"[OpenCode] Job {job_id}: SSE connection established, waiting for events")
                            if self.debug_conversation_logging:
                                # Log connection established
                                connection_event = {
                                    "timestamp": time.time(),
                                    "event_type": "connection_established",
                                    "data": "SSE connection established, waiting for events"
                                }
                                self._write_event_to_streaming_log(connection_event)
                            
                            event_count = 0
                            first_event_time = None
                            connection_established_time = time.time()
                            last_warning_time = connection_established_time
                            warning_interval = 30.0  # Warn every 30 seconds if no events
                            last_event_time = connection_established_time
                            
                            # Set up a watchdog task to log if no events arrive
                            async def event_watchdog():
                                while True:
                                    await asyncio.sleep(10)  # Check every 10 seconds
                                    elapsed = time.time() - last_event_time
                                    if elapsed > 30 and event_count == 0:
                                        logger.warning(f"[OpenCode] Job {job_id}: No SSE events received for {int(elapsed)}s after connection. OpenCode may be stuck.")
                                        if self.debug_conversation_logging:
                                            watchdog_event = {
                                                "timestamp": time.time(),
                                                "event_type": "watchdog",
                                                "data": f"No events for {int(elapsed)}s after connection. OpenCode may be stuck (waiting for MCP, LLM, or processing)."
                                            }
                                            self._write_event_to_streaming_log(watchdog_event)
                                    elif elapsed > 60 and event_count > 0:
                                        logger.warning(f"[OpenCode] Job {job_id}: No new SSE events for {int(elapsed)}s (last event was {event_count} events ago).")
                                        if self.debug_conversation_logging:
                                            watchdog_event = {
                                                "timestamp": time.time(),
                                                "event_type": "watchdog",
                                                "data": f"No new events for {int(elapsed)}s. Last event was #{event_count}."
                                            }
                                            self._write_event_to_streaming_log(watchdog_event)
                            
                            watchdog_task = asyncio.create_task(event_watchdog())
                            
                            try:
                                async for event in event_source.aiter_sse():
                                    # CRITICAL: Every event MUST be logged - no exceptions
                                    # Update last event time immediately
                                    last_event_time = time.time()
                                    
                                    # Track first event timing
                                    if event_count == 0:
                                        first_event_time = time.time()
                                        time_to_first_event = first_event_time - connection_established_time
                                        logger.info(f"[OpenCode] Job {job_id}: First SSE event received after {time_to_first_event:.1f}s")
                                        # CRITICAL: Log first event to regular logger AND streaming log
                                        if self.debug_conversation_logging:
                                            try:
                                                first_event_log = {
                                                    "timestamp": first_event_time,
                                                    "event_type": "first_event",
                                                    "data": f"First SSE event received after {time_to_first_event:.1f}s (event: {event.event or 'message'}, data length: {len(event.data or '')})"
                                                }
                                                self._write_event_to_streaming_log(first_event_log)
                                                logger.debug(f"[OpenCode] Job {job_id}: First event logged to streaming log")
                                            except Exception as e:
                                                logger.error(f"[OpenCode] Job {job_id}: CRITICAL: Failed to log first event: {e}", exc_info=True)
                                    
                                    event_count += 1
                                    
                                    # CRITICAL: Log every event count to verify logging is working
                                    if event_count <= 5 or event_count % 10 == 0:
                                        logger.debug(f"[OpenCode] Job {job_id}: Processing SSE event #{event_count} (type: {event.event or 'message'})")
                                    
                                    # Log event count periodically for verification
                                    if event_count % 10 == 0:
                                        logger.debug(f"[OpenCode] Job {job_id}: Processed {event_count} SSE events so far")
                                        if self.debug_conversation_logging:
                                            count_event = {
                                                "timestamp": time.time(),
                                                "event_type": "event_count",
                                                "data": f"Processed {event_count} SSE events so far"
                                            }
                                            self._write_event_to_streaming_log(count_event)
                                    
                                    # Check cancellation periodically during streaming
                                    if cancellation_event and cancellation_event.is_set():
                                        logger.info(f"[OpenCode] Job {job_id}: Cancellation requested during streaming")
                                        # Log cancellation event before raising
                                        if self.debug_conversation_logging:
                                            cancel_event = {
                                                "timestamp": time.time(),
                                                "event_type": "cancellation",
                                                "data": "Job cancellation requested during SSE streaming"
                                            }
                                            self._write_event_to_streaming_log(cancel_event)
                                        raise asyncio.CancelledError("Job cancelled during SSE streaming")
                                    
                                    # Process the event - this MUST log the event
                                    # CRITICAL: Log to regular logger first to ensure visibility
                                    event_type = event.event or "message"
                                    event_data_preview = (event.data or "")[:100] if event.data else ""
                                    logger.debug(f"[OpenCode] Job {job_id}: Processing SSE event #{event_count} - type: {event_type}, data preview: {event_data_preview}...")
                                    
                                    try:
                                        self._process_sse_event_obj(event, job_id)
                                        # Verify event was logged
                                        if self.debug_conversation_logging and event_count <= 5:
                                            logger.debug(f"[OpenCode] Job {job_id}: Event #{event_count} processed and logged to streaming log")
                                    except Exception as e:
                                        # If event processing fails, log it but continue
                                        logger.error(f"[OpenCode] Job {job_id}: CRITICAL: Error processing SSE event #{event_count}: {e}", exc_info=True)
                                        if self.debug_conversation_logging:
                                            try:
                                                error_event = {
                                                    "timestamp": time.time(),
                                                    "event_type": "processing_error",
                                                    "data": f"Error processing SSE event #{event_count}: {e}"
                                                }
                                                self._write_event_to_streaming_log(error_event)
                                            except Exception as log_err:
                                                logger.error(f"[OpenCode] Job {job_id}: Failed to log processing error: {log_err}")
                                    
                                    # Check for done event
                                    if event.event == "done":
                                        logger.info(f"[OpenCode] Job {job_id}: Prompt streaming completed (received {event_count} events)")
                                        # Ensure done event is logged before breaking
                                        if self.debug_conversation_logging:
                                            done_event = {
                                                "timestamp": time.time(),
                                                "event_type": "done",
                                                "data": f"SSE streaming completed successfully (received {event_count} total events)"
                                            }
                                            self._write_event_to_streaming_log(done_event)
                                        break
                            except Exception as e:
                                # Log any exception during event processing
                                logger.error(f"[OpenCode] Job {job_id}: Exception during SSE event loop: {e}")
                                if self.debug_conversation_logging:
                                    exception_event = {
                                        "timestamp": time.time(),
                                        "event_type": "exception",
                                        "data": f"Exception during SSE event loop: {e}"
                                    }
                                    self._write_event_to_streaming_log(exception_event)
                                raise
                            finally:
                                # Cancel watchdog when done
                                watchdog_task.cancel()
                                try:
                                    await watchdog_task
                                except asyncio.CancelledError:
                                    pass
                                
                                # Log final event count for verification
                                logger.info(f"[OpenCode] Job {job_id}: SSE event loop ended. Total events processed: {event_count}")
                                if self.debug_conversation_logging:
                                    final_count_event = {
                                        "timestamp": time.time(),
                                        "event_type": "event_loop_end",
                                        "data": f"SSE event loop ended. Total events processed: {event_count}"
                                    }
                                    self._write_event_to_streaming_log(final_count_event)
                            
                            # If we exit the loop without 'done' event
                            if event_count == 0:
                                elapsed = time.time() - connection_established_time
                                logger.error(
                                    f"[OpenCode] Job {job_id}: SSE connection established but NO events received "
                                    f"after {elapsed:.1f}s. OpenCode may be stuck waiting for MCP servers, LLM, or other resources."
                                )
                                if self.debug_conversation_logging:
                                    no_events_event = {
                                        "timestamp": time.time(),
                                        "event_type": "error",
                                        "data": f"SSE connection established but no events received after {elapsed:.1f}s - OpenCode may be stuck"
                                    }
                                    self._write_event_to_streaming_log(no_events_event)
                            else:
                                logger.info(f"[OpenCode] Job {job_id}: SSE streaming ended (received {event_count} events, no 'done' event)")
                        
                        # If we get here without 'done', streaming completed normally
                        logger.info(f"[OpenCode] Job {job_id}: Prompt streaming completed")
                        return
                
                except asyncio.CancelledError:
                    raise  # Re-raise cancellation errors
                    
                except SSEError as e:
                    last_error = e
                    error_msg = f"SSE error on attempt {attempt + 1}/{SSE_MAX_RETRIES}: {e}"
                    logger.warning(f"[OpenCode] Job {job_id}: {error_msg}")
                    # Log to streaming log if enabled
                    if self.debug_conversation_logging:
                        try:
                            error_event = {
                                "timestamp": time.time(),
                                "event_type": "sse_error",
                                "data": error_msg
                            }
                            self._write_event_to_streaming_log(error_event)
                        except Exception:
                            pass  # Don't fail on logging errors
                    
                except httpx.ConnectError as e:
                    last_error = e
                    error_msg = f"Connection error on attempt {attempt + 1}/{SSE_MAX_RETRIES}: {e}"
                    logger.warning(f"[OpenCode] Job {job_id}: {error_msg}")
                    # Log to streaming log if enabled
                    if self.debug_conversation_logging:
                        try:
                            error_event = {
                                "timestamp": time.time(),
                                "event_type": "connection_error",
                                "data": error_msg
                            }
                            self._write_event_to_streaming_log(error_event)
                        except Exception:
                            pass  # Don't fail on logging errors
                    
                except httpx.ReadError as e:
                    last_error = e
                    error_msg = f"Read error on attempt {attempt + 1}/{SSE_MAX_RETRIES}: {e}"
                    logger.warning(f"[OpenCode] Job {job_id}: {error_msg}")
                    # Log to streaming log if enabled
                    if self.debug_conversation_logging:
                        try:
                            error_event = {
                                "timestamp": time.time(),
                                "event_type": "read_error",
                                "data": error_msg
                            }
                            self._write_event_to_streaming_log(error_event)
                        except Exception:
                            pass  # Don't fail on logging errors
                    
                except Exception as e:
                    # Catch-all for any other exceptions during request/response
                    last_error = e
                    error_msg = f"Unexpected error on attempt {attempt + 1}/{SSE_MAX_RETRIES}: {e}"
                    logger.error(f"[OpenCode] Job {job_id}: {error_msg}", exc_info=True)
                    # Log to streaming log if enabled
                    if self.debug_conversation_logging:
                        try:
                            error_event = {
                                "timestamp": time.time(),
                                "event_type": "unexpected_error",
                                "data": f"{error_msg} | Type: {type(e).__name__}"
                            }
                            self._write_event_to_streaming_log(error_event)
                        except Exception:
                            pass  # Don't fail on logging errors
                # Exponential backoff before retry
                if attempt < SSE_MAX_RETRIES - 1:
                    logger.info(f"[OpenCode] Job {job_id}: Retrying in {backoff:.1f}s...")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * SSE_BACKOFF_MULTIPLIER, SSE_MAX_BACKOFF)
            else:
                # All retries exhausted
                error_msg = f"SSE streaming failed after {SSE_MAX_RETRIES} attempts: {last_error}"
                # Log final failure to streaming log if enabled
                if self.debug_conversation_logging:
                    try:
                        failure_event = {
                            "timestamp": time.time(),
                            "event_type": "streaming_failed",
                            "data": error_msg
                        }
                        self._write_event_to_streaming_log(failure_event)
                    except Exception:
                        pass  # Don't fail on logging errors
                # Write error to log before raising
                if self.debug_conversation_logging:
                    self._write_error_to_log(job_id, "STREAMING_ERROR", error_msg, 0)
                raise ContainerError(error_msg)
        except asyncio.CancelledError:
            # Job was cancelled - write to log before finalizing
            if self.debug_conversation_logging:
                self._write_error_to_log(job_id, "CANCELLED", "Job was cancelled during SSE streaming", 0)
            raise
        except Exception as e:
            # Any other error - write to log before finalizing
            error_msg = f"Unexpected error during streaming: {type(e).__name__}: {str(e)}"
            if self.debug_conversation_logging:
                self._write_error_to_log(job_id, "ERROR", error_msg, 0)
            raise
        finally:
            # Stop message polling task
            if poll_task:
                poll_task.cancel()
                try:
                    await poll_task
                except asyncio.CancelledError:
                    pass
                logger.debug(f"[OpenCode] Job {job_id}: Message polling task stopped")
                # Clean up tracking for this session
                if session_id in self._last_polled_message_length:
                    del self._last_polled_message_length[session_id]
                if session_id in self._last_polled_message_id:
                    del self._last_polled_message_id[session_id]
                # Clean up parts count tracking
                if hasattr(self, '_last_message_parts_count') and session_id in self._last_message_parts_count:
                    del self._last_message_parts_count[session_id]

            # Finalize streaming log and save JSON log
            # CRITICAL: This MUST happen even if errors occurred or job was cancelled
            # The log file is NEVER deleted - it's preserved for debugging
            if self.debug_conversation_logging:
                try:
                    # Ensure log file handle is open before finalizing
                    if not self._log_file_handle and self._log_file_path:
                        logger.warning(f"[OpenCode] Job {job_id}: Log file handle is None in finally block, attempting to reopen")
                        try:
                            self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                        except Exception as e:
                            logger.error(f"[OpenCode] Job {job_id}: Failed to reopen log file in finally block: {e}")

                    # Stop container log streaming before finalizing
                    if self._container_log_task:
                        logger.info(f"[OpenCode] Job {job_id}: Stopping container log streaming in finally block")
                        self._container_log_task.cancel()
                        try:
                            await self._container_log_task
                        except asyncio.CancelledError:
                            pass
                        self._container_log_task = None
                        # Give it a moment to write final logs
                        await asyncio.sleep(0.5)
                    
                    # CRITICAL: Always finalize log file, even on errors/cancellations
                    # This preserves the log for debugging - the file is NEVER deleted
                    self._finalize_streaming_log(job_id)
                    await self._save_conversation_logs(job_id)
                except Exception as e:
                    # Even if finalization fails, log it but preserve the file
                    logger.error(f"[OpenCode] Job {job_id}: Error during log finalization (log file preserved): {e}")
    
    def _process_sse_event_obj(self, event, job_id: str):
        """Process an SSE event object from httpx-sse"""
        event_type = event.event or "message"
        data = event.data or ""
        timestamp = time.time()

        # ALWAYS log to regular logger first (even if debug logging is disabled)
        # Use INFO level to ensure SSE events are visible in logs
        logger.info(f"[OpenCode] Job {job_id} SSE event received: type={event_type}, data_len={len(data)}")

        if event_type == "error":
            logger.error(f"[OpenCode] Job {job_id} SSE error: {data}")
        elif event_type == "done":
            logger.info(f"[OpenCode] Job {job_id} SSE done event received")
        else:
            # Log truncated data for debugging
            if len(data) > 100:
                logger.debug(f"[OpenCode] Job {job_id} SSE {event_type}: {data[:100]}...")
            else:
                logger.debug(f"[OpenCode] Job {job_id} SSE {event_type}: {data}")
        
        # Capture full event for debug logging if enabled
        # This MUST happen after regular logging to ensure events are never lost
        if self.debug_conversation_logging:
            try:
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
                # Write event to streaming log immediately - MUST NOT fail silently
                self._write_event_to_streaming_log(event_record)
            except Exception as e:
                # If logging fails, log the error but don't crash
                logger.error(f"[OpenCode] Job {job_id}: Failed to log SSE event to streaming log: {e}")
                logger.error(f"[OpenCode] Job {job_id}: Event that failed to log - type: {event_type}, data length: {len(data)}")
    
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
    
    def _init_streaming_log_file(self, job_id: str):
        """
        Initialize streaming log file for real-time event logging.
        
        Args:
            job_id: Job identifier for file naming
        """
        if not self.debug_conversation_logging or not self._conversation_start_time:
            return
        
        # Create log directory if it doesn't exist
        log_dir = Path(self.conversation_log_dir)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[OpenCode] Job {job_id}: Failed to create log directory {log_dir}: {e}")
            return
        
        # Open streaming log file
        self._log_file_path = log_dir / f"{job_id}.log"
        try:
            self._log_file_handle = open(self._log_file_path, 'w', encoding='utf-8')
            
            # Write header (end time will be updated later)
            start_time_str = datetime.fromtimestamp(self._conversation_start_time, tz=timezone.utc).isoformat()
            # Write header - use a format that allows easy replacement later
            header_lines = [
                f"OpenCode Conversation Log - Job: {job_id}\n",
                f"Started: {start_time_str}\n",
                f"Ended: <streaming in progress>\n",
                f"Duration: <streaming in progress>\n",
                f"\n{'='*80}\n",
                "PROMPT\n",
                f"{'='*80}\n",
                f"{self._conversation_prompt or '<PROMPT_PLACEHOLDER>'}\n",
                f"\n{'='*80}\n",
                "EVENTS\n",
                f"{'='*80}\n"
            ]
            for line in header_lines:
                self._log_file_handle.write(line)
            self._log_file_handle.flush()
            logger.info(f"[OpenCode] Job {job_id}: ✅ Log file header written (prompt placeholder: {'<PROMPT_PLACEHOLDER>' if not self._conversation_prompt else 'actual prompt'})")  # Ensure header is written immediately
            
            logger.debug(f"[OpenCode] Job {job_id}: Initialized streaming log file: {self._log_file_path}")
        except Exception as e:
            logger.error(f"[OpenCode] Job {job_id}: Failed to initialize streaming log file: {e}")
            self._log_file_handle = None
            self._log_file_path = None

    def _log_container_diagnostics(self, job_id: str, container_id: str, container_env: Dict[str, str],
                                    mcp_urls: List[str] = None, network_name: str = None):
        """
        Write container diagnostics to the streaming log file.

        This provides visibility into the container configuration for debugging hangs.

        Args:
            job_id: Job identifier
            container_id: Docker container ID
            container_env: Environment variables passed to container (will be redacted)
            mcp_urls: List of MCP server URLs
            network_name: Docker network name
        """
        if not self._log_file_handle:
            return

        try:
            # Redact sensitive values (API keys)
            redacted_env = {}
            for key, value in container_env.items():
                if 'API_KEY' in key or 'TOKEN' in key or 'SECRET' in key or 'PASSWORD' in key:
                    redacted_env[key] = f"***{value[-4:]}" if value and len(value) > 4 else "***"
                elif 'MODEL' in key or 'PROVIDER' in key or 'WORKSPACE' in key or 'DEBUG' in key or 'LOG' in key:
                    redacted_env[key] = value
                # Skip other env vars to keep log clean

            diagnostics_lines = [
                f"\n{'='*80}\n",
                "CONTAINER DIAGNOSTICS\n",
                f"{'='*80}\n",
                f"Container ID: {container_id[:12]}...\n",
                f"Docker Image: {self.docker_image}\n",
                f"Network: {network_name or 'none'}\n",
                f"Job Timeout: {self.job_timeout_seconds}s\n",
            ]

            # Add MCP server URLs if configured
            if mcp_urls:
                diagnostics_lines.append(f"MCP Servers: {', '.join(mcp_urls)}\n")
            else:
                diagnostics_lines.append("MCP Servers: none configured\n")

            # Add key environment variables (redacted)
            diagnostics_lines.append("\nKey Environment Variables:\n")
            for key, value in sorted(redacted_env.items()):
                diagnostics_lines.append(f"  {key}: {value}\n")

            diagnostics_lines.append(f"\n{'='*80}\n\n")

            for line in diagnostics_lines:
                self._log_file_handle.write(line)
            self._log_file_handle.flush()

            logger.info(f"[OpenCode] Job {job_id}: Container diagnostics written to log file")
        except Exception as e:
            logger.error(f"[OpenCode] Job {job_id}: Failed to write container diagnostics: {e}")

    def _write_event_to_streaming_log(self, event_record: Dict[str, Any]):
        """
        Write a single event to the streaming log file.
        
        This function MUST be called for every event when debug_conversation_logging is enabled.
        It handles errors gracefully but logs them to ensure visibility.
        
        CRITICAL: This function will attempt to reopen the log file if the handle is None,
        ensuring events are never lost when debug_conversation_logging is True.
        
        Args:
            event_record: Event record dict with timestamp, event_type, data
        """
        # CRITICAL: Always log to regular logger first for visibility
        event_type = event_record.get('event_type', 'unknown')
        event_data_preview = str(event_record.get('data', ''))[:100]
        logger.debug(f"[OpenCode] _write_event_to_streaming_log called - type: {event_type}, handle exists: {self._log_file_handle is not None}, debug_logging: {self.debug_conversation_logging}")
        
        # If handle is None but debug logging is enabled, try to reopen the file
        if not self._log_file_handle:
            if self.debug_conversation_logging and self._log_file_path:
                try:
                    logger.warning(f"[OpenCode] Log file handle is None, attempting to reopen: {self._log_file_path}")
                    self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                    logger.info(f"[OpenCode] Successfully reopened log file handle")
                except Exception as e:
                    logger.error(f"[OpenCode] CRITICAL: Failed to reopen log file: {e}", exc_info=True)
                    # Still log to regular logger so event is not completely lost
                    event_type = event_record.get('event_type', 'unknown')
                    event_data = str(event_record.get('data', ''))[:200]  # Truncate for logger
                    logger.error(f"[OpenCode] LOST EVENT - type: {event_type}, data: {event_data}...")
                    return
            else:
                # Log warning if file handle is missing but we're trying to log
                logger.warning(f"[OpenCode] Cannot write event to streaming log: file handle is None, debug_logging={self.debug_conversation_logging}, path={self._log_file_path}. Event type: {event_record.get('event_type', 'unknown')}")
                return
        
        try:
            event_time = datetime.fromtimestamp(event_record['timestamp'], tz=timezone.utc)
            event_time_str = event_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            event_type = event_record.get('event_type', 'unknown')
            event_data = event_record.get('data', '')
            
            # Truncate very long data to prevent log file bloat, but log that it was truncated
            max_data_length = 10000  # 10KB per event max
            if len(event_data) > max_data_length:
                truncated_data = event_data[:max_data_length] + f"... [TRUNCATED: {len(event_data)} chars total]"
                logger.debug(f"[OpenCode] Event data truncated from {len(event_data)} to {max_data_length} chars")
            else:
                truncated_data = event_data
            
            # Format: [timestamp] [event_type] data
            # Special handling for container logs and polled_message to maintain readability
            try:
                if event_type == 'container':
                    # Container logs already have their own timestamp format, use it as-is
                    log_line = f"[{event_time_str}] [container] {truncated_data}\n"
                    self._log_file_handle.write(log_line)
                elif event_type == 'polled_message':
                    # Polled messages are formatted multiline - write with proper indentation
                    # First line has timestamp, subsequent lines are indented for readability
                    lines = truncated_data.split('\n')
                    if lines:
                        # Write first line with timestamp
                        self._log_file_handle.write(f"[{event_time_str}] [{event_type}] {lines[0]}\n")
                        # Write remaining lines with fixed indentation (aligns with content after timestamp)
                        indent = " " * 45  # Fixed indent to align with message content
                        for line in lines[1:]:
                            if line.strip():  # Skip empty lines
                                self._log_file_handle.write(f"{indent}{line}\n")
                            else:
                                self._log_file_handle.write("\n")  # Preserve empty lines
                else:
                    log_line = f"[{event_time_str}] [{event_type}] {truncated_data}\n"
                    self._log_file_handle.write(log_line)
                
                # CRITICAL: Flush immediately for real-time viewing
                self._log_file_handle.flush()
                
                # Verify write succeeded by checking file position (if possible)
                # This is a sanity check to catch silent failures
                try:
                    current_pos = self._log_file_handle.tell()
                    if current_pos == 0 and len(truncated_data) > 0:
                        logger.warning(f"[OpenCode] Suspicious: file position is 0 after writing event. Event may not have been written.")
                    else:
                        # Log success for first few events to verify logging works
                        if event_type in ['http_response', 'first_event', 'connection_established']:
                            logger.debug(f"[OpenCode] Event '{event_type}' written to log file at position {current_pos}")
                except (AttributeError, OSError):
                    # Some file handles don't support tell(), that's okay
                    pass
            except Exception as write_err:
                logger.error(f"[OpenCode] CRITICAL: Failed to write/flush event to file: {write_err}", exc_info=True)
                raise  # Re-raise to be caught by outer exception handler
                
        except Exception as e:
            # Log error with full context - this is critical for debugging
            logger.error(f"[OpenCode] CRITICAL: Failed to write event to streaming log: {e}")
            logger.error(f"[OpenCode] Event that failed: type={event_record.get('event_type', 'unknown')}, "
                        f"data_length={len(str(event_record.get('data', '')))}, "
                        f"timestamp={event_record.get('timestamp', 'unknown')}")
            # Try to log the error to the file handle if it's still valid
            try:
                if self._log_file_handle:
                    error_time = datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    self._log_file_handle.write(f"[{error_time}] [system_error] Failed to write event: {e}\n")
                    self._log_file_handle.flush()
            except Exception:
                # If even error logging fails, give up
                pass
    
    def _finalize_streaming_log(self, job_id: str):
        """
        Finalize streaming log file by updating header with end time.
        
        This method preserves the log file even on errors/cancellations.
        It only updates the header, never deletes the file.
        
        Args:
            job_id: Job identifier
        """
        # If no start time, we can't finalize (but file may still exist with partial logs)
        if not self._conversation_start_time:
            # Still try to close handle if open
            if self._log_file_handle:
                try:
                    self._log_file_handle.close()
                except Exception:
                    pass
                self._log_file_handle = None
            return
        
        # If no file path, nothing to finalize
        if not self._log_file_path:
            return
        
        try:
            end_time = time.time()
            duration = end_time - self._conversation_start_time
            end_time_str = datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat()
            
            # Close file handle if open (but preserve the file)
            if self._log_file_handle:
                try:
                    self._log_file_handle.close()
                except Exception as e:
                    logger.warning(f"[OpenCode] Job {job_id}: Error closing log file handle: {e}")
                self._log_file_handle = None
            
            # Read file, update header, write back
            # CRITICAL: Use 'r+' mode to preserve file if read fails
            try:
                with open(self._log_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Replace placeholder header lines
                content = content.replace(
                    "Ended: <streaming in progress>\n",
                    f"Ended: {end_time_str}\n"
                )
                content = content.replace(
                    "Duration: <streaming in progress>\n",
                    f"Duration: {duration:.3f}s\n"
                )
                
                # Write updated content (preserves all existing log data)
                with open(self._log_file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                logger.debug(f"[OpenCode] Job {job_id}: Finalized streaming log file")
            except FileNotFoundError:
                # File doesn't exist - that's okay, might have been created but not written to yet
                logger.debug(f"[OpenCode] Job {job_id}: Log file not found for finalization (may not have been created)")
            except Exception as e:
                # If we can't read/update the file, log it but don't delete the file
                logger.warning(f"[OpenCode] Job {job_id}: Failed to update log file header (file preserved): {e}")
        except Exception as e:
            # Even if finalization fails completely, preserve the log file
            logger.warning(f"[OpenCode] Job {job_id}: Failed to finalize streaming log (file preserved): {e}")
        finally:
            # Ensure file handle is closed (but file itself is never deleted)
            if self._log_file_handle:
                try:
                    self._log_file_handle.close()
                except Exception:
                    pass
                self._log_file_handle = None

    async def _poll_messages(
        self,
        port: int,
        session_id: str,
        job_id: str,
        cancellation_event: Optional[asyncio.Event] = None
    ):
        """
        Poll the message endpoint to see what OpenCode is doing.

        Runs as background task, polling GET /session/{session_id}/message
        every 1-2 seconds and logging responses to provide visibility during hangs.

        Args:
            port: OpenCode server port
            session_id: Session identifier
            job_id: Job identifier for logging
            cancellation_event: Optional event to signal cancellation
        """
        url = f"http://localhost:{port}/session/{session_id}/message"
        poll_interval = 1.5  # seconds

        logger.info(f"[OpenCode] Job {job_id}: Starting message polling task (GET {url} every {poll_interval}s)")

        poll_count = 0
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                if cancellation_event and cancellation_event.is_set():
                    logger.info(f"[OpenCode] Job {job_id}: Message polling cancelled after {poll_count} polls")
                    break

                poll_count += 1
                try:
                    response = await client.get(url)
                    status = response.status_code

                    if status == 200:
                        data = response.text
                        if data and data.strip():
                            try:
                                # Parse JSON response (array of message objects)
                                messages = json.loads(data)
                                if not isinstance(messages, list):
                                    messages = [messages]
                                
                                # Get last seen message ID for this session
                                last_message_id = self._last_polled_message_id.get(session_id)
                                
                                # Find the latest message by timestamp (defensive: don't assume array order)
                                # Messages are typically ordered oldest to newest, but we verify by timestamp
                                latest_message = None
                                latest_timestamp = 0
                                for msg in messages:
                                    msg_timestamp = msg.get('info', {}).get('time', {}).get('created', 0)
                                    if msg_timestamp > latest_timestamp:
                                        latest_timestamp = msg_timestamp
                                        latest_message = msg
                                
                                # Fallback: if no timestamp found, use last message in array
                                if not latest_message and messages:
                                    latest_message = messages[-1]
                                
                                if not latest_message:
                                    continue
                                
                                latest_message_id = latest_message.get('info', {}).get('id')
                                
                                # Check if this is a new message or an update to an existing one
                                parts = latest_message.get('parts', [])
                                parts_count = len(parts)
                                
                                # Only log if:
                                # 1. This is a new message (different ID), OR
                                # 2. This is the same message but now has parts (was empty before)
                                is_new_message = latest_message_id and latest_message_id != last_message_id
                                has_parts_now = parts_count > 0
                                
                                # Track message parts count to detect when parts are added
                                last_parts_count = getattr(self, '_last_message_parts_count', {}).get(session_id, {}).get(latest_message_id, 0)
                                
                                # Log if new message OR if parts were added to existing message
                                should_log = is_new_message or (latest_message_id == last_message_id and parts_count > last_parts_count)
                                
                                if should_log and latest_message_id:
                                    # Debug: Log message structure for troubleshooting
                                    logger.debug(f"[OpenCode] Job {job_id} poll #{poll_count}: Message {latest_message_id} has {parts_count} parts (was {last_parts_count}), keys: {list(latest_message.keys())}")
                                    
                                    # Only format and log if message has content (parts, content, or text)
                                    if parts_count > 0 or latest_message.get('content') or latest_message.get('text'):
                                        # Format message in human-readable way
                                        formatted_message = self._format_message_for_log(latest_message, poll_count)
                                        
                                        if self.debug_conversation_logging:
                                            event = {
                                                "timestamp": time.time(),
                                                "event_type": "polled_message",
                                                "data": formatted_message
                                            }
                                            self._write_event_to_streaming_log(event)

                                        # Also log to regular logger (truncated preview)
                                        preview = formatted_message[:300].replace('\n', ' ')
                                        logger.info(f"[OpenCode] Job {job_id} poll #{poll_count} (message: {latest_message_id}, {parts_count} parts): {preview}...")
                                    else:
                                        # Message exists but has no content yet - log a brief status
                                        logger.debug(f"[OpenCode] Job {job_id} poll #{poll_count}: Message {latest_message_id} created but no content yet (parts: {parts_count})")
                                
                                # Track parts count for this message
                                if latest_message_id:
                                    if not hasattr(self, '_last_message_parts_count'):
                                        self._last_message_parts_count = {}
                                    if session_id not in self._last_message_parts_count:
                                        self._last_message_parts_count[session_id] = {}
                                    self._last_message_parts_count[session_id][latest_message_id] = parts_count
                                    
                                    # Always update last seen message ID to the latest
                                    self._last_polled_message_id[session_id] = latest_message_id
                                
                            except json.JSONDecodeError:
                                # Fallback to old length-based tracking if JSON parsing fails
                                last_length = self._last_polled_message_length.get(session_id, 0)
                                current_length = len(data)
                                
                                if current_length > last_length:
                                    new_content = data[last_length:]
                                    if new_content.strip():
                                        if self.debug_conversation_logging:
                                            event = {
                                                "timestamp": time.time(),
                                                "event_type": "polled_message",
                                                "data": f"[Poll #{poll_count}] {new_content[:5000]}"
                                            }
                                            self._write_event_to_streaming_log(event)
                                        preview = new_content[:200].replace('\n', ' ')
                                        logger.info(f"[OpenCode] Job {job_id} poll #{poll_count} (new): {preview}...")
                                    self._last_polled_message_length[session_id] = current_length
                            except Exception as e:
                                logger.debug(f"[OpenCode] Job {job_id} poll #{poll_count} error parsing messages: {e}")
                    else:
                        logger.debug(f"[OpenCode] Job {job_id} poll #{poll_count}: status={status}")

                except asyncio.CancelledError:
                    logger.info(f"[OpenCode] Job {job_id}: Message polling task cancelled")
                    raise
                except Exception as e:
                    # Don't spam logs on errors, just debug level
                    if poll_count <= 3 or poll_count % 10 == 0:
                        logger.debug(f"[OpenCode] Job {job_id} poll #{poll_count} error: {e}")

                await asyncio.sleep(poll_interval)
            
        # Clean up tracking when polling ends
        if session_id in self._last_polled_message_length:
            del self._last_polled_message_length[session_id]
        if session_id in self._last_polled_message_id:
            del self._last_polled_message_id[session_id]
        # Clean up parts count tracking
        if hasattr(self, '_last_message_parts_count') and session_id in self._last_message_parts_count:
            del self._last_message_parts_count[session_id]
        logger.debug(f"[OpenCode] Job {job_id}: Cleaned up message tracking for session {session_id}")
    
    def _format_message_for_log(self, message: Dict[str, Any], poll_count: int) -> str:
        """
        Format a message object into a human-readable string for logging.
        
        Args:
            message: Message object from OpenCode API
            poll_count: Poll number for context
            
        Returns:
            Formatted human-readable string
        """
        info = message.get('info', {})
        parts = message.get('parts', [])
        
        # Extract key information
        msg_id = info.get('id', 'unknown')
        role = info.get('role', 'unknown')
        model_id = info.get('modelID') or info.get('model', {}).get('modelID', 'unknown')
        provider_id = info.get('providerID') or info.get('model', {}).get('providerID', 'unknown')
        time_info = info.get('time', {})
        created = time_info.get('created', 0)
        completed = time_info.get('completed')
        
        # Format timestamp
        if created:
            try:
                created_dt = datetime.fromtimestamp(created / 1000)
                created_str = created_dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                created_str = str(created)
        else:
            created_str = 'unknown'
        
        # Build formatted output
        lines = [
            f"[Poll #{poll_count}] Message Update",
            f"{'='*80}",
            f"Message ID: {msg_id}",
            f"Role: {role}",
            f"Model: {provider_id}/{model_id}",
            f"Created: {created_str}",
        ]
        
        if completed:
            try:
                completed_dt = datetime.fromtimestamp(completed / 1000)
                completed_str = completed_dt.strftime('%Y-%m-%d %H:%M:%S')
                duration_ms = completed - created
                duration_sec = duration_ms / 1000
                lines.append(f"Completed: {completed_str} (Duration: {duration_sec:.2f}s)")
            except:
                lines.append(f"Completed: {completed}")
        
        # Extract and format parts
        if parts:
            lines.append(f"\nParts ({len(parts)}):")
            for i, part in enumerate(parts, 1):
                part_type = part.get('type', 'unknown')
                part_id = part.get('id', 'unknown')
                lines.append(f"\n  Part {i}: {part_type} (ID: {part_id})")
                
                if part_type == 'text':
                    text = part.get('text', '')
                    if text:
                        # Truncate very long text
                        max_text_length = 2000
                        if len(text) > max_text_length:
                            text_preview = text[:max_text_length] + f"\n... [TRUNCATED: {len(text)} chars total]"
                        else:
                            text_preview = text
                        lines.append(f"    Text: {text_preview}")
                    else:
                        lines.append(f"    Text: <empty>")
                
                elif part_type == 'tool':
                    tool_name = part.get('tool', 'unknown')
                    call_id = part.get('callID', 'unknown')
                    state = part.get('state', {})
                    status = state.get('status', 'unknown')
                    tool_input = state.get('input', {})
                    
                    lines.append(f"    Tool: {tool_name}")
                    lines.append(f"    Call ID: {call_id}")
                    lines.append(f"    Status: {status}")
                    
                    if tool_input:
                        command = tool_input.get('command', '')
                        description = tool_input.get('description', '')
                        if command:
                            lines.append(f"    Command: {command}")
                        if description:
                            lines.append(f"    Description: {description}")
                    
                    if status == 'completed':
                        output = state.get('output', '')
                        if output:
                            max_output_length = 1000
                            if len(output) > max_output_length:
                                output_preview = output[:max_output_length] + f"\n... [TRUNCATED: {len(output)} chars total]"
                            else:
                                output_preview = output
                            lines.append(f"    Output: {output_preview}")
                
                elif part_type in ['step-start', 'step-finish']:
                    if part_type == 'step-finish':
                        reason = part.get('reason', '')
                        if reason:
                            lines.append(f"    Reason: {reason}")
                        cost = part.get('cost')
                        if cost is not None:
                            lines.append(f"    Cost: ${cost:.6f}")
                        tokens = part.get('tokens', {})
                        if tokens:
                            input_tokens = tokens.get('input', 0)
                            output_tokens = tokens.get('output', 0)
                            lines.append(f"    Tokens: {input_tokens} input, {output_tokens} output")
                else:
                    # Unknown part type - show raw data (truncated)
                    part_str = str(part)
                    if len(part_str) > 500:
                        part_str = part_str[:500] + "... [TRUNCATED]"
                    lines.append(f"    Raw data: {part_str}")
        else:
            # No parts found - check if there's content elsewhere in the message
            # Some message structures might have content directly in the message
            content = message.get('content', '')
            if content:
                if isinstance(content, str):
                    max_content_length = 2000
                    if len(content) > max_content_length:
                        content_preview = content[:max_content_length] + f"\n... [TRUNCATED: {len(content)} chars total]"
                    else:
                        content_preview = content
                    lines.append(f"\nContent: {content_preview}")
                elif isinstance(content, list):
                    lines.append(f"\nContent (list with {len(content)} items):")
                    for idx, item in enumerate(content[:5], 1):  # Show first 5 items
                        item_str = str(item)
                        if len(item_str) > 500:
                            item_str = item_str[:500] + "... [TRUNCATED]"
                        lines.append(f"  Item {idx}: {item_str}")
                    if len(content) > 5:
                        lines.append(f"  ... and {len(content) - 5} more items")
            
            # Also check for text directly in message
            text = message.get('text', '')
            if text:
                max_text_length = 2000
                if len(text) > max_text_length:
                    text_preview = text[:max_text_length] + f"\n... [TRUNCATED: {len(text)} chars total]"
                else:
                    text_preview = text
                lines.append(f"\nText: {text_preview}")
            
            # If still no content, indicate that parts array was empty
            if not content and not text:
                # Check if message is still being generated (might have status or state info)
                status = message.get('status', '')
                state = message.get('state', {})
                
                if status or state:
                    lines.append(f"\n[Message is being generated - no content yet]")
                    if status:
                        lines.append(f"Status: {status}")
                    if state:
                        state_str = str(state)
                        if len(state_str) > 500:
                            state_str = state_str[:500] + "... [TRUNCATED]"
                        lines.append(f"State: {state_str}")
                else:
                    lines.append(f"\n[No parts found in message - parts array is empty]")
                    # Log raw message structure for debugging (truncated)
                    message_str = str(message)
                    if len(message_str) > 1000:
                        message_str = message_str[:1000] + "... [TRUNCATED]"
                    lines.append(f"Message keys: {list(message.keys())}")
                    logger.debug(f"[OpenCode] Message {msg_id} has no parts. Message structure: {message_str[:500]}")
        
        lines.append(f"{'='*80}\n")
        
        return '\n'.join(lines)
    
    def _write_error_to_log(self, job_id: str, error_type: str, error_message: str, execution_time: float = 0):
        """
        Write error or cancellation information to the log file.
        
        This ensures errors and cancellations are preserved in the log for debugging.
        
        Args:
            job_id: Job identifier
            error_type: Type of error (TIMEOUT, CANCELLED, ERROR)
            error_message: Error message
            execution_time: Execution time before error (seconds)
        """
        if not self.debug_conversation_logging:
            return
        
        try:
            # Ensure log file handle is open
            if not self._log_file_handle and self._log_file_path:
                try:
                    self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                except Exception as e:
                    logger.error(f"[OpenCode] Job {job_id}: Failed to reopen log file for error logging: {e}")
                    return
            
            if not self._log_file_handle:
                return
            
            # Write error information
            error_time = datetime.now(tz=timezone.utc)
            error_time_str = error_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            
            error_lines = [
                f"\n{'='*80}",
                f"JOB TERMINATION: {error_type}",
                f"{'='*80}",
                f"Time: {error_time_str}",
                f"Execution Time: {execution_time:.2f}s",
                f"Error Type: {error_type}",
                f"Error Message: {error_message}",
                f"{'='*80}\n"
            ]
            
            for line in error_lines:
                self._log_file_handle.write(f"{line}\n")
            self._log_file_handle.flush()
            
            logger.info(f"[OpenCode] Job {job_id}: Wrote {error_type} information to log file")
        except Exception as e:
            logger.error(f"[OpenCode] Job {job_id}: Failed to write error to log file: {e}")

    async def _stream_container_logs(
        self,
        container_id: str,
        job_id: str,
        cancellation_event: Optional[asyncio.Event] = None
    ):
        """
        Stream container logs (stdout/stderr) to the streaming log file in real-time.
        
        This provides visibility into what OpenCode is doing internally, even when
        SSE events aren't arriving (e.g., when stuck waiting for MCP servers).
        
        Args:
            container_id: Docker container ID
            job_id: Job identifier
            cancellation_event: Optional event to signal cancellation
        """
        if not self.debug_conversation_logging:
            logger.debug(f"[OpenCode] Job {job_id}: Container log streaming skipped (debug_conversation_logging=False)")
            return
        
        if not self._log_file_handle:
            # Try to reopen the file if handle is None but debug logging is enabled
            if self._log_file_path:
                try:
                    logger.warning(f"[OpenCode] Job {job_id}: Container log streaming: file handle is None, attempting to reopen")
                    self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                    logger.info(f"[OpenCode] Job {job_id}: Successfully reopened log file for container log streaming")
                except Exception as e:
                    logger.error(f"[OpenCode] Job {job_id}: Failed to reopen log file for container streaming: {e}")
                    return
            else:
                logger.warning(f"[OpenCode] Job {job_id}: Container log streaming skipped (log file handle is None and no file path)")
                return
        
        try:
            container = self.docker_client.containers.get(container_id)

            # NOTE: We no longer write a separate CONTAINER LOGS section header.
            # Container logs are written as [container] events in the EVENTS section,
            # keeping all events in chronological order for easier debugging.

            # Stream logs in real-time using polling approach (more async-friendly)
            # Poll for new logs every second to avoid blocking the event loop
            seen_log_hashes = set()  # Track which log lines we've already written
            poll_interval = 1.0  # Poll every second
            poll_count = 0
            total_logs_written = 0
            
            logger.info(f"[OpenCode] Job {job_id}: Starting container log streaming task")

            # Log that we're starting container log streaming using standard event format
            start_event = {
                "timestamp": time.time(),
                "event_type": "system",
                "data": "Starting container log streaming"
            }
            self._write_event_to_streaming_log(start_event)
            logger.info(f"[OpenCode] Job {job_id}: ✅ Container log streaming start message written to log file")
            
            while True:
                poll_count += 1
                
                # Check cancellation
                if cancellation_event and cancellation_event.is_set():
                    logger.info(f"[OpenCode] Job {job_id}: Container log streaming cancelled (poll #{poll_count}, {total_logs_written} lines written)")
                    break
                
                # Check if log file handle is still valid - try to reopen if None
                if not self._log_file_handle:
                    if self._log_file_path:
                        try:
                            logger.warning(f"[OpenCode] Job {job_id}: Log file handle closed during streaming (poll #{poll_count}), attempting to reopen")
                            self._log_file_handle = open(self._log_file_path, 'a', encoding='utf-8')
                            logger.info(f"[OpenCode] Job {job_id}: Successfully reopened log file during container log streaming")
                        except Exception as e:
                            logger.error(f"[OpenCode] Job {job_id}: Failed to reopen log file during container streaming: {e}")
                            break
                    else:
                        logger.warning(f"[OpenCode] Job {job_id}: Log file handle closed, stopping container log streaming (poll #{poll_count}, {total_logs_written} lines written)")
                        break
                
                try:
                    # Get current logs - use since parameter to get logs from container start
                    # This ensures we capture all logs, not just recent ones
                    current_logs = container.logs(
                        stdout=True,
                        stderr=True,
                        since=datetime.fromtimestamp(self._conversation_start_time, tz=timezone.utc) if self._conversation_start_time else None,
                        tail=1000  # Get last 1000 lines as fallback
                    )
                    
                    # Decode logs
                    if isinstance(current_logs, bytes):
                        try:
                            log_text = current_logs.decode('utf-8', errors='replace')
                        except Exception:
                            log_text = str(current_logs)
                    else:
                        log_text = str(current_logs)
                    
                    # Process lines (skip duplicates using hash)
                    lines = log_text.split('\n')
                    new_count = 0
                    
                    for log_line in lines:
                        log_line = log_line.rstrip('\n\r')
                        if not log_line.strip():
                            continue
                        
                        # Create hash of log line to detect duplicates
                        line_hash = hashlib.md5(log_line.encode('utf-8')).hexdigest()
                        
                        if line_hash in seen_log_hashes:
                            continue  # Already seen this line
                        
                        seen_log_hashes.add(line_hash)
                        new_count += 1
                        total_logs_written += 1
                        
                        # Write to streaming log - use _write_event_to_streaming_log for consistency and auto-recovery
                        try:
                            container_log_event = {
                                "timestamp": time.time(),
                                "event_type": "container",
                                "data": log_line
                            }
                            self._write_event_to_streaming_log(container_log_event)
                        except Exception as e:
                            logger.error(f"[OpenCode] Job {job_id}: CRITICAL: Failed to write container log line: {e}")
                            # Don't break - continue trying to write other lines
                            continue
                    
                    if new_count > 0:
                        logger.info(f"[OpenCode] Job {job_id}: Wrote {new_count} new container log lines (total: {total_logs_written} lines written so far)")
                    elif poll_count % 10 == 0:  # Log every 10 polls if no new logs
                        logger.debug(f"[OpenCode] Job {job_id}: Container log polling (poll #{poll_count}, {total_logs_written} total lines written)")
                    
                    # Limit hash set size to prevent memory issues (keep last 1000)
                    if len(seen_log_hashes) > 1000:
                        # Keep only recent hashes (simple approach: clear and rebuild from recent logs)
                        seen_log_hashes.clear()
                        # Rebuild from last 100 lines
                        for log_line in lines[-100:]:
                            log_line = log_line.rstrip('\n\r')
                            if log_line.strip():
                                line_hash = hashlib.md5(log_line.encode('utf-8')).hexdigest()
                                seen_log_hashes.add(line_hash)
                    
                    # Check if container is still running
                    try:
                        container.reload()
                        if container.status != 'running':
                            # Container stopped, break loop
                            logger.debug(f"[OpenCode] Job {job_id}: Container stopped (status: {container.status}), stopping log streaming")
                            break
                    except NotFound:
                        # Container removed
                        logger.debug(f"[OpenCode] Job {job_id}: Container removed, stopping log streaming")
                        break
                    
                    # Wait before next poll
                    await asyncio.sleep(poll_interval)
                    
                except NotFound:
                    # Container was removed
                    logger.debug(f"[OpenCode] Job {job_id}: Container not found, stopping log streaming")
                    break
                except Exception as e:
                    logger.warning(f"[OpenCode] Job {job_id}: Error polling container logs: {e}")
                    # Continue polling even on errors
                    await asyncio.sleep(poll_interval)
                
        except NotFound:
            # Container was removed, stop streaming
            if self._log_file_handle:
                try:
                    self._log_file_handle.write(f"[{datetime.now(tz=timezone.utc).isoformat()}] [container] Container removed, stopping log stream\n")
                    self._log_file_handle.flush()
                except Exception:
                    pass
        except asyncio.CancelledError:
            # Task was cancelled, stop streaming
            if self._log_file_handle:
                try:
                    self._log_file_handle.write(f"[{datetime.now(tz=timezone.utc).isoformat()}] [container] Log streaming cancelled\n")
                    self._log_file_handle.flush()
                except Exception:
                    pass
            raise
        except Exception as e:
            # Log error but don't crash the main job
            logger.warning(f"[OpenCode] Job {job_id}: Error streaming container logs: {e}")
            if self._log_file_handle:
                try:
                    error_time = datetime.now(tz=timezone.utc).isoformat()
                    self._log_file_handle.write(f"[{error_time}] [container] Error streaming logs: {e}\n")
                    self._log_file_handle.flush()
                except Exception:
                    pass
    
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
        # CRITICAL: Do NOT overwrite the streaming log file - it already contains all the real-time events
        # Instead, append a summary section if the file exists, or create it if it doesn't
        text_path = log_dir / f"{job_id}.log"
        try:
            # Check if streaming log file already exists (it should, since we've been writing to it)
            if text_path.exists() and text_path.stat().st_size > 0:
                # File exists with content - append summary section instead of overwriting
                with open(text_path, 'a', encoding='utf-8') as f:
                    f.write(f"\n\n{'='*80}\n")
                    f.write("SUMMARY (Appended at completion)\n")
                    f.write(f"{'='*80}\n")
                    f.write(f"Job ID: {job_id}\n")
                    f.write(f"Started: {start_time_str}\n")
                    f.write(f"Ended: {end_time_str}\n")
                    f.write(f"Duration: {duration:.3f}s\n")
                    f.write(f"Total Events Logged: {len(self._conversation_logs)}\n")
                    f.write(f"{'='*80}\n")
                
                logger.info(f"[OpenCode] Job {job_id}: Appended summary to existing streaming log at {text_path}")
            else:
                # File doesn't exist or is empty - create it with full content
                # This is a fallback in case streaming logging wasn't enabled or failed
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
                
                logger.info(f"[OpenCode] Job {job_id}: Created conversation log at {text_path} (streaming log was empty or missing)")
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
