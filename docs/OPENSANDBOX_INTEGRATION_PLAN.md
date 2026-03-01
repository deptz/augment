# OpenSandbox Integration Implementation Plan

**Status:** Draft  
**Last Updated:** 2026-03-01  

---

## 1. Executive Summary

This document outlines the integration of [OpenSandbox](https://github.com/alibaba/OpenSandbox) (Alibaba) into Augment to provide standardized, isolated, and scalable code execution environments. The integration replaces direct Docker management (`OpenCodeRunner`), host-based verification (`Verifier`), and host-based git operations with OpenSandbox's unified sandbox platform.

**Core principle:** The sandbox owns the entire compute lifecycle — clone, code generation, git transactions, verification, packaging, and push. The host only orchestrates sandbox lifecycle and makes Bitbucket API calls.

### Key Benefits

| Benefit | Description |
|---------|-------------|
| **Standardized Lifecycle** | Unified create/destroy/pause/resume APIs for all sandboxes |
| **Multi-Language Support** | Native Python, Java, Go, Node.js execution via code-interpreter image |
| **Better Isolation** | Network policies, resource limits, and security boundaries |
| **Scalability** | Kubernetes runtime for horizontal scaling beyond single machine |
| **Simplified Operations** | Single sandbox platform instead of custom container management |
| **No File Transfer** | Git clone inside sandbox eliminates upload/download overhead entirely |
| **CI/CD-Like Model** | Each pipeline stage gets a fresh clone — reproducible, stateless |

### SDK Clarification

There are two similarly-named Python packages. This plan uses the **Alibaba SDK**:

| Package | PyPI Name | Source | Used Here |
|---------|-----------|--------|-----------|
| Alibaba SDK | `opensandbox` | `alibaba/OpenSandbox` | **Yes** |
| Digger SDK (E2B-compat) | `opensandbox-sdk` | `diggerhq/opensandbox` | No |
| Code Interpreter | `opensandbox-code-interpreter` | `alibaba/OpenSandbox` | **Yes** |

Use the Alibaba `opensandbox` and `opensandbox-code-interpreter` packages (not the Digger `opensandbox-sdk`).

---

## What Needs to Be Done

1. **Foundation**
   - Build a custom Docker image from `opensandbox/code-interpreter` with OpenCode CLI, pytest, and ruff pre-installed.
   - Add OpenSandbox SDK and config; implement `SandboxClient`, `SandboxGitOps`, and retry-with-backoff.
   - Fix the draft PR worker so it always calls `unregister_ticket_job(story_key)` (e.g. in a `finally` block).
   - Fix missing `plan_generation` / `code_application` in `JOB_TYPE_SCHEMAS` and define `ArtifactStoreError`.

2. **Sandbox execution**
   - Implement `SandboxCodeRunner`: create sandbox, clone repo in sandbox, run OpenCode (no install step), read result, destroy sandbox.
   - Implement `SandboxVerifier`: run test, lint, and build in parallel inside the same sandbox that has the repo.

3. **Full pipeline in one sandbox**
   - Implement `SandboxPipelineRunner`: one sandbox for APPLY → VERIFY → PACKAGE → DRAFT_PR (clone, apply, git checkpoint/rollback, plan-apply guard, verify, package, branch + push). Host only creates/destroys sandbox and calls Bitbucket API to create the PR.
   - Integrate into `DraftPRPipeline` behind a feature flag; keep legacy path for fallback.
   - Wire Redis cancellation to `cancellation_event` for draft PR jobs; add overall job timeout.

4. **Operations and hardening**
   - Add sandbox pause/resume/status API and store `sandbox_id` in Redis for cross-process visibility.
   - Worker startup: check OpenSandbox availability and run orphan sandbox cleanup.
   - Optional: Kubernetes runtime and migration/deprecation of the old Docker path.

---

## 2. Architecture Overview

### 2.1 Current Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Augment API/Worker                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│   OpenCode    │          │    Verifier   │          │   Workspace   │
│    Runner     │          │  (subprocess) │          │   Manager     │
└───────┬───────┘          └───────┬───────┘          └───────┬───────┘
        │                          │                          │
        ▼                          ▼                          ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│ Docker Client │          │     Host      │          │   Git Clone   │
│  (direct API) │          │   Shell Exec  │          │   to /tmp     │
└───────────────┘          └───────────────┘          └───────────────┘
```

**Pain Points (verified from codebase):**
- Direct Docker API calls require manual lifecycle management (`_spawn_container`, `_stop_container`, `_wait_for_ready`)
- No resource limits or network isolation on containers
- Verifier runs on host via `subprocess` — security, reproducibility, and PATH dependency issues
- `command.split()` breaks quoted arguments (e.g., `pytest -k "test foo"`)
- Verifier `cwd` is `workspace_path` (parent dir), not repo root — wrong for multi-repo workspaces
- `plan_generation` and `code_application` job types missing from `JOB_TYPE_SCHEMAS` — validation fails
- No cancellation bridge: Redis `job:cancel:{job_id}` flags never reach `cancellation_event` in pipeline
- Single-node scaling limited to `max_concurrent` semaphore (default 2)
- Orphan container cleanup depends on `augment-opencode-` name prefix convention
- Host workspace persists across approval gap — consumes disk, orphan cleanup needed

### 2.2 Target Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Augment API/Worker                             │
│                                                                          │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  │
│  │ SandboxPipeline │  │ SandboxVerifier │  │   BitbucketClient       │  │
│  │ Runner          │  │ (inside sandbox)│  │   (HTTP only, on host)  │  │
│  └────────┬────────┘  └────────┬────────┘  └────────────┬────────────┘  │
│           │                    │                        │               │
│  ┌────────┴────────────────────┘                        │               │
│  │   SandboxClient (connection pool + lifecycle mgmt)   │               │
│  └────────┬─────────────────────────────────────────────┘               │
└───────────┼─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      OpenSandbox Server (Lifecycle API)                  │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                      Runtime Layer                                │   │
│  │   ┌──────────────┐              ┌──────────────┐                │   │
│  │   │    Docker    │              │  Kubernetes  │                │   │
│  │   │   Runtime    │              │   Runtime    │                │   │
│  │   └──────┬───────┘              └──────┬───────┘                │   │
│  │          ▼                              ▼                       │   │
│  │   ┌──────────────────────────────────────────────────────┐      │   │
│  │   │               Sandbox Container/Pod                   │      │   │
│  │   │                                                       │      │   │
│  │   │  git clone ─► OpenCode ─► git commit ─► pytest ─►    │      │   │
│  │   │              git diff ─► git push                     │      │   │
│  │   │                                                       │      │   │
│  │   │  [Code Interpreter + Node.js + Git + Python]          │      │   │
│  │   └──────────────────────────────────────────────────────┘      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

The sandbox owns clone and all git operations; there is no file upload or download between host and sandbox.

### 2.3 Sandbox-Native Pipeline Flow

```
PLANNING STAGE (ephemeral sandbox #1)
======================================
  Sandbox:  git clone --depth 1 <repo>
            run opencode (plan generation; CLI pre-installed in image)
  Host:     extract result.json via sandbox.files.read_file()
            store plan artifacts
            destroy sandbox
            
WAITING_FOR_APPROVAL
======================================
  Nothing running. No sandbox. No host workspace.
  Artifacts (plans, input_spec) live in artifact store.
  
APPLY → VERIFY → PACKAGE → DRAFT_PR (long-lived sandbox #2)
======================================
  Sandbox:  git clone <repo>          # full clone (needed for push)
            git config user.name/email
            git add -A && git commit   # checkpoint
            run opencode (code application; CLI pre-installed in image)
            plan-apply guard (git diff --stat, git diff --name-only)
            git add -A && git commit
            pip install / npm install   # project deps
            pytest / ruff / npm test    # verification
            git diff HEAD~1            # generate diff
            git checkout -b augment/<branch>
            git push origin <branch>
  Host:     extract diff + PR metadata via sandbox.files.read_file()
            destroy sandbox
            bitbucket_client.create_draft_pull_request()  # HTTP only
```

**Design rationale:** Clone inside the sandbox avoids any host↔sandbox file transfer: no upload of workspace files, no sync-back of changes. The sandbox has a real git repo (including `.git`), so all git operations stay inside the sandbox. Between planning and approval nothing runs and no workspace is kept on the host; after approval a new sandbox does a fresh clone. Shallow clone for planning (5–15s); full clone for apply (15–45s) so push works.

**Security: Git credentials in sandbox**

The sandbox already receives LLM API keys (Anthropic, OpenAI) which can incur real costs. Git credentials (Bitbucket app password) carry the same or lower risk:
- Sandboxes are ephemeral — destroyed after job
- Credentials are env vars, destroyed with sandbox
- `async with sandbox:` context manager ensures cleanup
- Network policy limits outbound to `bitbucket.org` and LLM APIs only
- This is exactly what every CI/CD system does (GitHub Actions, GitLab CI)

---

## 3. Component Design

### 3.1 SandboxClient (Shared Infrastructure)

**Purpose:** Centralized OpenSandbox connection management, sandbox tracking, and orphan cleanup.

```python
# src/sandbox_client.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from opensandbox.sandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.manager import SandboxManager
from opensandbox.models.sandboxes import (
    NetworkPolicy, NetworkRule, SandboxFilter,
)
from opensandbox.exceptions import SandboxException

logger = logging.getLogger(__name__)


class SandboxClientError(Exception):
    """Base exception for sandbox client errors"""
    pass

class SandboxUnavailableError(SandboxClientError):
    """OpenSandbox server is unreachable"""
    pass

class SandboxTimeoutError(SandboxClientError):
    """Sandbox operation timed out"""
    pass

class SandboxResultError(SandboxClientError):
    """Result extraction failed"""
    pass

class SandboxGitError(SandboxClientError):
    """Git operation inside sandbox failed"""
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
    def config(self) -> ConnectionConfig:
        return self._config
    
    async def is_available(self) -> bool:
        """Health check against OpenSandbox server"""
        try:
            async with await SandboxManager.create(
                connection_config=self._config
            ) as manager:
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
        network_policy: Optional[NetworkPolicy] = None,
        entrypoint: Optional[List[str]] = None,
    ) -> Sandbox:
        """Create a sandbox with semaphore-gated concurrency"""
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
                f"Failed to create sandbox: [{e.error.code}] {e.error.message}"
            ) from e
        except Exception as e:
            self._semaphore.release()
            raise SandboxUnavailableError(f"Failed to create sandbox: {e}") from e
    
    def release_sandbox(self, job_id: str) -> None:
        """Release semaphore and remove tracking entry"""
        self._active_sandboxes.pop(job_id, None)
        self._semaphore.release()
    
    async def cleanup_orphaned_sandboxes(self, max_age_minutes: int = 30) -> int:
        """Kill sandboxes older than max_age that aren't tracked"""
        cleaned = 0
        try:
            async with await SandboxManager.create(
                connection_config=self._config
            ) as manager:
                result = await manager.list_sandbox_infos(
                    SandboxFilter(states=["RUNNING", "PAUSED"])
                )
                tracked_ids = set(self._active_sandboxes.values())
                for info in result.sandbox_infos:
                    if info.id not in tracked_ids:
                        age_minutes = (
                            datetime.utcnow() - info.created_at
                        ).total_seconds() / 60
                        if age_minutes > max_age_minutes:
                            await manager.kill_sandbox(info.id)
                            cleaned += 1
        except Exception as e:
            logger.warning(f"Orphan cleanup failed: {e}")
        return cleaned
    
    async def close(self) -> None:
        """Close shared transport"""
        await self._transport.aclose()
```

### 3.2 SandboxGitOps (Git Operations via Shell)

**Purpose:** Execute git operations inside a sandbox via `sandbox.commands.run()`. Replaces GitPython-based `CodeApplier`, `PackageService`, and `DraftPRCreator` git logic.

```python
# src/sandbox_git_ops.py
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, quote

from opensandbox.sandbox import Sandbox

from .sandbox_client import SandboxGitError

logger = logging.getLogger(__name__)


class SandboxGitOps:
    """
    Git operations executed inside a sandbox via shell commands.
    
    Replaces GitPython-based operations in CodeApplier, PackageService,
    and DraftPRCreator with sandbox-native shell commands.
    
    All methods are stateless — they take a sandbox and repo path.
    """
    
    def __init__(self, sandbox: Sandbox, repo_path: str = "/workspace/repo"):
        self.sandbox = sandbox
        self.repo_path = repo_path
    
    async def _run(self, cmd: str, check: bool = True) -> Tuple[int, str, str]:
        """Run a command in the sandbox, return (exit_code, stdout, stderr)"""
        result = await self.sandbox.commands.run(f"cd {self.repo_path} && {cmd}")
        stdout = "".join(msg.text for msg in result.logs.stdout) if result.logs.stdout else ""
        stderr = "".join(msg.text for msg in result.logs.stderr) if result.logs.stderr else ""
        if check and result.exit_code != 0:
            raise SandboxGitError(
                f"Command failed (exit {result.exit_code}): {cmd}\n{stderr}"
            )
        return result.exit_code, stdout.strip(), stderr.strip()
    
    # --- Clone ---
    
    async def clone(
        self,
        url: str,
        branch: Optional[str] = None,
        shallow: bool = False,
        git_username: Optional[str] = None,
        git_password: Optional[str] = None,
    ) -> None:
        """Clone a repository into the sandbox"""
        auth_url = self._add_auth_to_url(url, git_username, git_password)
        
        parts = ["git clone"]
        if shallow:
            parts.append("--depth 1")
        if branch:
            parts.append(f"--branch {branch}")
        parts.append(f'"{auth_url}" {self.repo_path}')
        
        await self._run(" ".join(parts))
        
        # Configure git user for commits
        await self._run('git config user.name "Augment Bot"')
        await self._run('git config user.email "augment@automated.local"')
    
    def _add_auth_to_url(
        self, url: str,
        username: Optional[str], password: Optional[str],
    ) -> str:
        """Inject credentials into HTTPS URL"""
        if not username or not password:
            return url
        if url.startswith("https://"):
            parsed = urlparse(url)
            user_enc = quote(username, safe="")
            pass_enc = quote(password, safe="")
            return f"https://{user_enc}:{pass_enc}@{parsed.netloc}{parsed.path}"
        return url  # SSH uses keys
    
    # --- Transaction safety ---
    
    async def check_repo_state(self) -> None:
        """Reject problematic git states before APPLY"""
        exit_code, _, _ = await self._run("git symbolic-ref HEAD", check=False)
        if exit_code != 0:
            raise SandboxGitError("Repository is in detached HEAD state")
        
        exit_code, unmerged, _ = await self._run("git ls-files --unmerged", check=False)
        if unmerged.strip():
            raise SandboxGitError("Repository has merge conflicts")
    
    async def create_checkpoint(self) -> str:
        """Create checkpoint commit, return its SHA"""
        _, dirty, _ = await self._run("git status --porcelain", check=False)
        if dirty.strip():
            logger.warning(f"Uncommitted changes before APPLY: {dirty[:100]}")
            await self._run("git add -A")
            await self._run('git commit -m "Checkpoint before APPLY" --allow-empty')
        
        _, sha, _ = await self._run("git rev-parse HEAD")
        logger.info(f"Git checkpoint: {sha[:8]}")
        return sha
    
    async def rollback_to(self, sha: str) -> None:
        """Hard reset to checkpoint SHA"""
        try:
            await self._run(f"git reset --hard {sha}")
            logger.info(f"Rolled back to {sha[:8]}")
        except SandboxGitError as e:
            raise SandboxGitError(f"Rollback failed: {e}")
    
    # --- Change detection ---
    
    async def get_changed_files(self) -> List[str]:
        """Get list of files changed since last commit"""
        _, output, _ = await self._run("git diff --name-only HEAD", check=False)
        if not output.strip():
            return []
        return sorted(set(f.strip() for f in output.split("\n") if f.strip()))
    
    async def get_loc_delta(self) -> int:
        """Calculate lines added minus lines removed"""
        _, output, _ = await self._run(
            "git diff --numstat HEAD | awk '{added+=$1; removed+=$2} END {print added-removed}'",
            check=False,
        )
        try:
            return int(output.strip())
        except (ValueError, TypeError):
            return 0
    
    async def get_diff(self, cached: bool = False) -> str:
        """Get git diff output"""
        flag = "--cached " if cached else ""
        _, diff, _ = await self._run(f"git diff {flag}HEAD", check=False)
        return diff
    
    async def get_diff_stat(self) -> str:
        """Get diff stat for PR description"""
        _, stat, _ = await self._run("git diff --stat HEAD~1", check=False)
        return stat
    
    # --- Staging and committing ---
    
    async def stage_and_commit(self, message: str) -> Optional[str]:
        """Stage all changes and commit. Returns SHA or None if nothing to commit."""
        _, dirty, _ = await self._run("git status --porcelain", check=False)
        if not dirty.strip():
            logger.warning("No changes to commit")
            return None
        
        await self._run("git add -A")
        cached_diff = await self.get_diff(cached=True)
        await self._run(f'git commit -m "{message}"')
        _, sha, _ = await self._run("git rev-parse HEAD")
        return sha
    
    # --- Branch and push ---
    
    async def create_branch_and_push(
        self,
        branch_name: str,
        destination_branch: str = "main",
    ) -> None:
        """Create feature branch from current HEAD and push"""
        await self._run(f"git checkout -b {branch_name}")
        await self._run(f"git push origin {branch_name} --set-upstream")
        logger.info(f"Pushed branch {branch_name}")
    
    async def get_remote_url(self) -> str:
        """Get origin remote URL"""
        _, url, _ = await self._run("git remote get-url origin")
        return url
    
    async def extract_repo_info(self) -> Tuple[str, str]:
        """Extract (workspace, repo_slug) from remote URL"""
        url = await self.get_remote_url()
        
        # Strip credentials from URL for parsing
        if "@" in url and url.startswith("https://"):
            url = "https://" + url.split("@", 1)[1]
        
        if url.startswith("https://"):
            parts = url.replace("https://bitbucket.org/", "").replace(".git", "").split("/")
        elif url.startswith("git@"):
            parts = url.split(":")[1].replace(".git", "").split("/")
        else:
            raise SandboxGitError(f"Unsupported remote URL: {url}")
        
        if len(parts) != 2:
            raise SandboxGitError(f"Cannot parse workspace/repo from: {url}")
        
        return parts[0], parts[1]
```

### 3.3 SandboxCodeRunner (Replaces OpenCodeRunner)

**Purpose:** Run OpenCode inside OpenSandbox. Clones repo directly — no file upload needed.

```python
# src/sandbox_code_runner.py
import asyncio
import json
import logging
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from opensandbox.sandbox import Sandbox
from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule

from .sandbox_client import (
    SandboxClient, SandboxClientError,
    SandboxResultError, SandboxTimeoutError,
)
from .sandbox_git_ops import SandboxGitOps

logger = logging.getLogger(__name__)


class SandboxCodeRunner:
    """
    Runs OpenCode inside OpenSandbox. The sandbox clones the repo
    directly via git (no file upload). Results are read via
    sandbox.files.read_file(). For code application, changes are
    committed and pushed from inside the sandbox.
    """
    
    def __init__(
        self,
        sandbox_client: SandboxClient,
        image: str = "opensandbox/code-interpreter:v1.0.1",
        timeout_minutes: int = 20,
        max_result_size_bytes: int = 10 * 1024 * 1024,
        result_file: str = "result.json",
        llm_config: Optional[Dict[str, Any]] = None,
        git_username: Optional[str] = None,
        git_password: Optional[str] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ):
        self.sandbox_client = sandbox_client
        self.image = image
        self.timeout = timedelta(minutes=timeout_minutes)
        self.max_result_size_bytes = max_result_size_bytes
        self.result_file = result_file
        self.opencode_version = "latest"
        self.llm_config = llm_config or {}
        self.git_username = git_username
        self.git_password = git_password
        self.network_policy = network_policy or self._default_network_policy()
    
    def set_llm_config(self, llm_config: Dict[str, Any]) -> None:
        self.llm_config = llm_config
    
    def _default_network_policy(self) -> NetworkPolicy:
        """Default egress: package registries + LLM APIs + git hosts"""
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
        """Build environment variables for sandbox (LLM keys + git + runtime)"""
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
        
        for provider, (env_key, value) in provider_env_map.items():
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
        
        Sandbox lifecycle:
        1. Create sandbox (custom image has OpenCode pre-installed)
        2. Shallow clone repo
        3. Run OpenCode
        4. Extract result.json
        5. Destroy sandbox
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
                
                # 1. Shallow clone (fast, only need code for plan generation)
                await git_ops.clone(
                    url=repo_url,
                    branch=branch,
                    shallow=True,
                    git_username=self.git_username,
                    git_password=self.git_password,
                )
                
                self._check_cancelled(cancellation_event)
                
                # 2. Run OpenCode (pre-installed in custom image — no npm install needed)
                await self._run_opencode(sandbox, prompt, "/workspace/repo")
                
                self._check_cancelled(cancellation_event)
                
                # 3. Extract result
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
    
    async def create_apply_sandbox(
        self,
        job_id: str,
        repo_url: str,
        branch: Optional[str],
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Sandbox:
        """
        Create a long-lived sandbox for APPLY → VERIFY → PACKAGE → DRAFT_PR.
        
        Does full clone (not shallow) because we need to push later.
        Returns the sandbox — caller is responsible for lifecycle.
        """
        self._check_cancelled(cancellation_event)
        
        sandbox = await self.sandbox_client.create_sandbox(
            job_id=f"apply-{job_id}",
            image=self.image,
            env=self._build_env(),
            timeout=timedelta(minutes=45),  # longer for full pipeline
            resource={"cpu": "2", "memory": "4Gi"},
            network_policy=self.network_policy,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        )
        
        git_ops = SandboxGitOps(sandbox)
        
        # Full clone (needed for push)
        await git_ops.clone(
            url=repo_url,
            branch=branch,
            shallow=False,
            git_username=self.git_username,
            git_password=self.git_password,
        )
        
        # OpenCode is pre-installed in custom image — no npm install needed
        
        return sandbox
    
    async def run_code_application(
        self,
        sandbox: Sandbox,
        prompt: str,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """Run OpenCode for code application inside existing sandbox"""
        self._check_cancelled(cancellation_event)
        await self._run_opencode(sandbox, prompt, "/workspace/repo")
        self._check_cancelled(cancellation_event)
        return await self._read_result(sandbox, "/workspace/repo")
    
    # --- Backward-compatible execute() for drop-in replacement ---
    
    async def execute(
        self,
        job_id: str,
        workspace_path: Any,  # ignored — sandbox clones internally
        prompt: str,
        job_type: str,
        cancellation_event: Optional[asyncio.Event] = None,
    ) -> Dict[str, Any]:
        """
        Backward-compatible interface matching OpenCodeRunner.execute().
        
        For plan_generation: creates ephemeral sandbox, clones, runs, destroys.
        For code_application: should use create_apply_sandbox() + run_code_application() instead.
        """
        # Extract repo URL from workspace_path (for backward compat, 
        # callers should migrate to explicit methods)
        repo_url = self._infer_repo_url(workspace_path)
        
        return await self.execute_plan_generation(
            job_id=job_id,
            repo_url=repo_url,
            branch=None,
            prompt=prompt,
            cancellation_event=cancellation_event,
        )
    
    # --- Internal helpers ---
    
    async def _install_opencode(self, sandbox: Sandbox) -> None:
        result = await sandbox.commands.run(
            f"npm install -g @opencodeai/cli@{self.opencode_version}"
        )
        if result.exit_code != 0:
            stderr = "".join(msg.text for msg in result.logs.stderr) if result.logs.stderr else ""
            raise SandboxClientError(f"Failed to install OpenCode: {stderr}")
    
    async def _run_opencode(self, sandbox: Sandbox, prompt: str, cwd: str) -> None:
        escaped = prompt.replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
        result = await sandbox.commands.run(
            f'cd {cwd} && opencode run "{escaped}" --format json'
        )
        if result.exit_code != 0:
            stderr = "".join(msg.text for msg in result.logs.stderr) if result.logs.stderr else ""
            logger.warning(f"OpenCode exited with code {result.exit_code}: {stderr[:200]}")
    
    async def _read_result(self, sandbox: Sandbox, workspace: str) -> Dict[str, Any]:
        """Download and validate result.json"""
        try:
            content = await sandbox.files.read_file(f"{workspace}/{self.result_file}")
        except Exception:
            raise SandboxResultError(
                f"OpenCode did not produce {self.result_file}"
            )
        
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
        """Handle markdown-wrapped JSON (matches OpenCodeRunner behavior)"""
        if content.startswith("{") or content.startswith("["):
            return content
        match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', content)
        return match.group(1).strip() if match else content
    
    def _check_cancelled(self, event: Optional[asyncio.Event]) -> None:
        if event and event.is_set():
            raise asyncio.CancelledError("Job cancellation requested")
    
    async def _safe_kill(self, sandbox: Sandbox) -> None:
        try:
            await sandbox.kill()
        except Exception:
            pass
    
    def _infer_repo_url(self, workspace_path: Any) -> str:
        """Infer repo URL from workspace path (backward compat)"""
        workspace = Path(str(workspace_path))
        for child in workspace.iterdir():
            if child.is_dir() and (child / ".git").exists():
                from git import Repo
                repo = Repo(child)
                return repo.remotes.origin.url
        raise SandboxClientError(f"No git repo found in {workspace_path}")
```

### 3.4 SandboxVerifier (Replaces Verifier)

**Purpose:** Run verification commands inside the same sandbox that already has the cloned and modified repo from the APPLY step (no separate upload).

```python
# src/sandbox_verifier.py
import asyncio
import logging
from typing import Any, Dict, List, Optional

from opensandbox.sandbox import Sandbox

from .sandbox_client import SandboxClientError

logger = logging.getLogger(__name__)


class SandboxVerifier:
    """
    Runs verification commands inside an existing sandbox that
    already has the cloned and modified repo from the APPLY stage.
    """
    
    def __init__(
        self,
        test_command: Optional[str] = None,
        lint_command: Optional[str] = None,
        build_command: Optional[str] = None,
        security_scan_command: Optional[str] = None,
        setup_commands: Optional[List[str]] = None,
        language: str = "python",
    ):
        self.test_command = test_command
        self.lint_command = lint_command
        self.build_command = build_command
        self.security_scan_command = security_scan_command
        self.setup_commands = setup_commands or self._default_setup(language)

    def _default_setup(self, language: str) -> List[str]:
        return {
            "python": [
                "pip install -r requirements.txt 2>/dev/null || true",
                "pip install pytest ruff 2>/dev/null || true",
            ],
            "node": ["npm install 2>/dev/null || true"],
            "java": ["mvn dependency:resolve 2>/dev/null || true"],
            "go": ["go mod download 2>/dev/null || true"],
        }.get(language, [])
    
    async def verify(
        self,
        sandbox: Sandbox,
        repo_path: str = "/workspace/repo",
        plan_spec: Any = None,
        repos: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Run verification in the existing sandbox.
        
        Args:
            sandbox: The sandbox that already has the repo (from APPLY stage)
            repo_path: Path to repo inside sandbox
            plan_spec: Unused (reserved for future plan-aware verification)
            repos: Unused (repo already cloned in sandbox)
        """
        if not any([self.test_command, self.lint_command, self.build_command, self.security_scan_command]):
            return {
                "passed": True,
                "test_results": None,
                "lint_results": None,
                "build_results": None,
                "security_scan_results": None,
                "summary": "No verification commands configured",
            }
        
        # Install project dependencies (sequential — must complete first)
        for cmd in self.setup_commands:
            await sandbox.commands.run(f"cd {repo_path} && {cmd}")
        
        # Run verification commands in PARALLEL
        # Test, lint, build, and security_scan don't conflict — safe to run concurrently
        tasks = {}
        for key, command, label in [
            ("test_results", self.test_command, "test"),
            ("lint_results", self.lint_command, "lint"),
            ("build_results", self.build_command, "build"),
            ("security_scan_results", self.security_scan_command, "security_scan"),
        ]:
            if command:
                tasks[key] = self._run_command(sandbox, repo_path, command, label)
        
        results = {"test_results": None, "lint_results": None, "build_results": None, "security_scan_results": None}
        
        if tasks:
            gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), gathered):
                if isinstance(result, Exception):
                    results[key] = {"stdout": "", "stderr": str(result), "exit_code": -1}
                else:
                    results[key] = result
        
        results["passed"] = all(
            r is None or r["exit_code"] == 0
            for r in [results["test_results"], results["lint_results"], results["build_results"], results["security_scan_results"]]
        )
        results["summary"] = self._generate_summary(results)
        return results
    
    async def _run_command(
        self, sandbox: Sandbox, repo_path: str, command: str, label: str,
    ) -> Dict[str, Any]:
        try:
            result = await sandbox.commands.run(f"cd {repo_path} && {command}")
            stdout = "".join(msg.text for msg in result.logs.stdout) if result.logs.stdout else ""
            stderr = "".join(msg.text for msg in result.logs.stderr) if result.logs.stderr else ""
            return {"stdout": stdout, "stderr": stderr, "exit_code": result.exit_code}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}
    
    def _generate_summary(self, results: Dict[str, Any]) -> str:
        parts = []
        for key, label in [
            ("test_results", "Tests"),
            ("lint_results", "Lint"),
            ("build_results", "Build"),
            ("security_scan_results", "Security scan"),
        ]:
            r = results.get(key)
            if r is None:
                continue
            status = "PASSED" if r["exit_code"] == 0 else f"FAILED (exit code {r['exit_code']})"
            parts.append(f"{label}: {status}")
        return " | ".join(parts) if parts else "No verification commands configured"
```

### 3.5 Sandbox Pipeline Orchestrator

**Purpose:** Coordinate the APPLY → VERIFY → PACKAGE → DRAFT_PR stages in a single long-lived sandbox.

```python
# src/sandbox_pipeline.py
import logging
from typing import Any, Dict, List, Optional

from opensandbox.sandbox import Sandbox

from .sandbox_client import SandboxClient, SandboxGitError, SandboxClientError
from .sandbox_git_ops import SandboxGitOps
from .sandbox_code_runner import SandboxCodeRunner
from .sandbox_verifier import SandboxVerifier
from .draft_pr_models import PlanSpec, PlanVersion
from .bitbucket_client import BitbucketClient
from .artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


class SandboxPipelineRunner:
    """
    Runs APPLY → VERIFY → PACKAGE → DRAFT_PR inside a single sandbox.
    
    The sandbox owns the full lifecycle:
    - git clone (full, for push)
    - OpenCode execution (code application)
    - git transaction safety (checkpoint, rollback)
    - plan-apply guard
    - verification (test, lint, build)
    - packaging (diff generation)
    - branch creation and push
    
    The host only:
    - Creates/destroys the sandbox
    - Reads artifacts from sandbox (diff, metadata)
    - Makes Bitbucket API call to create the PR
    """
    
    def __init__(
        self,
        sandbox_runner: SandboxCodeRunner,
        sandbox_verifier: SandboxVerifier,
        bitbucket_client: Optional[BitbucketClient],
        artifact_store: ArtifactStore,
    ):
        self.runner = sandbox_runner
        self.verifier = sandbox_verifier
        self.bitbucket_client = bitbucket_client
        self.artifact_store = artifact_store
    
    async def execute_apply_to_pr(
        self,
        job_id: str,
        approved_plan: PlanVersion,
        repo_url: str,
        branch: Optional[str],
        story_key: Optional[str] = None,
        destination_branch: str = "main",
        cancellation_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute APPLY → VERIFY → PACKAGE → DRAFT_PR in one sandbox.
        
        Returns dict with stage results for each step.
        """
        sandbox = await self.runner.create_apply_sandbox(
            job_id=job_id,
            repo_url=repo_url,
            branch=branch,
            cancellation_event=cancellation_event,
        )
        
        try:
            async with sandbox:
                git_ops = SandboxGitOps(sandbox)
                
                # === APPLY ===
                apply_results = await self._apply(
                    sandbox, git_ops, approved_plan, job_id, cancellation_event,
                )
                self.artifact_store.store_artifact(
                    job_id, "git_diff", apply_results.get("git_diff", ""),
                )
                
                if not apply_results.get("commit_hash"):
                    return {"stage": "FAILED", "error": "No changes produced by OpenCode"}
                
                # === VERIFY ===
                verification_results = await self.verifier.verify(sandbox)
                self.artifact_store.store_artifact(job_id, "validation_logs", verification_results)
                
                if not verification_results.get("passed"):
                    return {
                        "stage": "FAILED",
                        "error": "Verification failed",
                        "apply_results": apply_results,
                        "verification_results": verification_results,
                    }
                
                # === PACKAGE ===
                diff = await git_ops.get_diff_stat()
                changed_files = await git_ops.get_changed_files()
                pr_metadata = self._generate_pr_metadata(
                    approved_plan, verification_results, changed_files,
                )
                self.artifact_store.store_artifact(job_id, "pr_metadata", pr_metadata)
                
                # === DRAFT_PR (git part: branch + push) ===
                branch_name = self._generate_branch_name(
                    job_id, story_key, approved_plan,
                )
                await git_ops.create_branch_and_push(
                    branch_name, destination_branch,
                )
                workspace, repo_slug = await git_ops.extract_repo_info()
                
                await sandbox.kill()
            
            # === DRAFT_PR (API part: create PR on host) ===
            pr_results = self._create_pr_via_api(
                workspace, repo_slug, branch_name,
                destination_branch, pr_metadata, story_key,
            )
            
            self.artifact_store.store_artifact(job_id, "pr_metadata", {
                **pr_metadata, **pr_results,
            })
            
            return {
                "stage": "COMPLETED",
                "approved_plan_hash": approved_plan.plan_hash,
                "apply_results": apply_results,
                "verification_results": verification_results,
                "pr_results": pr_results,
            }
            
        except Exception as e:
            try:
                await sandbox.kill()
            except Exception:
                pass
            raise
        finally:
            self.runner.sandbox_client.release_sandbox(f"apply-{job_id}")
    
    async def _apply(
        self,
        sandbox: Sandbox,
        git_ops: SandboxGitOps,
        plan_version: PlanVersion,
        job_id: str,
        cancellation_event: Optional[Any],
    ) -> Dict[str, Any]:
        """APPLY stage: OpenCode execution with git transaction safety"""
        plan_spec = plan_version.plan_spec
        
        # Check repo state
        await git_ops.check_repo_state()
        checkpoint = await git_ops.create_checkpoint()
        
        try:
            # Run OpenCode
            prompt = self._build_apply_prompt(plan_spec)
            await self.runner.run_code_application(
                sandbox, prompt, cancellation_event,
            )
            
            # Get changes
            changed_files = await git_ops.get_changed_files()
            loc_delta = await git_ops.get_loc_delta()
            
            # Plan-apply guard
            self._verify_plan_apply_guard(plan_spec, changed_files, loc_delta)
            
            # Commit
            commit_msg = f"Apply plan v{plan_version.version}\n\n{plan_spec.summary}"
            commit_hash = await git_ops.stage_and_commit(commit_msg)
            git_diff = await git_ops.get_diff(cached=False)
            
            return {
                "changed_files": changed_files,
                "loc_delta": loc_delta,
                "commit_hash": commit_hash,
                "git_diff": git_diff,
            }
            
        except Exception as e:
            logger.error(f"APPLY failed, rolling back: {e}")
            await git_ops.rollback_to(checkpoint)
            raise
    
    def _verify_plan_apply_guard(
        self, plan_spec: PlanSpec, changed_files: List[str], loc_delta: int,
    ) -> None:
        """Same logic as CodeApplier._verify_plan_apply_guard"""
        violations = []
        planned_files = {f.get("path") for f in plan_spec.scope.get("files", [])}
        actual_files = set(changed_files)
        
        if not planned_files and actual_files:
            violations.append(
                f"Plan specifies no files, but {len(actual_files)} changed: {actual_files}"
            )
        
        unexpected = actual_files - planned_files
        if unexpected:
            violations.append(f"Unexpected files changed: {unexpected}")
        
        missing = planned_files - actual_files
        if missing:
            logger.warning(f"Planned but not changed: {missing}")
        
        if abs(loc_delta) > 1000:
            violations.append(f"LOC delta very large: {loc_delta}")
        
        if violations:
            from .code_applier import PlanApplyGuardError
            raise PlanApplyGuardError(f"Plan-Apply guard violations: {'; '.join(violations)}")
    
    def _build_apply_prompt(self, plan_spec: PlanSpec) -> str:
        """Same prompt as CodeApplier._build_apply_prompt"""
        files_section = "\n".join(
            f"- {f.get('path')}: {f.get('change', 'modify')}"
            for f in plan_spec.scope.get("files", [])
        )
        return f"""Apply the following plan to the codebase:

**Summary:**
{plan_spec.summary}

**Files to Modify:**
{files_section}

**Implementation Requirements:**
- Follow the plan exactly
- Implement all specified changes
- Maintain code quality and style

**Happy Paths to Implement:**
{chr(10).join(f'- {p}' for p in plan_spec.happy_paths)}

**Edge Cases to Handle:**
{chr(10).join(f'- {c}' for c in plan_spec.edge_cases)}

**Tests to Create/Update:**
{chr(10).join(f'- {t.get("type")}: {t.get("target")}' for t in plan_spec.tests)}

Make the changes and ensure the code compiles and follows best practices.
"""
    
    def _generate_branch_name(
        self, job_id: str, ticket_key: Optional[str], plan_version: PlanVersion,
    ) -> str:
        if ticket_key:
            sanitized = "".join(c for c in ticket_key if c.isalnum() or c in "-_")
            return f"augment/{sanitized or 'ticket'}-{plan_version.plan_hash[:8]}"
        sanitized = "".join(c for c in job_id if c.isalnum() or c == "-")
        return f"augment/{sanitized}"
    
    def _generate_pr_metadata(
        self, plan_version: PlanVersion,
        verification_results: Optional[Dict[str, Any]],
        changed_files: List[str],
    ) -> Dict[str, Any]:
        """Same logic as PackageService._generate_pr_metadata"""
        plan_spec = plan_version.plan_spec
        title = f"Implement: {plan_spec.summary}"
        
        parts = [f"## Summary\n\n{plan_spec.summary}\n", "## Changes\n\n"]
        
        if plan_spec.scope.get("files"):
            parts.append("### Files Modified\n\n")
            for fc in plan_spec.scope.get("files", []):
                parts.append(f"- `{fc.get('path')}` ({fc.get('change', 'modify')})\n")
            parts.append("\n")
        
        if verification_results:
            parts.append("## Verification Results\n\n")
            parts.append(f"{verification_results.get('summary', 'N/A')}\n\n")
            tr = verification_results.get("test_results")
            if tr:
                emoji = "✅" if tr["exit_code"] == 0 else "❌"
                parts.append(f"{emoji} Tests {'passed' if tr['exit_code'] == 0 else 'failed'}\n\n")
        
        return {
            "title": title,
            "description": "".join(parts),
            "labels": ["draft", "automated"],
            "changed_files": changed_files,
            "plan_version": plan_version.version,
            "plan_hash": plan_version.plan_hash[:8],
        }
    
    def _create_pr_via_api(
        self,
        workspace: str,
        repo_slug: str,
        branch_name: str,
        destination_branch: str,
        pr_metadata: Dict[str, Any],
        ticket_key: Optional[str],
    ) -> Dict[str, Any]:
        """Create draft PR via Bitbucket API (HTTP only, no git needed)"""
        if not self.bitbucket_client:
            raise ValueError("Bitbucket client required for DRAFT_PR stage")
        
        pr_data = self.bitbucket_client.create_draft_pull_request(
            workspace=workspace,
            repo_slug=repo_slug,
            title=pr_metadata.get("title", "Draft PR"),
            description=pr_metadata.get("description", ""),
            source_branch=branch_name,
            destination_branch=destination_branch,
            ticket_key=ticket_key,
        )
        
        return {
            "pr_id": pr_data.get("id"),
            "pr_url": pr_data.get("links", {}).get("html", {}).get("href"),
            "branch_name": branch_name,
            "workspace": workspace,
            "repo_slug": repo_slug,
        }
```

### 3.6 Integration into DraftPRPipeline

The existing `DraftPRPipeline` changes minimally. The heavy lifting moves to `SandboxPipelineRunner`:

```python
# Changes to src/draft_pr_pipeline.py

class DraftPRPipeline:
    def __init__(
        self,
        plan_generator: PlanGenerator,
        workspace_manager: WorkspaceManager,        # kept for non-sandbox fallback
        artifact_store: ArtifactStore,
        opencode_runner: Optional[OpenCodeRunner] = None,  # legacy
        sandbox_pipeline: Optional[SandboxPipelineRunner] = None,  # NEW
        sandbox_runner: Optional[SandboxCodeRunner] = None,  # NEW
        llm_client: Optional[LLMClient] = None,
        bitbucket_client: Optional[BitbucketClient] = None,
        yolo_policy: Optional[Dict[str, Any]] = None,
        verification_config: Optional[Dict[str, Any]] = None,
    ):
        ...
    
    async def _execute_from_apply_stage(self, job_id, approved_plan, repos, ...):
        """Delegate to sandbox pipeline runner when enabled"""
        if self.sandbox_pipeline:
            repo_url = repos[0].get("url")
            branch = repos[0].get("branch")
            story_key = self.artifact_store.retrieve_artifact(job_id, "input_spec").get("story_key")
            
            return await self.sandbox_pipeline.execute_apply_to_pr(
                job_id=job_id,
                approved_plan=approved_plan,
                repo_url=repo_url,
                branch=branch,
                story_key=story_key,
                cancellation_event=cancellation_event,
            )
        else:
            # Legacy path: host-based CodeApplier + Verifier + DraftPRCreator
            ...  # existing code unchanged
    
    async def continue_pipeline_after_approval(self, job_id, approved_plan_hash, ...):
        """No longer needs host workspace — sandbox clones fresh"""
        if self.sandbox_pipeline:
            # Retrieve repos from input_spec (stored in artifact store)
            input_spec = self.artifact_store.retrieve_artifact(job_id, "input_spec")
            repos = input_spec.get("repos", [])
            
            # Find approved plan from artifacts (existing logic)
            approved_plan = self._find_approved_plan(job_id, approved_plan_hash)
            
            # No workspace_path needed — sandbox clones internally
            return await self._execute_from_apply_stage(
                job_id=job_id,
                approved_plan=approved_plan,
                repos=repos,
                cancellation_event=cancellation_event,
            )
        else:
            # Legacy path: needs host workspace to still exist
            workspace_path = self.workspace_manager.get_workspace_path(job_id)
            ...  # existing code unchanged
```

### 3.7 Configuration Schema

```yaml
# config.yaml additions

opensandbox:
  enabled: ${OPENSANDBOX_ENABLED:false}
  server:
    domain: ${OPENSANDBOX_DOMAIN:localhost:8080}
    api_key: ${OPENSANDBOX_API_KEY:}
    protocol: ${OPENSANDBOX_PROTOCOL:http}
    max_concurrent: ${OPENSANDBOX_MAX_CONCURRENT:5}
    request_timeout_seconds: 30
  
  defaults:
    image: "opensandbox/code-interpreter:v1.0.1"
    entrypoint: ["/opt/opensandbox/code-interpreter.sh"]
    timeout_minutes: 20
    apply_timeout_minutes: 45    # longer for full APPLY→PR pipeline
    resource:
      cpu: "2"
      memory: "4Gi"
  
  git:
    username: ${GIT_USERNAME:}
    password: ${GIT_PASSWORD:}
    user_name: "Augment Bot"
    user_email: "augment@automated.local"
  
  languages:
    python:
      version: "3.11"
      test_command: "pytest"
      lint_command: "ruff check"
      setup_commands:
        - "pip install -r requirements.txt 2>/dev/null || true"
        - "pip install pytest ruff 2>/dev/null || true"
    java:
      version: "17"
      test_command: "mvn test"
      lint_command: "mvn checkstyle:check"
    node:
      version: "20"
      test_command: "npm test"
      lint_command: "npm run lint"
    go:
      version: "1.24"
      test_command: "go test ./..."
      lint_command: "gofmt -l ."
  
  network_policy:
    default_action: "deny"
    egress:
      # Package registries
      - { action: "allow", target: "pypi.org" }
      - { action: "allow", target: "files.pythonhosted.org" }
      - { action: "allow", target: "registry.npmjs.org" }
      - { action: "allow", target: "proxy.golang.org" }
      # LLM APIs
      - { action: "allow", target: "api.openai.com" }
      - { action: "allow", target: "api.anthropic.com" }
      - { action: "allow", target: "generativelanguage.googleapis.com" }
      - { action: "allow", target: "api.moonshot.cn" }
      # Git hosts
      - { action: "allow", target: "bitbucket.org" }
      - { action: "allow", target: "*.bitbucket.org" }
      - { action: "allow", target: "github.com" }
      - { action: "allow", target: "*.github.com" }
  
  cleanup:
    enabled: true
    max_age_minutes: 30

opencode_auth:
  provider: ${LLM_PROVIDER:anthropic}
  api_keys:
    openai: ${OPENAI_API_KEY:}
    anthropic: ${ANTHROPIC_API_KEY:}
    gemini: ${GEMINI_API_KEY:}
    google: ${GOOGLE_API_KEY:}
    moonshot: ${MOONSHOT_API_KEY:}
  models:
    openai: ${OPENAI_MODEL:gpt-4o}
    anthropic: ${ANTHROPIC_MODEL:claude-sonnet-4}

draft_pr:
  verification:
    test_command: ${DRAFT_PR_TEST_COMMAND:pytest}
    lint_command: ${DRAFT_PR_LINT_COMMAND:ruff check}
    build_command: ${DRAFT_PR_BUILD_COMMAND:}
    security_scan_command: ${DRAFT_PR_SECURITY_SCAN_COMMAND:}  # Optional (e.g. semgrep scan --config auto). Empty = disabled.
    timeout_seconds: ${DRAFT_PR_VERIFY_TIMEOUT:600}
    language: ${DRAFT_PR_LANGUAGE:python}
    setup_commands: []

features:
  use_sandbox: ${USE_SANDBOX:false}
  sandbox_runtime: ${SANDBOX_RUNTIME:docker}
```

---

## 4. Known Bugs to Fix During Integration

| Bug | Location | Fix |
|-----|----------|-----|
| `plan_generation` and `code_application` not in `JOB_TYPE_SCHEMAS` | `src/opencode_schemas.py` | Add schemas or make validation optional |
| `ArtifactStoreError` used but never defined | `src/artifact_store.py` | Define the exception class |
| Worker `cancellation_event=None` for draft PR | `api/workers.py` | Wire Redis cancellation to asyncio.Event |
| `jobs` dict not shared between API/worker processes | `api/dependencies.py` | Store sandbox_id in Redis |

---

## 5. Implementation Phases

### Phase 1: Foundation (Week 1-2)

**Goals:**
- Build custom sandbox image with OpenCode CLI and common tools pre-installed
- Add OpenSandbox SDK dependencies
- Create SandboxClient, SandboxGitOps, and retry infrastructure
- Add configuration and feature flags
- Fix critical bug: unregister ticket job on draft PR completion/failure

**Tasks:**

| Task | File | Description |
|------|------|-------------|
| 1.1 | `images/augment-sandbox/Dockerfile` | Custom image: code-interpreter + OpenCode CLI + pytest + ruff |
| 1.2 | `requirements.txt` | Add `opensandbox>=0.1.0`, `opensandbox-code-interpreter>=1.0.0` |
| 1.3 | `src/sandbox_client.py` | SandboxClient with connection pooling, semaphore, tracking |
| 1.4 | `src/sandbox_git_ops.py` | SandboxGitOps — all git operations via shell commands in sandbox |
| 1.5 | `src/retry.py` | Retry with exponential backoff for transient failures |
| 1.6 | `config.yaml` | Add `opensandbox` configuration section |
| 1.7 | `src/config.py` | Add `get_sandbox_config()` with validation |
| 1.8 | `.env.example` | Add all `OPENSANDBOX_*` env vars |
| 1.9 | `src/opencode_schemas.py` | Fix missing `plan_generation`/`code_application` job types |
| 1.10 | `src/artifact_store.py` | Define `ArtifactStoreError` |
| 1.11 | `api/workers.py` | CRITICAL: Call `unregister_ticket_job(story_key)` in a finally block so retries work |
| 1.12 | `tests/test_sandbox_client.py` | Unit tests |
| 1.13 | `tests/test_sandbox_git_ops.py` | Unit tests for git operations |
| 1.14 | `tests/test_retry.py` | Unit tests for retry logic |

**Acceptance Criteria:**
- Custom image builds and includes `opencode` CLI, `pytest`, `ruff`
- SandboxClient connects to local OpenSandbox server
- SandboxGitOps can clone, commit, diff, push inside sandbox
- Retry logic handles transient failures with backoff
- `unregister_ticket_job` bug is fixed
- Config loads and validates all settings

### Phase 2: SandboxCodeRunner + SandboxVerifier (Week 2-3)

**Goals:**
- Plan generation via sandbox (clone + OpenCode; CLI pre-installed in custom image)
- Verification via sandbox with parallel test, lint, and build
- Wire cancellation from Redis to asyncio.Event

**Tasks:**

| Task | File | Description |
|------|------|-------------|
| 2.1 | `src/sandbox_code_runner.py` | SandboxCodeRunner with clone-in-sandbox (OpenCode pre-baked in image) |
| 2.2 | `src/sandbox_verifier.py` | SandboxVerifier with parallel test/lint/build via `asyncio.gather()` |
| 2.3 | `api/workers.py` | Wire Redis cancellation → asyncio.Event |
| 2.4 | `tests/test_sandbox_code_runner.py` | Unit tests |
| 2.5 | `tests/test_sandbox_verifier.py` | Unit tests (including parallel execution test) |

**Acceptance Criteria:**
- Plan generation: sandbox creates, clones, runs OpenCode (pre-installed), extracts result, destroys
- No npm install step during sandbox execution
- Verification: test, lint, and build run in parallel inside sandbox
- Cancellation kills sandbox within 5 seconds

**Edge Cases Covered:**
- Shallow clone fails (private repo, no credentials) → SandboxGitError
- OpenCode install fails (npm registry unreachable) → SandboxClientError
- No result.json produced → SandboxResultError
- Result wrapped in markdown → extracted correctly
- Result too large → SandboxResultError
- Network policy blocks LLM API → OpenCode fails with clear error
- Empty prompt → OpenCode may produce empty result → handled gracefully

### Phase 3: Sandbox Pipeline Runner (Week 3-4)

**Goals:**
- Full APPLY → VERIFY → PACKAGE → DRAFT_PR in one sandbox
- Git transaction safety (checkpoint + rollback)
- Plan-apply guard
- Branch creation and push from sandbox
- PR creation via Bitbucket API on host

**Tasks:**

| Task | File | Description |
|------|------|-------------|
| 3.1 | `src/sandbox_pipeline.py` | SandboxPipelineRunner |
| 3.2 | `src/draft_pr_pipeline.py` | Integrate SandboxPipelineRunner, keep legacy fallback |
| 3.3 | `api/routes/draft_pr.py` | Update pipeline construction |
| 3.4 | `api/workers.py` | Update worker to construct sandbox pipeline |
| 3.5 | `api/dependencies.py` | Add `get_sandbox_client()` singleton |
| 3.6 | `tests/integration/test_sandbox_pipeline.py` | Full pipeline integration test |

**Acceptance Criteria:**
- Full pipeline: clone → apply → verify → package → push → PR
- Git transaction: rollback on failure
- Plan-apply guard: rejects unexpected file changes
- Approval gap: new sandbox clones fresh (no host workspace dependency)
- Feature flag toggles between sandbox and legacy paths
- Branch pushed from sandbox, PR created via API on host

**Edge Cases Covered:**
- OpenCode produces no changes → pipeline returns FAILED with clear message
- Plan-apply guard violation → rollback to checkpoint, FAILED
- Verification fails → results stored, FAILED
- Push fails (branch exists) → error with branch name for manual cleanup
- PR creation fails after push → partial failure, branch exists but no PR
- Sandbox timeout during long test suite → sandbox auto-killed, FAILED
- Multiple repos in request → only first repo used (current behavior)
- Approval hours later → fresh clone, no stale workspace issues
- Cancel during code application → sandbox killed, checkpoint preserved

### Phase 4: Advanced Features (Week 4-5)

**Goals:**
- Pause/resume for debugging
- Sandbox status API endpoints
- Cross-process sandbox tracking via Redis
- Startup health checks

**Tasks:**

| Task | File | Description |
|------|------|-------------|
| 4.1 | `api/routes/sandbox.py` | Pause/resume/status endpoints |
| 4.2 | `api/routes/__init__.py` | Register sandbox router |
| 4.3 | `api/job_queue.py` | Store sandbox_id in Redis |
| 4.4 | `run_worker.py` | Startup: `is_available()`, `cleanup_orphaned_sandboxes()` |
| 4.5 | `api/models/draft_pr.py` | Add SandboxOptions model |
| 4.6 | Documentation | Update API docs |

### Phase 5: Kubernetes Runtime (Week 5-7)

**Goals:** Deploy OpenSandbox and Augment workers on Kubernetes. The SDK abstracts the runtime; no application code changes needed beyond configuration.

**Done:** Kubernetes / production deployment is documented in [docs/deployment/KUBERNETES.md](deployment/KUBERNETES.md). It covers: running the OpenSandbox server with Kubernetes runtime (per [Alibaba OpenSandbox kubernetes/](https://github.com/alibaba/OpenSandbox/tree/main/kubernetes)); running Augment API and workers on K8s (Deployment); required env (`OPENSANDBOX_DOMAIN`, `REDIS_*`, `SANDBOX_RUNTIME=kubernetes`) and `config.yaml` `features.sandbox_runtime: kubernetes`; and a minimal worker manifest in [opensandbox-augment-worker-deployment.yaml](../deployment/opensandbox-augment-worker-deployment.yaml). `config.yaml` and `.env.example` document `SANDBOX_RUNTIME` (docker vs kubernetes); no app code changes—only config.

### Phase 6: Migration & Cleanup (Week 7-8)

**Done:**
- **6.1** Deprecation warnings added in `OpenCodeRunner`, `Verifier`, `CodeApplier`, `DraftPRCreator` (see `src/opencode_runner.py`, `src/verifier.py`, `src/code_applier.py`, `src/draft_pr_creator.py`).
- **6.2** Migration guide: [docs/MIGRATION_OPENSANDBOX.md](MIGRATION_OPENSANDBOX.md).
- **6.3** Performance: `scripts/benchmark_sandbox.py` for sandbox lifecycle timing; see migration guide § Performance.
- **6.4** `USE_SANDBOX` default set to `true` in `config.yaml` and `.env.example`.
- **6.5** WorkspaceManager usage when sandbox disabled documented in migration guide and AGENTS.md.

**Original task list:**

| Task | Description |
|------|-------------|
| 6.1 | Deprecation warnings on OpenCodeRunner, Verifier, CodeApplier, DraftPRCreator |
| 6.2 | Migration guide |
| 6.3 | Performance benchmarks (sandbox vs Docker) |
| 6.4 | Set `USE_SANDBOX=true` as default |
| 6.5 | WorkspaceManager: only needed for plan generation if sandbox disabled |

---

## 6. API Changes

### New Endpoints

```yaml
POST /sandbox/jobs/{job_id}/pause
POST /sandbox/jobs/{job_id}/resume
GET  /sandbox/jobs/{job_id}/status
```

### Modified Endpoints

```yaml
POST /draft-pr/create
  request:
    sandbox_options:             # NEW (optional)
      pause_on_failure: boolean
      resource: { cpu, memory }
      language: string
      setup_commands: [string]

GET /draft-pr/jobs/{job_id}
  response:
    sandbox_id: string | null    # NEW
    sandbox_status: string | null
```

---

## 7. Testing Strategy

### Unit Tests

```python
# tests/test_sandbox_git_ops.py
class TestSandboxGitOps:
    async def test_clone_with_auth(self, mock_sandbox):
        """Clone injects credentials into HTTPS URL"""
    
    async def test_clone_ssh_url_unchanged(self, mock_sandbox):
        """SSH URLs pass through without modification"""
    
    async def test_checkpoint_and_rollback(self, mock_sandbox):
        """Checkpoint creates commit, rollback resets to it"""
    
    async def test_stage_and_commit(self, mock_sandbox):
        """Stages all changes and commits"""
    
    async def test_create_branch_and_push(self, mock_sandbox):
        """Creates branch from HEAD and pushes"""
    
    async def test_extract_repo_info_https(self, mock_sandbox):
        """Parses workspace/repo from HTTPS remote"""
    
    async def test_extract_repo_info_ssh(self, mock_sandbox):
        """Parses workspace/repo from SSH remote"""
    
    async def test_extract_repo_info_with_credentials_in_url(self, mock_sandbox):
        """Strips credentials before parsing"""

# tests/test_sandbox_pipeline.py
class TestSandboxPipelineRunner:
    async def test_full_apply_to_pr(self, mock_sandbox):
        """Full APPLY → VERIFY → PACKAGE → DRAFT_PR"""
    
    async def test_apply_failure_rollback(self, mock_sandbox):
        """On OpenCode failure, git resets to checkpoint"""
    
    async def test_plan_apply_guard_unexpected_files(self):
        """Guard rejects files not in plan scope"""
    
    async def test_verification_failure_stops_pipeline(self):
        """Verification failure → FAILED, no push"""
    
    async def test_push_failure_partial(self):
        """Push fails → branch may exist, error reported"""
    
    async def test_no_changes_produced(self):
        """OpenCode changes nothing → FAILED with message"""
```

### Integration Tests

```python
# tests/integration/test_sandbox_end_to_end.py
@pytest.mark.integration
class TestSandboxEndToEnd:
    async def test_plan_generation_via_sandbox(self):
        """Plan generation: create sandbox → clone → OpenCode → destroy"""
    
    async def test_full_pipeline_yolo_mode(self):
        """YOLO: plan → auto-approve → apply → verify → push → PR"""
    
    async def test_approval_gap_fresh_clone(self):
        """After approval, new sandbox clones fresh"""
    
    async def test_cancel_during_apply(self):
        """Cancel kills sandbox, no orphans left"""
```

---

## 8. Performance & Resilience Improvements

### 8.1 Custom Image: Pre-Bake OpenCode CLI (saves 30-90s per sandbox)

**Problem:** Installing `npm install -g @opencodeai/cli` inside every sandbox costs 30-90 seconds per sandbox, and the full pipeline uses two sandboxes (planning and apply). Doing this on every run is unnecessary.

**Solution:** Build a custom image based on the code-interpreter with OpenCode pre-installed:

```dockerfile
# images/augment-sandbox/Dockerfile
FROM opensandbox/code-interpreter:v1.0.1

# Pre-install OpenCode CLI (saves ~30-90s per sandbox)
RUN npm install -g @opencodeai/cli@latest

# Pre-install common verification tools
RUN pip install pytest ruff

# Pre-install common build tools
RUN pip install build setuptools wheel
```

**Config change:**
```yaml
opensandbox:
  defaults:
    image: "augment/sandbox:latest"   # custom image, not base code-interpreter
    # entrypoint stays the same: ["/opt/opensandbox/code-interpreter.sh"]
```

**Impact:**
- Eliminates `_install_opencode()` call entirely from `SandboxCodeRunner`
- Saves 30-90s per sandbox creation (60-180s per full pipeline)
- Pre-installed `pytest` and `ruff` reduce `setup_commands` time in verifier
- Image rebuild needed only when OpenCode version changes (rare)

**Build pipeline:**
```bash
# CI/CD: rebuild when OpenCode or base image updates
docker build -t augment/sandbox:latest -f images/augment-sandbox/Dockerfile .
docker push augment/sandbox:latest  # or use local registry
```

**When:** Phase 1 (Foundation). The image build is a prerequisite for sandbox execution.

### 8.2 Parallel Verification (saves ~50% of verify time)

**Problem:** SandboxVerifier runs test, lint, and build sequentially. These commands don't conflict — they read the same files but don't write to each other's outputs.

**Solution:** Run all three commands in parallel using `asyncio.gather()`:

```python
# In SandboxVerifier.verify():
async def verify(self, sandbox, repo_path="/workspace/repo", ...):
    # Setup (sequential — must complete before verification)
    for cmd in self.setup_commands:
        await sandbox.commands.run(f"cd {repo_path} && {cmd}")
    
    # Verification (parallel — no conflicts)
    tasks = {}
    for key, command, label in [
        ("test_results", self.test_command, "test"),
        ("lint_results", self.lint_command, "lint"),
        ("build_results", self.build_command, "build"),
        ("security_scan_results", self.security_scan_command, "security_scan"),
    ]:
        if command:
            tasks[key] = self._run_command(sandbox, repo_path, command, label)
    
    if tasks:
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        results = dict(zip(tasks.keys(), gathered))
        # Handle exceptions in results
        for key, result in results.items():
            if isinstance(result, Exception):
                results[key] = {"stdout": "", "stderr": str(result), "exit_code": -1}
    else:
        results = {}
    
    # Fill missing keys
    for key in ["test_results", "lint_results", "build_results", "security_scan_results"]:
        if key not in results:
            results[key] = None
    
    results["passed"] = all(
        r is None or r["exit_code"] == 0
        for r in [results["test_results"], results["lint_results"], results["build_results"], results["security_scan_results"]]
    )
    results["summary"] = self._generate_summary(results)
    return results
```

**Impact:**
- If test takes 60s, lint takes 10s, build takes 20s:
  - Sequential: 90s
  - Parallel: 60s (limited by longest command)
  - Savings: ~33%
- Typical savings: 30-50% of verification time
- No resource conflict: sandbox has 2 CPU / 4Gi — enough for concurrent test/lint/build

**Caveat:** If the project has resource-heavy tests that consume all CPU/memory, parallel lint may slow everything down. Add a config flag `parallel_verification: true` (default true) to allow disabling.

**When:** Phase 2 (SandboxVerifier implementation).

### 8.3 Retry with Backoff + Critical Bug Fixes (resilience)

**Problem:** The pipeline has **zero retry logic**. A single transient failure (network blip, LLM rate limit, sandbox OOM) kills the entire job. Additionally, there's a critical bug: `process_draft_pr_worker` never calls `unregister_ticket_job()`, permanently blocking retries for the same story.

#### 8.3.1 Critical Bug: `unregister_ticket_job` Never Called

In `api/workers.py`, `process_draft_pr_worker` registers the ticket job at creation but never unregisters on completion or failure:

```python
# Current: ticket_jobs[story_key] = job_id is set at enqueue time
# But NEVER cleared. After the job finishes (success or failure),
# any retry for the same story_key returns 409 Conflict forever.
```

**Fix:**
```python
# In process_draft_pr_worker, add finally block:
try:
    results = await pipeline.execute_pipeline(...)
    # ... update job status ...
finally:
    # Always unregister, regardless of success/failure/exception
    from api.dependencies import unregister_ticket_job
    unregister_ticket_job(story_key)
```

**When:** Phase 1, before any sandbox work.

#### 8.3.2 Retry Wrapper for Transient Failures

Add a generic retry decorator for sandbox operations:

```python
# src/retry.py
import asyncio
import logging
from typing import Type, Tuple

logger = logging.getLogger(__name__)

TRANSIENT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    # Sandbox transient failures
    SandboxTimeoutError,
    SandboxUnavailableError,
    # Network
    ConnectionError,
    TimeoutError,
    # httpx
    # httpx.ConnectError, httpx.ReadTimeout (if httpx used)
)

async def retry_with_backoff(
    coro_factory,
    max_retries: int = 3,
    initial_backoff: float = 2.0,
    max_backoff: float = 30.0,
    backoff_multiplier: float = 2.0,
    transient_exceptions: Tuple[Type[Exception], ...] = TRANSIENT_EXCEPTIONS,
    cancellation_event=None,
):
    """
    Retry a coroutine with exponential backoff on transient failures.
    
    Args:
        coro_factory: Callable that returns a new coroutine each call
        max_retries: Maximum retry attempts (0 = no retries)
        initial_backoff: Initial wait in seconds
        cancellation_event: If set, abort retries
    """
    backoff = initial_backoff
    last_exception = None
    
    for attempt in range(max_retries + 1):
        if cancellation_event and cancellation_event.is_set():
            raise asyncio.CancelledError("Cancelled during retry")
        
        try:
            return await coro_factory()
        except transient_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    f"Transient failure (attempt {attempt + 1}/{max_retries + 1}), "
                    f"retrying in {backoff:.1f}s: {e}"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * backoff_multiplier, max_backoff)
            else:
                logger.error(
                    f"All {max_retries + 1} attempts failed: {e}"
                )
                raise
        except Exception:
            raise  # Non-transient exceptions fail immediately
    
    raise last_exception  # Should not reach here
```

**Usage in SandboxPipelineRunner:**
```python
# Retry OpenCode execution (transient LLM/network failures)
result = await retry_with_backoff(
    lambda: self.runner.run_code_application(sandbox, prompt, cancellation_event),
    max_retries=2,
    initial_backoff=5.0,
)

# Retry git push (transient network failures)
await retry_with_backoff(
    lambda: git_ops.create_branch_and_push(branch_name, destination_branch),
    max_retries=2,
    initial_backoff=3.0,
)
```

**What gets retried (transient) vs what doesn't (permanent):**

| Failure | Transient? | Retry? |
|---------|-----------|--------|
| Sandbox creation timeout | Yes | Yes |
| Network blip during OpenCode | Yes | Yes |
| LLM rate limit | Yes | Yes (with backoff) |
| `git push` network timeout | Yes | Yes |
| Plan-apply guard violation | No | No (permanent) |
| Schema validation failure | No | No |
| `result.json` not found | No | No (LLM didn't produce it) |
| OpenCode exits with error | Maybe | No (LLM logic error, not transient) |

**When:** Add retry module in Phase 1; use it in SandboxPipelineRunner in Phase 3.

#### 8.3.3 Overall Job Timeout

The current `_execute_internal` in OpenCodeRunner has no overall timeout (just per-operation timeouts). The sandbox pipeline needs one:

```python
# In SandboxPipelineRunner.execute_apply_to_pr():
try:
    return await asyncio.wait_for(
        self._execute_apply_to_pr_internal(...),
        timeout=overall_timeout_seconds,  # e.g., 2700s (45 min)
    )
except asyncio.TimeoutError:
    raise SandboxTimeoutError(f"Pipeline timed out after {overall_timeout_seconds}s")
```

**When:** Phase 3 (SandboxPipelineRunner implementation).

### 8.4 Summary: Impact on Timeline

These three improvements add minimal implementation time but dramatically change the quality:

| Improvement | Implementation Time | Time Saved Per Job | Resilience Impact |
|-------------|--------------------|--------------------|-------------------|
| Custom image | ~2 hours (Dockerfile + CI) | 60-180s | Fewer moving parts |
| Parallel verification | ~1 hour (refactor verify loop) | 30-50% of verify | None |
| Retry + bug fixes | ~4 hours | 0 (but prevents re-runs) | Critical |
| Overall timeout | ~30 min | 0 | Prevents hung jobs |
| **Total** | **~8 hours** | **~2-4 min per job** | **From zero to production-grade** |

---

## 9. Deployment Guide

### Local Development

```bash
# 1. Install and start OpenSandbox
uv pip install opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
docker pull opensandbox/code-interpreter:v1.0.1
opensandbox-server

# 2. Configure Augment
cat >> .env << 'EOF'
OPENSANDBOX_ENABLED=true
OPENSANDBOX_DOMAIN=localhost:8080
USE_SANDBOX=true
EOF

# 3. Install SDK
pip install opensandbox opensandbox-code-interpreter

# 4. Start Augment
python api_server.py
python run_worker.py
```

---

## 10. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| OpenSandbox server unavailable | Low | High | Feature flag fallback to legacy Docker path |
| Git credentials in sandbox | Low | Medium | Ephemeral sandbox, network policy, same model as CI/CD |
| Clone slower than bind mount | Medium | Low | Shallow clone for planning (5-15s), full clone for apply (15-45s) |
| SDK breaking changes (v0.x) | Medium | High | Pin version, integration tests |
| Network policy blocks clone/push | Medium | Medium | bitbucket.org in default egress rules |
| Shallow clone push issues | Low | Medium | Full clone for apply sandbox (push needs history) |
| Long approval gap + sandbox timeout | Low | Low | No sandbox during gap (stateless, re-clone after approval) |

---

## 11. Success Metrics

| Metric | Before (Docker) | Target (Sandbox) |
|--------|-----------------|-------------------|
| Container/sandbox startup | ~5s | < 15s |
| Workspace setup | ~5s (clone) + bind mount | ~10s (clone inside sandbox) |
| OpenCode install | 30-90s per container | 0s (pre-baked in custom image) |
| Verification time | Sequential (T+L+B) | Parallel: max(T,L,B) — ~50% faster |
| Verification isolation | Host subprocess | Full sandbox isolation |
| Concurrent jobs | ~2 (semaphore) | ~20 (OpenSandbox) |
| Multi-language support | Python only | Python/Java/Go/Node |
| Resource enforcement | None | CPU/memory limits |
| Pause/resume | No | Yes |
| Host disk usage during approval | Workspace persists | Zero (stateless) |
| Transient failure resilience | Zero retries | 3 retries with exponential backoff |
| Full pipeline overhead | Baseline | Net faster (image + parallel saves > sandbox overhead) |

---

## 12. Appendix

### A. Why Clone in Sandbox

Cloning inside the sandbox was chosen over cloning on the host and uploading files into the sandbox. Upload/sync-back would require batching writes, exclude patterns, and change detection; it would also leave the host workspace on disk during the approval gap. Cloning in the sandbox gives a single command per stage, no host↔sandbox transfer, and a stateless approval gap. Git credentials are passed into the sandbox (same pattern as LLM API keys); sandboxes are ephemeral and network policy limits egress.

### B. SDK API Reference

```python
from opensandbox.sandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule
from opensandbox.models.filesystem import WriteEntry

config = ConnectionConfig(domain="localhost:8080", api_key="", protocol="http")

sandbox = await Sandbox.create(
    "opensandbox/code-interpreter:v1.0.1",
    connection_config=config,
    timeout=timedelta(minutes=20),
    entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    resource={"cpu": "2", "memory": "4Gi"},
    env={"PYTHON_VERSION": "3.11"},
    network_policy=NetworkPolicy(
        defaultAction="deny",
        egress=[NetworkRule(action="allow", target="pypi.org")],
    ),
)

result = await sandbox.commands.run("echo hello")
# result.logs.stdout[0].text → "hello\n"
# result.exit_code → 0

await sandbox.files.write_files([WriteEntry(path="/tmp/f.txt", data="hi", mode=644)])
content = await sandbox.files.read_file("/tmp/f.txt")

await sandbox.pause()
sandbox = await Sandbox.resume(sandbox_id=sandbox.id, connection_config=config)
await sandbox.kill()
```

### C. Glossary

- **Sandbox:** Isolated execution environment managed by OpenSandbox
- **SandboxGitOps:** Git operations executed via shell commands inside sandbox
- **SandboxPipelineRunner:** Orchestrates APPLY→DRAFT_PR inside a single sandbox
- **Execd:** Execution daemon inside each sandbox
- **Code Interpreter:** Jupyter-based multi-language execution
- **OpenCode:** AI code generation CLI tool
- **YOLO Mode:** Auto-approval for low-risk changes
- **Checkpoint:** Git commit created before APPLY for rollback safety

---

**End of Document**
