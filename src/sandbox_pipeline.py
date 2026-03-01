"""
Run APPLY → VERIFY → PACKAGE → DRAFT_PR inside a single OpenSandbox.
Host only creates/destroys sandbox and calls Bitbucket API for PR creation.
"""
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

# Type for async callbacks (job_id, sandbox_id) -> None and (job_id) -> None
SandboxCreatedCallback = Callable[[str, str], Any]
SandboxReleasedCallback = Callable[[str], Any]

from .sandbox_client import SandboxClient, SandboxGitError, SandboxTimeoutError
from .sandbox_git_ops import SandboxGitOps
from .sandbox_code_runner import SandboxCodeRunner
from .sandbox_verifier import SandboxVerifier
from .draft_pr_models import PlanSpec, PlanVersion
from .artifact_store import ArtifactStore

logger = logging.getLogger(__name__)


class SandboxPipelineRunner:
    """
    Runs APPLY → VERIFY → PACKAGE → DRAFT_PR inside a single sandbox.
    Sandbox owns clone, OpenCode apply, git checkpoint/rollback, plan-apply guard,
    verification, packaging, branch and push. Host does Bitbucket PR API only.
    """

    def __init__(
        self,
        sandbox_runner: SandboxCodeRunner,
        sandbox_verifier: SandboxVerifier,
        bitbucket_client: Optional[Any],
        artifact_store: ArtifactStore,
        timeout_seconds: int = 2700,
    ):
        self.runner = sandbox_runner
        self.verifier = sandbox_verifier
        self.bitbucket_client = bitbucket_client
        self.artifact_store = artifact_store
        self.timeout_seconds = timeout_seconds  # Overall APPLY→PR timeout (default 45 min)

    async def execute_apply_to_pr(
        self,
        job_id: str,
        approved_plan: PlanVersion,
        repo_url: str,
        branch: Optional[str],
        story_key: Optional[str] = None,
        destination_branch: str = "main",
        cancellation_event: Optional[Any] = None,
        on_sandbox_created: Optional[SandboxCreatedCallback] = None,
        on_sandbox_released: Optional[SandboxReleasedCallback] = None,
    ) -> Dict[str, Any]:
        """
        Execute APPLY → VERIFY → PACKAGE → DRAFT_PR in one sandbox.

        Optional on_sandbox_created(job_id, sandbox_id) and on_sandbox_released(job_id)
        are called when a sandbox is created and when it is released (async callables).

        Returns:
            Dict with "stage" ("COMPLETED" | "FAILED"), "error", "apply_results",
            "verification_results", "pr_results". Sandbox is always released in finally.

        Raises:
            SandboxTimeoutError: If the pipeline exceeds timeout_seconds.
        """
        try:
            return await asyncio.wait_for(
                self._execute_apply_to_pr_impl(
                    job_id, approved_plan, repo_url, branch,
                    story_key, destination_branch, cancellation_event,
                    on_sandbox_created, on_sandbox_released,
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise SandboxTimeoutError(
                f"Pipeline timed out after {self.timeout_seconds}s"
            ) from None

    async def _execute_apply_to_pr_impl(
        self,
        job_id: str,
        approved_plan: PlanVersion,
        repo_url: str,
        branch: Optional[str],
        story_key: Optional[str],
        destination_branch: str,
        cancellation_event: Optional[Any],
        on_sandbox_created: Optional[SandboxCreatedCallback] = None,
        on_sandbox_released: Optional[SandboxReleasedCallback] = None,
    ) -> Dict[str, Any]:
        sandbox = await self.runner.create_apply_sandbox(
            job_id=job_id,
            repo_url=repo_url,
            branch=branch,
            cancellation_event=cancellation_event,
        )
        if on_sandbox_created:
            try:
                cb = on_sandbox_created(job_id, str(sandbox.id))
                if asyncio.iscoroutine(cb):
                    await cb
            except Exception as e:
                logger.warning("on_sandbox_created callback failed: %s", e)
        try:
            async with sandbox:
                git_ops = SandboxGitOps(sandbox)
                apply_results = await self._apply(
                    sandbox, git_ops, approved_plan, job_id, cancellation_event
                )
                self.artifact_store.store_artifact(
                    job_id, "git_diff", apply_results.get("git_diff", "")
                )
                if not apply_results.get("commit_hash"):
                    return {
                        "stage": "FAILED",
                        "error": "No changes produced by OpenCode",
                    }
                verification_results = await self.verifier.verify(sandbox)
                self.artifact_store.store_artifact(
                    job_id, "validation_logs", verification_results
                )
                if not verification_results.get("passed"):
                    return {
                        "stage": "FAILED",
                        "error": "Verification failed",
                        "apply_results": apply_results,
                        "verification_results": verification_results,
                    }
                changed_files = await git_ops.get_changed_files()
                pr_metadata = self._generate_pr_metadata(
                    approved_plan, verification_results, changed_files
                )
                self.artifact_store.store_artifact(job_id, "pr_metadata", pr_metadata)
                branch_name = self._generate_branch_name(
                    job_id, story_key, approved_plan
                )
                await git_ops.create_branch_and_push(
                    branch_name, destination_branch
                )
                workspace, repo_slug = await git_ops.extract_repo_info()
                await sandbox.kill()
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
            if on_sandbox_released:
                try:
                    cb = on_sandbox_released(job_id)
                    if asyncio.iscoroutine(cb):
                        await cb
                except Exception as e:
                    logger.warning("on_sandbox_released callback failed: %s", e)
            self.runner.sandbox_client.release_sandbox(f"apply-{job_id}")

    async def _apply(
        self,
        sandbox: Any,
        git_ops: SandboxGitOps,
        plan_version: PlanVersion,
        job_id: str,
        cancellation_event: Optional[Any],
    ) -> Dict[str, Any]:
        """APPLY stage: OpenCode execution with git transaction safety."""
        plan_spec = plan_version.plan_spec
        await git_ops.check_repo_state()
        checkpoint = await git_ops.create_checkpoint()
        try:
            prompt = self._build_apply_prompt(plan_spec)
            await self.runner.run_code_application(
                sandbox, prompt, cancellation_event
            )
            changed_files = await git_ops.get_changed_files()
            loc_delta = await git_ops.get_loc_delta()
            self._verify_plan_apply_guard(plan_spec, changed_files, loc_delta)
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
            logger.error("APPLY failed, rolling back: %s", e)
            await git_ops.rollback_to(checkpoint)
            raise

    def _verify_plan_apply_guard(
        self,
        plan_spec: PlanSpec,
        changed_files: List[str],
        loc_delta: int,
    ) -> None:
        from .code_applier import PlanApplyGuardError
        violations = []
        planned_files = {f.get("path") for f in (plan_spec.scope.get("files") or [])}
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
            logger.warning("Planned but not changed: %s", missing)
        if abs(loc_delta) > 1000:
            violations.append(f"LOC delta very large: {loc_delta}")
        if violations:
            raise PlanApplyGuardError(
                f"Plan-Apply guard violations: {'; '.join(violations)}"
            )

    def _build_apply_prompt(self, plan_spec: PlanSpec) -> str:
        files_section = "\n".join(
            f"- {f.get('path')}: {f.get('change', 'modify')}"
            for f in (plan_spec.scope.get("files") or [])
        )
        happy = "\n".join(f"- {p}" for p in (plan_spec.happy_paths or []))
        edge = "\n".join(f"- {c}" for c in (plan_spec.edge_cases or []))
        tests = "\n".join(
            f"- {t.get('type')}: {t.get('target')}"
            for t in (plan_spec.tests or [])
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
{happy}

**Edge Cases to Handle:**
{edge}

**Tests to Create/Update:**
{tests}

Make the changes and ensure the code compiles and follows best practices.
"""

    def _generate_branch_name(
        self,
        job_id: str,
        ticket_key: Optional[str],
        plan_version: PlanVersion,
    ) -> str:
        if ticket_key:
            sanitized = "".join(c for c in ticket_key if c.isalnum() or c in "-_")
            return f"augment/{sanitized or 'ticket'}-{plan_version.plan_hash[:8]}"
        sanitized = "".join(c for c in job_id if c.isalnum() or c == "-")
        return f"augment/{sanitized}"

    def _generate_pr_metadata(
        self,
        plan_version: PlanVersion,
        verification_results: Optional[Dict[str, Any]],
        changed_files: List[str],
    ) -> Dict[str, Any]:
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
                emoji = "✅" if tr.get("exit_code") == 0 else "❌"
                parts.append(f"{emoji} Tests {'passed' if tr.get('exit_code') == 0 else 'failed'}\n\n")
            sr = verification_results.get("security_scan_results")
            if sr:
                emoji = "✅" if sr.get("exit_code") == 0 else "❌"
                parts.append(f"{emoji} Security scan {'passed' if sr.get('exit_code') == 0 else 'failed'}\n\n")
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
