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
        llm_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize the OpenCode runner.
        
        Args:
            docker_image: OpenCode Docker image to use
            job_timeout_minutes: Maximum job execution time
            max_result_size_mb: Maximum result file size
            result_file: Name of the result file to read
            llm_config: LLM configuration dict with API keys and settings
        """
        self.docker_image = docker_image
        self.job_timeout_seconds = job_timeout_minutes * 60
        self.max_result_size_bytes = max_result_size_mb * 1024 * 1024
        self.result_file = result_file
        self.llm_config = llm_config or {}
        
        self._docker_client: Optional[docker.DockerClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
    
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
        
        # LLM API Keys - check config first, then environment
        api_key_mappings = [
            ('openai_api_key', 'OPENAI_API_KEY'),
            ('anthropic_api_key', 'ANTHROPIC_API_KEY'),
            ('google_api_key', 'GOOGLE_API_KEY'),
            ('gemini_api_key', 'GEMINI_API_KEY'),
            ('moonshot_api_key', 'MOONSHOT_API_KEY'),
        ]
        
        for config_key, env_key in api_key_mappings:
            value = self.llm_config.get(config_key) or os.getenv(env_key)
            if value:
                env[env_key] = value
        
        # LLM Provider and Model settings
        provider = self.llm_config.get('provider') or os.getenv('LLM_PROVIDER')
        if provider:
            env['LLM_PROVIDER'] = provider
            
            # Get model for the provider
            model_key = f'{provider}_model'
            model = self.llm_config.get(model_key) or os.getenv(f'{provider.upper()}_MODEL')
            if model:
                env['LLM_MODEL'] = model
        
        # Filter out None/empty values
        return {k: v for k, v in env.items() if v}
    
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
        cancellation_event: Optional[asyncio.Event] = None
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
                    job_id, workspace_path, prompt, job_type, cancellation_event
                )
        else:
            return await self._execute_internal(
                job_id, workspace_path, prompt, job_type, cancellation_event
            )
    
    async def _execute_internal(
        self,
        job_id: str,
        workspace_path: Path,
        prompt: str,
        job_type: str,
        cancellation_event: Optional[asyncio.Event] = None
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
            container, port = await self._spawn_container(job_id, workspace_path)
            container_id = container.id
            
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
            
            # Read result file
            result = await self._read_result(workspace_path, job_type)
            
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
    
    async def _spawn_container(
        self,
        job_id: str,
        workspace_path: Path
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
            
            # Build environment variables for container
            container_env = self._build_container_environment()
            
            # Create and start container
            container = self.docker_client.containers.run(
                self.docker_image,
                name=container_name,
                command=["serve", "--hostname", "0.0.0.0", "--port", "4096"],
                volumes={
                    str(workspace_path): {"bind": "/workspace", "mode": "rw"}
                },
                ports={"4096/tcp": None},  # Random host port
                detach=True,
                remove=False,  # We remove manually after getting result
                working_dir="/workspace",
                environment=container_env
            )
            
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
        
        last_error = None
        backoff = SSE_INITIAL_BACKOFF
        
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
                            # Check if it's an error response
                            if "error" in data:
                                raise ContainerError(f"OpenCode returned error: {data.get('error')}")
                            # Otherwise, assume it completed successfully
                            logger.info(f"[OpenCode] Job {job_id}: Received JSON response (non-streaming completion)")
                            return
                        except json.JSONDecodeError:
                            logger.warning(f"[OpenCode] Job {job_id}: Invalid JSON in response")
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
    
    def _process_sse_event_obj(self, event, job_id: str):
        """Process an SSE event object from httpx-sse"""
        event_type = event.event or "message"
        data = event.data or ""
        
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
    
    async def _read_result(
        self,
        workspace_path: Path,
        job_type: str
    ) -> Dict[str, Any]:
        """
        Read and validate result.json from workspace.
        
        Args:
            workspace_path: Path to workspace
            job_type: Type of job for validation
            
        Returns:
            Parsed and validated result
            
        Raises:
            ResultError: If result cannot be read or validated
        """
        result_path = workspace_path / self.result_file
        
        # Check if file exists
        if not result_path.exists():
            logger.error(f"Result file not found: {result_path}")
            raise ResultError(
                f"OpenCode did not produce {self.result_file}. "
                "The LLM may not have followed instructions to write the result file."
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
