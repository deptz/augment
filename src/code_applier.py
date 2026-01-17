"""
Code Applier
Service for applying code changes to workspace with git transaction safety
"""
import logging
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
from contextlib import contextmanager

import git
from git import Repo, GitCommandError

from .draft_pr_models import PlanSpec, PlanVersion

logger = logging.getLogger(__name__)


class CodeApplierError(Exception):
    """Base exception for code applier errors"""
    pass


class PlanApplyGuardError(CodeApplierError):
    """Raised when plan-apply guard detects divergence"""
    pass


class CodeApplier:
    """
    Applies code changes to workspace with git transaction safety.
    
    Uses git transactions to ensure atomicity - on failure, workspace is reset.
    """
    
    def __init__(self, workspace_path: Path):
        """
        Initialize code applier.
        
        Args:
            workspace_path: Path to workspace with git repos
        """
        self.workspace_path = workspace_path
    
    @contextmanager
    def git_transaction(self, repo_path: Path):
        """
        Context manager for git transaction safety.
        
        Creates a checkpoint commit before changes, and resets on failure.
        
        Args:
            repo_path: Path to git repository
            
        Yields:
            Repo object
            
        Raises:
            CodeApplierError: If transaction fails
        """
        repo = Repo(repo_path)
        
        # Check for problematic git states
        if repo.head.is_detached:
            raise CodeApplierError("Repository is in detached HEAD state. Cannot proceed with APPLY.")
        
        # Check for uncommitted changes that aren't part of our transaction
        if repo.is_dirty():
            # Check if there are uncommitted changes that might conflict
            uncommitted = repo.git.status('--porcelain')
            if uncommitted.strip():
                logger.warning(f"Repository has uncommitted changes before APPLY: {uncommitted[:100]}")
                # We'll commit these as part of checkpoint, but log the warning
        
        # Check for merge conflicts
        if repo.index.conflicts:
            raise CodeApplierError("Repository has merge conflicts. Resolve conflicts before APPLY.")
        
        original_commit = repo.head.commit.hexsha
        
        try:
            # Create checkpoint commit
            if repo.is_dirty():
                repo.git.add(A=True)
                repo.index.commit("Checkpoint before APPLY")
                checkpoint_commit = repo.head.commit.hexsha
            else:
                checkpoint_commit = original_commit
            
            logger.info(f"Git transaction started, checkpoint: {checkpoint_commit[:8]}")
            
            yield repo
            
            logger.info(f"Git transaction completed successfully")
            
        except Exception as e:
            # Reset to checkpoint on failure
            logger.error(f"Git transaction failed, resetting to checkpoint: {e}")
            try:
                repo.git.reset('--hard', checkpoint_commit)
                logger.info(f"Reset to checkpoint {checkpoint_commit[:8]}")
            except Exception as reset_error:
                logger.error(f"Failed to reset to checkpoint: {reset_error}")
                raise CodeApplierError(f"Transaction failed and reset failed: {reset_error}")
            raise CodeApplierError(f"Transaction failed: {e}")
    
    async def apply_plan(
        self,
        plan_version: PlanVersion,
        opencode_runner: Any,
        job_id: str,
        cancellation_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Apply plan to workspace.
        
        Args:
            plan_version: Approved plan version to apply
            opencode_runner: OpenCode runner for executing changes
            job_id: Job identifier
            cancellation_event: Cancellation event
            
        Returns:
            Dict with:
                - changed_files: List of changed file paths
                - loc_delta: Lines of code delta
                - commit_hash: Git commit hash (if committed)
                
        Raises:
            CodeApplierError: If application fails
            PlanApplyGuardError: If plan-apply guard detects divergence
        """
        plan_spec = plan_version.plan_spec
        
        # Find the primary repo (first repo in workspace)
        repos = list(self.workspace_path.iterdir())
        if not repos:
            raise CodeApplierError("No repositories found in workspace")
        
        primary_repo_path = repos[0]
        if not (primary_repo_path / ".git").exists():
            raise CodeApplierError(f"Not a git repository: {primary_repo_path}")
        
        # Build prompt for OpenCode to apply changes
        prompt = self._build_apply_prompt(plan_spec)
        
        # Use git transaction for safety
        with self.git_transaction(primary_repo_path) as repo:
            # Store original state for verification
            original_commit = repo.head.commit.hexsha
            original_dirty = repo.is_dirty()
            
            # Execute OpenCode to apply changes
            try:
                result = await opencode_runner.execute(
                    job_id=job_id,
                    workspace_path=self.workspace_path,
                    prompt=prompt,
                    job_type="code_application",
                    cancellation_event=cancellation_event
                )
            except asyncio.TimeoutError as e:
                # OpenCode timeout - verify workspace state
                current_commit = repo.head.commit.hexsha
                current_dirty = repo.is_dirty()
                
                # Check if workspace was modified before timeout
                if current_commit != original_commit or (not original_dirty and current_dirty):
                    logger.warning(f"OpenCode timed out but workspace was modified. Commit: {original_commit[:8]} -> {current_commit[:8]}, Dirty: {original_dirty} -> {current_dirty}")
                    # Workspace was partially modified - transaction will rollback
                
                raise CodeApplierError(f"OpenCode execution timed out: {e}")
            except Exception as e:
                # Verify workspace state after failure
                current_commit = repo.head.commit.hexsha
                current_dirty = repo.is_dirty()
                
                # Check if workspace was modified before failure
                if current_commit != original_commit or (not original_dirty and current_dirty):
                    logger.warning(f"OpenCode failed but workspace was modified. Commit: {original_commit[:8]} -> {current_commit[:8]}, Dirty: {original_dirty} -> {current_dirty}")
                    # Workspace was partially modified - transaction will rollback
                    raise CodeApplierError(
                        f"OpenCode execution failed and workspace was partially modified. "
                        f"Workspace will be rolled back to checkpoint. Error: {e}"
                    )
                else:
                    # No changes made - safe failure
                    raise CodeApplierError(f"OpenCode execution failed (no workspace changes): {e}")
            
            # Verify OpenCode result is valid
            if not result:
                raise CodeApplierError("OpenCode returned empty result")
            
            # Get changed files (before staging)
            changed_files = self._get_changed_files(repo)
            loc_delta = self._calculate_loc_delta(repo)
            
            # Verify workspace state after OpenCode execution
            final_commit = repo.head.commit.hexsha
            final_dirty = repo.is_dirty()
            
            # Log workspace state for debugging
            logger.info(
                f"OpenCode execution completed. Workspace state: commit={final_commit[:8]}, "
                f"dirty={final_dirty}, changed_files={len(changed_files)}, loc_delta={loc_delta}"
            )
            
            # Plan-Apply guard: verify changes match plan BEFORE staging
            # This way if guard fails, we can abort without staging
            self._verify_plan_apply_guard(plan_spec, changed_files, loc_delta)
            
            # Stage all changes
            if repo.is_dirty():
                repo.git.add(A=True)
                
                # Get git diff after staging but before committing
                git_diff = repo.git.diff('--cached', 'HEAD')
                
                # Commit changes
                commit_message = f"Apply plan v{plan_version.version}\n\n{plan_spec.summary}"
                repo.index.commit(commit_message)
                commit_hash = repo.head.commit.hexsha
            else:
                git_diff = ""
                commit_hash = None
                logger.warning("No changes detected after APPLY")
        
        return {
            "changed_files": changed_files,
            "loc_delta": loc_delta,
            "commit_hash": commit_hash,
            "git_diff": git_diff
        }
    
    def _build_apply_prompt(self, plan_spec: PlanSpec) -> str:
        """
        Build prompt for OpenCode to apply plan changes.
        
        Args:
            plan_spec: Plan specification
            
        Returns:
            Prompt string
        """
        files_section = "\n".join([
            f"- {f.get('path')}: {f.get('change', 'modify')}"
            for f in plan_spec.scope.get('files', [])
        ])
        
        return f"""Apply the following plan to the codebase:

**Summary:**
{plan_spec.summary}

**Files to Modify:**
{files_section}

**Implementation Requirements:**
- Follow the plan exactly
- Implement all specified changes
- Maintain code quality and style
- Add appropriate comments where needed

**Happy Paths to Implement:**
{chr(10).join(f'- {path}' for path in plan_spec.happy_paths)}

**Edge Cases to Handle:**
{chr(10).join(f'- {case}' for case in plan_spec.edge_cases)}

**Tests to Create/Update:**
{chr(10).join(f'- {t.get("type")}: {t.get("target")}' for t in plan_spec.tests)}

Make the changes and ensure the code compiles and follows best practices.
"""
    
    def _get_changed_files(self, repo: Repo) -> List[str]:
        """
        Get list of changed files in repository.
        
        Args:
            repo: Git repository
            
        Returns:
            List of changed file paths
        """
        changed = []
        
        # Get diff from HEAD
        diff = repo.head.commit.diff(None, create_patch=False)
        
        for item in diff:
            if item.a_path:
                changed.append(item.a_path)
            if item.b_path and item.b_path != item.a_path:
                changed.append(item.b_path)
        
        return sorted(set(changed))
    
    def _calculate_loc_delta(self, repo: Repo) -> int:
        """
        Calculate lines of code delta.
        
        Args:
            repo: Git repository
            
        Returns:
            LOC delta (positive = added, negative = removed)
        """
        try:
            # Use git diff --stat to get line counts
            diff_stat = repo.git.diff('--stat', 'HEAD')
            
            # Parse diff stat output
            # Format: "file.py | 10 ++++++++++---"
            total_added = 0
            total_removed = 0
            
            for line in diff_stat.split('\n'):
                if '|' in line and ('+' in line or '-' in line):
                    # Extract numbers
                    parts = line.split('|')
                    if len(parts) == 2:
                        stats = parts[1].strip()
                        # Parse like "10 ++++++++++---"
                        if '+' in stats and '-' in stats:
                            # Count + and - characters
                            added = stats.count('+')
                            removed = stats.count('-')
                            total_added += added
                            total_removed += removed
            
            return total_added - total_removed
            
        except Exception as e:
            logger.warning(f"Failed to calculate LOC delta: {e}")
            return 0
    
    def _verify_plan_apply_guard(
        self,
        plan_spec: PlanSpec,
        changed_files: List[str],
        loc_delta: int
    ) -> None:
        """
        Verify that changes match the plan (Plan-Apply Guard).
        
        Args:
            plan_spec: Original plan specification
            changed_files: Files that were actually changed
            loc_delta: Actual LOC delta
            
        Raises:
            PlanApplyGuardError: If guard detects divergence
        """
        violations = []
        
        # Check changed files ⊆ plan.scope.files
        planned_files = {f.get('path') for f in plan_spec.scope.get('files', [])}
        actual_files = set(changed_files)
        
        # Handle case where plan specifies no files (should be caught by validation, but defensive check)
        if not planned_files and actual_files:
            violations.append(f"Plan specifies no files to change, but {len(actual_files)} files were changed: {actual_files}")
        
        unexpected_files = actual_files - planned_files
        if unexpected_files:
            violations.append(f"Unexpected files changed: {unexpected_files}")
        
        # Check for files that were planned but not changed (warn, not error - might be intentional)
        missing_files = planned_files - actual_files
        if missing_files:
            logger.warning(f"Files specified in plan but not changed: {missing_files}")
        
        # Check LOC delta within reasonable bounds (allow some variance)
        # We can't enforce exact LOC match, but we can check it's not way off
        # This is a heuristic - actual enforcement would need more sophisticated analysis
        if abs(loc_delta) > 1000:  # Very large changes might indicate divergence
            violations.append(f"LOC delta very large: {loc_delta} (might indicate divergence)")
        
        if violations:
            raise PlanApplyGuardError(f"Plan-Apply guard violations: {'; '.join(violations)}")
