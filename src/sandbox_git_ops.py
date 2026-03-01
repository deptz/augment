"""
Git operations inside an OpenSandbox via shell commands.
Replaces GitPython-based logic in CodeApplier, PackageService, DraftPRCreator.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, quote

from .sandbox_client import SandboxGitError

logger = logging.getLogger(__name__)


class SandboxGitOps:
    """
    Git operations executed inside a sandbox via shell commands.
    All methods are stateless — they take a sandbox and repo path.
    """

    def __init__(self, sandbox: Any, repo_path: str = "/workspace/repo"):
        self.sandbox = sandbox
        self.repo_path = repo_path

    async def _run(self, cmd: str, check: bool = True) -> Tuple[int, str, str]:
        """Run a command in the sandbox, return (exit_code, stdout, stderr)."""
        result = await self.sandbox.commands.run(f"cd {self.repo_path} && {cmd}")
        stdout = "".join(msg.text for msg in result.logs.stdout) if result.logs.stdout else ""
        stderr = "".join(msg.text for msg in result.logs.stderr) if result.logs.stderr else ""
        if check and result.exit_code != 0:
            raise SandboxGitError(
                f"Command failed (exit {result.exit_code}): {cmd}\n{stderr}"
            )
        return result.exit_code, stdout.strip(), stderr.strip()

    async def clone(
        self,
        url: str,
        branch: Optional[str] = None,
        shallow: bool = False,
        git_username: Optional[str] = None,
        git_password: Optional[str] = None,
    ) -> None:
        """Clone a repository into the sandbox."""
        auth_url = self._add_auth_to_url(url, git_username, git_password)
        parts = ["git clone"]
        if shallow:
            parts.append("--depth 1")
        if branch:
            parts.append(f"--branch {branch}")
        parts.append(f'"{auth_url}" {self.repo_path}')
        await self._run(" ".join(parts))
        await self._run('git config user.name "Augment Bot"')
        await self._run('git config user.email "augment@automated.local"')

    def _add_auth_to_url(
        self,
        url: str,
        username: Optional[str],
        password: Optional[str],
    ) -> str:
        """Inject credentials into HTTPS URL."""
        if not username or not password:
            return url
        if url.startswith("https://"):
            parsed = urlparse(url)
            user_enc = quote(username, safe="")
            pass_enc = quote(password, safe="")
            return f"https://{user_enc}:{pass_enc}@{parsed.netloc}{parsed.path}"
        return url

    async def check_repo_state(self) -> None:
        """Reject problematic git states before APPLY."""
        exit_code, _, _ = await self._run("git symbolic-ref HEAD", check=False)
        if exit_code != 0:
            raise SandboxGitError("Repository is in detached HEAD state")
        exit_code, unmerged, _ = await self._run("git ls-files --unmerged", check=False)
        if unmerged.strip():
            raise SandboxGitError("Repository has merge conflicts")

    async def create_checkpoint(self) -> str:
        """Create checkpoint commit, return its SHA."""
        _, dirty, _ = await self._run("git status --porcelain", check=False)
        if dirty.strip():
            logger.warning("Uncommitted changes before APPLY: %s", dirty[:100])
            await self._run("git add -A")
            await self._run('git commit -m "Checkpoint before APPLY" --allow-empty')
        _, sha, _ = await self._run("git rev-parse HEAD")
        logger.info("Git checkpoint: %s", sha[:8])
        return sha

    async def rollback_to(self, sha: str) -> None:
        """Hard reset to checkpoint SHA."""
        try:
            await self._run(f"git reset --hard {sha}")
            logger.info("Rolled back to %s", sha[:8])
        except SandboxGitError as e:
            raise SandboxGitError(f"Rollback failed: {e}") from e

    async def get_changed_files(self) -> List[str]:
        """Get list of files changed since last commit."""
        _, output, _ = await self._run("git diff --name-only HEAD", check=False)
        if not output.strip():
            return []
        return sorted(set(f.strip() for f in output.split("\n") if f.strip()))

    async def get_loc_delta(self) -> int:
        """Calculate lines added minus lines removed."""
        _, output, _ = await self._run(
            "git diff --numstat HEAD | awk '{added+=$1; removed+=$2} END {print added-removed}'",
            check=False,
        )
        try:
            return int(output.strip())
        except (ValueError, TypeError):
            return 0

    async def get_diff(self, cached: bool = False) -> str:
        """Get git diff output."""
        flag = "--cached " if cached else ""
        _, diff, _ = await self._run(f"git diff {flag}HEAD", check=False)
        return diff

    async def get_diff_stat(self) -> str:
        """Get diff stat for PR description."""
        _, stat, _ = await self._run("git diff --stat HEAD~1", check=False)
        return stat

    async def stage_and_commit(self, message: str) -> Optional[str]:
        """Stage all changes and commit. Returns SHA or None if nothing to commit."""
        _, dirty, _ = await self._run("git status --porcelain", check=False)
        if not dirty.strip():
            logger.warning("No changes to commit")
            return None
        await self._run("git add -A")
        await self._run(f'git commit -m "{message}"')
        _, sha, _ = await self._run("git rev-parse HEAD")
        return sha

    async def create_branch_and_push(
        self,
        branch_name: str,
        destination_branch: str = "main",
    ) -> None:
        """Create feature branch from current HEAD and push."""
        await self._run(f"git checkout -b {branch_name}")
        await self._run(f"git push origin {branch_name} --set-upstream")
        logger.info("Pushed branch %s", branch_name)

    async def get_remote_url(self) -> str:
        """Get origin remote URL."""
        _, url, _ = await self._run("git remote get-url origin")
        return url

    async def extract_repo_info(self) -> Tuple[str, str]:
        """Extract (workspace, repo_slug) from remote URL."""
        url = await self.get_remote_url()
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
