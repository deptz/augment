"""
Run OpenCode inside OpenSandbox: clone in sandbox, run OpenCode (pre-installed in image), read result.
"""
import asyncio
import json
import logging
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .sandbox_client import (
    SandboxClient,
    SandboxClientError,
    SandboxResultError,
)
from .sandbox_git_ops import SandboxGitOps

logger = logging.getLogger(__name__)

# Optional: used for network policy and type hints
try:
    from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule
except ImportError:
    NetworkPolicy = None  # type: ignore[misc, assignment]
    NetworkRule = None  # type: ignore[misc, assignment]


class SandboxCodeRunner:
    """
    Runs OpenCode inside OpenSandbox. The sandbox clones the repo directly via git.
    Results are read via sandbox.files.read_file(). For code application, changes
    are committed and pushed from inside the sandbox.
    """

    def __init__(
        self,
        sandbox_client: SandboxClient,
        image: str = "opensandbox/code-interpreter:v1.0.1",
        timeout_minutes: int = 20,
        apply_timeout_minutes: int = 45,
        max_result_size_bytes: int = 10 * 1024 * 1024,
        result_file: str = "result.json",
        llm_config: Optional[Dict[str, Any]] = None,
        git_username: Optional[str] = None,
        git_password: Optional[str] = None,
        network_policy: Optional[Any] = None,
    ):
        self.sandbox_client = sandbox_client
        self.image = image
        self.timeout = timedelta(minutes=timeout_minutes)
        self.apply_timeout_minutes = apply_timeout_minutes
        self.max_result_size_bytes = max_result_size_bytes
        self.result_file = result_file
        self.opencode_version = "latest"
        self.llm_config = llm_config or {}
        self.git_username = git_username
        self.git_password = git_password
        self.network_policy = network_policy or self._default_network_policy()

    def set_llm_config(self, llm_config: Dict[str, Any]) -> None:
        self.llm_config = llm_config

    def _default_network_policy(self) -> Any:
        if NetworkPolicy is None or NetworkRule is None:
            return None
        return NetworkPolicy(
            defaultAction="deny",
            egress=[
                NetworkRule(action="allow", target="pypi.org"),
                NetworkRule(action="allow", target="files.pythonhosted.org"),
                NetworkRule(action="allow", target="registry.npmjs.org"),
                NetworkRule(action="allow", target="repo.maven.apache.org"),
                NetworkRule(action="allow", target="proxy.golang.org"),
                NetworkRule(action="allow", target="api.openai.com"),
                NetworkRule(action="allow", target="api.anthropic.com"),
                NetworkRule(action="allow", target="generativelanguage.googleapis.com"),
                NetworkRule(action="allow", target="api.moonshot.cn"),
                NetworkRule(action="allow", target="github.com"),
                NetworkRule(action="allow", target="*.github.com"),
                NetworkRule(action="allow", target="bitbucket.org"),
                NetworkRule(action="allow", target="*.bitbucket.org"),
            ],
        )

    def _build_env(self) -> Dict[str, str]:
        env = {
            "OPENCODE_WORKSPACE": "/workspace/repo",
            "PYTHON_VERSION": "3.11",
        }
        provider_env_map = {
            "openai": ("OPENAI_API_KEY", self.llm_config.get("openai_api_key")),
            "anthropic": ("ANTHROPIC_API_KEY", self.llm_config.get("anthropic_api_key")),
            "google": ("GOOGLE_API_KEY", self.llm_config.get("google_api_key")),
            "gemini": ("GEMINI_API_KEY", self.llm_config.get("gemini_api_key")),
            "moonshot": ("MOONSHOT_API_KEY", self.llm_config.get("moonshot_api_key")),
        }
        for _provider, (env_key, value) in provider_env_map.items():
            if value:
                env[env_key] = value
            elif os.environ.get(env_key):
                env[env_key] = os.environ[env_key]
        provider = self.llm_config.get("provider")
        if provider:
            env["LLM_PROVIDER"] = provider
            env["OPENCODE_PROVIDER"] = provider
            model = self.llm_config.get(f"{provider}_model") or self.llm_config.get("model")
            if model:
                env["LLM_MODEL"] = model
                env["OPENCODE_MODEL"] = model
        return {k: v for k, v in env.items() if v}

    async def execute_plan_generation(
        self,
        job_id: str,
        repo_url: str,
        branch: Optional[str],
        prompt: str,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """
        Generate a plan using OpenCode in a short-lived sandbox.
        Create → clone (shallow) → run OpenCode → read result.json → destroy.

        Args:
            job_id: Job id (used for sandbox tracking).
            repo_url: Git clone URL.
            branch: Optional branch.
            prompt: OpenCode prompt for plan generation.
            cancellation_event: If set, exit early.

        Returns:
            Parsed result dict (e.g. plan or wrapped plan).

        Raises:
            SandboxClientError: On sandbox or OpenCode failure.
            asyncio.CancelledError: When cancellation_event is set.
        """
        self._check_cancelled(cancellation_event)
        sandbox = await self.sandbox_client.create_sandbox(
            job_id=f"plan-{job_id}",
            image=self.image,
            env=self._build_env(),
            timeout=self.timeout,
            resource={"cpu": "2", "memory": "4Gi"},
            network_policy=self.network_policy,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        )
        try:
            async with sandbox:
                git_ops = SandboxGitOps(sandbox)
                self._check_cancelled(cancellation_event)
                await git_ops.clone(
                    url=repo_url,
                    branch=branch,
                    shallow=True,
                    git_username=self.git_username,
                    git_password=self.git_password,
                )
                self._check_cancelled(cancellation_event)
                await self._run_opencode(sandbox, prompt, "/workspace/repo")
                self._check_cancelled(cancellation_event)
                result = await self._read_result(sandbox, "/workspace/repo")
                await sandbox.kill()
                return result
        except asyncio.CancelledError:
            await self._safe_kill(sandbox)
            raise
        except SandboxClientError:
            await self._safe_kill(sandbox)
            raise
        except Exception as e:
            await self._safe_kill(sandbox)
            raise SandboxClientError(f"Plan generation failed: {e}") from e
        finally:
            self.sandbox_client.release_sandbox(f"plan-{job_id}")

    async def execute_generic(
        self,
        job_id: str,
        repo_url: str,
        branch: Optional[str],
        prompt: str,
        job_type: str,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """
        Run OpenCode in a short-lived sandbox for any job type (ticket_description, task_breakdown, coverage_check, plan_generation).
        Create → clone (shallow) → run OpenCode → read result.json → validate → destroy.
        """
        self._check_cancelled(cancellation_event)
        sandbox = await self.sandbox_client.create_sandbox(
            job_id=f"gen-{job_id}",
            image=self.image,
            env=self._build_env(),
            timeout=self.timeout,
            resource={"cpu": "2", "memory": "4Gi"},
            network_policy=self.network_policy,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        )
        try:
            async with sandbox:
                git_ops = SandboxGitOps(sandbox)
                self._check_cancelled(cancellation_event)
                await git_ops.clone(
                    url=repo_url,
                    branch=branch,
                    shallow=True,
                    git_username=self.git_username,
                    git_password=self.git_password,
                )
                self._check_cancelled(cancellation_event)
                await self._run_opencode(sandbox, prompt, "/workspace/repo")
                self._check_cancelled(cancellation_event)
                result = await self._read_result(sandbox, "/workspace/repo")
                await sandbox.kill()
                if job_type:
                    from .opencode_schemas import validate_opencode_result, validate_result_content
                    validate_opencode_result(result, job_type)
                    if not validate_result_content(result, job_type):
                        raise SandboxResultError(
                            f"OpenCode result for job_type={job_type} failed content validation"
                        )
                return result
        except asyncio.CancelledError:
            await self._safe_kill(sandbox)
            raise
        except SandboxClientError:
            await self._safe_kill(sandbox)
            raise
        except Exception as e:
            await self._safe_kill(sandbox)
            raise SandboxClientError(f"Sandbox execution failed ({job_type}): {e}") from e
        finally:
            self.sandbox_client.release_sandbox(f"gen-{job_id}")

    async def create_apply_sandbox(
        self,
        job_id: str,
        repo_url: str,
        branch: Optional[str],
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Any:
        """Create a long-lived sandbox for APPLY → VERIFY → PACKAGE → DRAFT_PR. Full clone (for push)."""
        self._check_cancelled(cancellation_event)
        sandbox = await self.sandbox_client.create_sandbox(
            job_id=f"apply-{job_id}",
            image=self.image,
            env=self._build_env(),
            timeout=timedelta(minutes=self.apply_timeout_minutes),
            resource={"cpu": "2", "memory": "4Gi"},
            network_policy=self.network_policy,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        )
        try:
            git_ops = SandboxGitOps(sandbox)
            await git_ops.clone(
                url=repo_url,
                branch=branch,
                shallow=False,
                git_username=self.git_username,
                git_password=self.git_password,
            )
            return sandbox
        except Exception:
            await self._safe_kill(sandbox)
            self.sandbox_client.release_sandbox(f"apply-{job_id}")
            raise

    async def run_code_application(
        self,
        sandbox: Any,
        prompt: str,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Run OpenCode for code application inside existing sandbox."""
        self._check_cancelled(cancellation_event)
        await self._run_opencode(sandbox, prompt, "/workspace/repo")
        self._check_cancelled(cancellation_event)
        return await self._read_result(sandbox, "/workspace/repo")

    async def execute(
        self,
        job_id: str,
        workspace_path: Any,
        prompt: str,
        job_type: str,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible interface matching OpenCodeRunner.execute()."""
        repo_url = self._infer_repo_url(workspace_path)
        return await self.execute_plan_generation(
            job_id=job_id,
            repo_url=repo_url,
            branch=None,
            prompt=prompt,
            cancellation_event=cancellation_event,
        )

    async def _run_opencode(self, sandbox: Any, prompt: str, cwd: str) -> None:
        escaped = prompt.replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        result = await sandbox.commands.run(
            f'cd {cwd} && opencode run "{escaped}" --format json'
        )
        if result.exit_code != 0:
            stderr = "".join(msg.text for msg in result.logs.stderr) if result.logs.stderr else ""
            logger.warning("OpenCode exited with code %s: %s", result.exit_code, stderr[:200])

    async def _read_result(self, sandbox: Any, workspace: str) -> Dict[str, Any]:
        try:
            content = await sandbox.files.read_file(f"{workspace}/{self.result_file}")
        except Exception as e:
            raise SandboxResultError(
                f"OpenCode did not produce {self.result_file}"
            ) from e
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        if len(content.encode("utf-8")) > self.max_result_size_bytes:
            raise SandboxResultError(
                f"Result too large: {len(content)} bytes (max {self.max_result_size_bytes})"
            )
        content = content.strip()
        json_str = self._extract_json(content)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise SandboxResultError(f"Invalid JSON in {self.result_file}: {e}") from e

    def _extract_json(self, content: str) -> str:
        if content.startswith("{") or content.startswith("["):
            return content
        match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", content)
        return match.group(1).strip() if match else content

    def _check_cancelled(self, event: Optional[asyncio.Event]) -> None:
        if event and event.is_set():
            raise asyncio.CancelledError("Job cancellation requested")

    async def _safe_kill(self, sandbox: Any) -> None:
        try:
            await sandbox.kill()
        except Exception:
            pass

    def _infer_repo_url(self, workspace_path: Any) -> str:
        workspace = Path(str(workspace_path))
        for child in workspace.iterdir():
            if child.is_dir() and (child / ".git").exists():
                from git import Repo
                repo = Repo(child)
                return repo.remotes.origin.url
        raise SandboxClientError(f"No git repo found in {workspace_path}")
