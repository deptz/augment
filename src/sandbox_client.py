"""
OpenSandbox client: connection pooling, sandbox lifecycle, orphan cleanup.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Optional OpenSandbox SDK imports (app works without them if sandbox disabled)
try:
    import httpx
    from opensandbox.sandbox import Sandbox
    from opensandbox.config import ConnectionConfig
    from opensandbox.manager import SandboxManager
    from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule, SandboxFilter
    from opensandbox.exceptions import SandboxException
    _OPENSANDBOX_AVAILABLE = True
except ImportError:
    Sandbox = None  # type: ignore[misc, assignment]
    ConnectionConfig = None  # type: ignore[misc, assignment]
    SandboxManager = None  # type: ignore[misc, assignment]
    NetworkPolicy = None  # type: ignore[misc, assignment]
    NetworkRule = None  # type: ignore[misc, assignment]
    SandboxFilter = None  # type: ignore[misc, assignment]
    SandboxException = Exception  # type: ignore[misc, assignment]
    _OPENSANDBOX_AVAILABLE = False


def network_policy_from_config(config: Optional[Dict[str, Any]]) -> Optional[Any]:
    """
    Build OpenSandbox NetworkPolicy from config dict.

    Config shape: { "default_action": "deny", "egress": [ {"action": "allow", "target": "pypi.org"}, ... ] }.
    Returns None if SDK unavailable or config is empty/None.
    """
    if not config or not _OPENSANDBOX_AVAILABLE or NetworkPolicy is None or NetworkRule is None:
        return None
    egress_list = config.get("egress")
    if not egress_list or not isinstance(egress_list, list):
        return None
    rules = []
    for e in egress_list:
        if isinstance(e, dict) and e.get("action") and e.get("target"):
            rules.append(NetworkRule(action=str(e["action"]), target=str(e["target"])))
    if not rules:
        return None
    default_action = (config.get("default_action") or "deny").strip().lower()
    # SDK uses camelCase defaultAction
    return NetworkPolicy(defaultAction=default_action, egress=rules)


class SandboxClientError(Exception):
    """Base exception for sandbox client errors."""
    pass


class SandboxUnavailableError(SandboxClientError):
    """OpenSandbox server is unreachable or sandbox creation failed."""
    pass


class SandboxTimeoutError(SandboxClientError):
    """Sandbox operation timed out."""
    pass


class SandboxResultError(SandboxClientError):
    """Result extraction failed."""
    pass


class SandboxGitError(SandboxClientError):
    """Git operation inside sandbox failed."""
    pass


class SandboxClient:
    """
    Centralized OpenSandbox client with connection pooling,
    sandbox tracking, and lifecycle management.
    """

    def __init__(
        self,
        domain: str = "localhost:8080",
        api_key: Optional[str] = None,
        protocol: str = "http",
        max_concurrent: int = 5,
        request_timeout: timedelta = timedelta(seconds=30),
    ):
        if not _OPENSANDBOX_AVAILABLE:
            raise SandboxUnavailableError(
                "OpenSandbox SDK not installed. Install with: pip install opensandbox opensandbox-code-interpreter"
            )
        self._transport = httpx.AsyncHTTPTransport(
            limits=httpx.Limits(
                max_connections=max_concurrent * 2,
                max_keepalive_connections=max_concurrent,
            ),
            keepalive_expiry=30.0,
        )
        self._config = ConnectionConfig(
            domain=domain,
            api_key=api_key or "",
            protocol=protocol,
            request_timeout=request_timeout,
            transport=self._transport,
        )
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_sandboxes: Dict[str, str] = {}  # job_id -> sandbox_id

    @property
    def config(self) -> "Any":
        return self._config

    async def is_available(self) -> bool:
        """Health check against OpenSandbox server."""
        try:
            async with await SandboxManager.create(connection_config=self._config) as manager:
                await manager.list_sandbox_infos(SandboxFilter(page_size=1))
            return True
        except Exception:
            return False

    async def create_sandbox(
        self,
        job_id: str,
        image: str,
        env: Dict[str, str],
        timeout: timedelta = timedelta(minutes=20),
        resource: Optional[Dict[str, str]] = None,
        network_policy: Optional[Any] = None,
        entrypoint: Optional[List[str]] = None,
    ) -> "Sandbox":
        """
        Create a sandbox with semaphore-gated concurrency.

        Args:
            job_id: Used for tracking; caller must call release_sandbox(job_id) in finally.
            image: Container image (e.g. opensandbox/code-interpreter:v1.0.1).
            env: Environment variables for the sandbox.
            timeout: Sandbox lifetime.
            resource: Optional CPU/memory.
            network_policy: Optional egress rules.
            entrypoint: Optional entrypoint.

        Returns:
            Sandbox instance (use async with sandbox: or call sandbox.kill()).

        Raises:
            SandboxUnavailableError: If creation fails. Semaphore is released before raise.
        """
        await self._semaphore.acquire()
        try:
            sandbox = await Sandbox.create(
                image,
                connection_config=self._config,
                timeout=timeout,
                resource=resource or {"cpu": "2", "memory": "4Gi"},
                env=env,
                entrypoint=entrypoint,
                network_policy=network_policy,
            )
            self._active_sandboxes[job_id] = sandbox.id
            return sandbox
        except SandboxException as e:
            self._semaphore.release()
            raise SandboxUnavailableError(
                f"Failed to create sandbox: [{getattr(e, 'error', e).code}] {getattr(getattr(e, 'error', e), 'message', str(e))}"
            ) from e
        except Exception as e:
            self._semaphore.release()
            raise SandboxUnavailableError(f"Failed to create sandbox: {e}") from e

    def release_sandbox(self, job_id: str) -> None:
        """Release semaphore and remove tracking entry."""
        self._active_sandboxes.pop(job_id, None)
        self._semaphore.release()

    async def cleanup_orphaned_sandboxes(self, max_age_minutes: int = 30) -> int:
        """Kill sandboxes older than max_age that aren't tracked."""
        cleaned = 0
        try:
            async with await SandboxManager.create(connection_config=self._config) as manager:
                result = await manager.list_sandbox_infos(
                    SandboxFilter(states=["RUNNING", "PAUSED"])
                )
                tracked_ids = set(self._active_sandboxes.values())
                for info in result.sandbox_infos:
                    if info.id not in tracked_ids:
                        age_minutes = (datetime.utcnow() - info.created_at).total_seconds() / 60
                        if age_minutes > max_age_minutes:
                            await manager.kill_sandbox(info.id)
                            cleaned += 1
        except Exception as e:
            logger.warning("Orphan cleanup failed: %s", e)
        return cleaned

    async def pause_sandbox(self, sandbox_id: str) -> None:
        """
        Pause a sandbox by ID (for debugging). Uses Sandbox.resume() to get a handle, then pause().
        Raises SandboxClientError if the SDK does not support pause or the operation fails.
        """
        try:
            sandbox = await Sandbox.resume(
                sandbox_id=sandbox_id,
                connection_config=self._config,
            )
            await sandbox.pause()
        except AttributeError:
            raise SandboxClientError(
                "OpenSandbox SDK does not support pause (sandbox.pause not available)"
            )
        except Exception as e:
            raise SandboxClientError(f"Failed to pause sandbox {sandbox_id}: {e}") from e

    async def resume_sandbox(self, sandbox_id: str) -> None:
        """
        Resume a paused sandbox by ID. Uses Sandbox.resume() to reconnect; the sandbox is resumed.
        Raises SandboxClientError if the SDK does not support resume or the operation fails.
        """
        try:
            sandbox = await Sandbox.resume(
                sandbox_id=sandbox_id,
                connection_config=self._config,
            )
            # Resuming gives us a handle; sandbox is now running. No need to hold the handle.
            del sandbox
        except AttributeError:
            raise SandboxClientError(
                "OpenSandbox SDK does not support resume (Sandbox.resume not available)"
            )
        except Exception as e:
            raise SandboxClientError(f"Failed to resume sandbox {sandbox_id}: {e}") from e

    async def get_sandbox_status(self, sandbox_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status info for a sandbox by ID (e.g. state RUNNING/PAUSED).
        Returns a dict with at least 'id' and 'state', or None if not found.
        """
        try:
            async with await SandboxManager.create(connection_config=self._config) as manager:
                result = await manager.list_sandbox_infos(
                    SandboxFilter(page_size=100)
                )
                for info in result.sandbox_infos:
                    if info.id == sandbox_id:
                        return {
                            "id": info.id,
                            "state": getattr(info, "state", "UNKNOWN"),
                        }
            return None
        except Exception as e:
            logger.warning("get_sandbox_status failed for %s: %s", sandbox_id, e)
            return None

    async def close(self) -> None:
        """Close shared transport."""
        await self._transport.aclose()
