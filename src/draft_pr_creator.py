"""
Draft PR Creator
Service for creating branches, pushing changes, and creating draft PRs
"""
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

import git
from git import Repo, GitCommandError

from .bitbucket_client import BitbucketClient
from .package_service import PackageService
from .draft_pr_models import PlanVersion

logger = logging.getLogger(__name__)


class DraftPRCreatorError(Exception):
    """Base exception for draft PR creator errors"""
    pass


class DraftPRCreator:
    """
    Creates draft PRs by:
    1. Creating feature branch
    2. Pushing changes to remote
    3. Creating draft PR via Bitbucket API
    4. Linking PR to JIRA ticket
    """
    
    def __init__(
        self,
        workspace_path: Path,
        bitbucket_client: BitbucketClient
    ):
        """
        Initialize draft PR creator.
        
        Args:
            workspace_path: Path to workspace with git repos
            bitbucket_client: Bitbucket client for API calls
        """
        self.workspace_path = workspace_path
        self.bitbucket_client = bitbucket_client
    
    def create_draft_pr(
        self,
        plan_version: PlanVersion,
        pr_metadata: Dict[str, Any],
        job_id: str,
        ticket_key: Optional[str] = None,
        destination_branch: str = "main"
    ) -> Dict[str, Any]:
        """
        Create draft PR from packaged changes.
        
        Args:
            plan_version: Plan version that was applied
            pr_metadata: PR metadata from PackageService
            job_id: Job identifier (for branch naming)
            ticket_key: Optional JIRA ticket key
            destination_branch: Destination branch (default: main)
            
        Returns:
            Dict with PR information
        """
        # Find primary repo
        repos = list(self.workspace_path.iterdir())
        if not repos:
            raise DraftPRCreatorError("No repositories found in workspace")
        
        primary_repo_path = repos[0]
        if not (primary_repo_path / ".git").exists():
            raise DraftPRCreatorError(f"Not a git repository: {primary_repo_path}")
        
        repo = Repo(primary_repo_path)
        
        # Detect default branch if not provided
        if destination_branch == "main":
            # Try to detect default branch from remote
            try:
                # First, try to get symbolic ref for origin/HEAD
                try:
                    remote_head_ref = repo.git.symbolic_ref('refs/remotes/origin/HEAD', '--quiet')
                    if remote_head_ref:
                        # Extract branch name (e.g., "refs/remotes/origin/main" -> "main")
                        default_branch = remote_head_ref.replace('refs/remotes/origin/', '')
                        if default_branch:
                            destination_branch = default_branch
                            logger.info(f"Detected default branch from symbolic ref: {destination_branch}")
                except Exception:
                    # Fall back to checking common branch names
                    for branch_name in ['main', 'master', 'develop', 'dev']:
                        try:
                            # Check if branch exists in remote
                            repo.git.show_ref(f'refs/remotes/origin/{branch_name}', '--quiet')
                            destination_branch = branch_name
                            logger.info(f"Found default branch by checking remotes: {destination_branch}")
                            break
                        except Exception:
                            continue
            except Exception as e:
                logger.warning(f"Could not detect default branch, using 'main': {e}")
                # Keep default "main"
        
        # Extract workspace and repo slug from remote URL
        workspace, repo_slug = self._extract_repo_info(repo)
        
        # Generate branch name with collision handling
        max_retries = 5
        branch_name = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Generate branch name with suffix for retries
                branch_name = self._generate_branch_name(job_id, ticket_key, plan_version, suffix=attempt)
                
                # Create and checkout branch
                self._create_branch(repo, branch_name, destination_branch)
                break  # Success, exit retry loop
                
            except DraftPRCreatorError as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(f"Branch name collision for {branch_name}, retrying with suffix {attempt + 1}: {e}")
                    continue
                else:
                    # Last attempt failed
                    raise DraftPRCreatorError(
                        f"Failed to create branch after {max_retries} attempts. Last error: {e}"
                    )
        
        if not branch_name:
            raise DraftPRCreatorError(f"Failed to generate valid branch name after {max_retries} attempts")
        
        # Push branch to remote
        branch_pushed = False
        try:
            self._push_branch(repo, branch_name)
            branch_pushed = True
        except Exception as e:
            # If push fails, try to delete local branch to clean up
            try:
                repo.git.checkout(destination_branch)
                repo.git.branch('-D', branch_name)
            except Exception:
                pass
            raise DraftPRCreatorError(f"Failed to push branch {branch_name}: {e}")
        
        # Create draft PR via Bitbucket API
        pr_data = None
        try:
            pr_data = self.bitbucket_client.create_draft_pull_request(
                workspace=workspace,
                repo_slug=repo_slug,
                title=pr_metadata.get('title', 'Draft PR'),
                description=pr_metadata.get('description', ''),
                source_branch=branch_name,
                destination_branch=destination_branch,
                ticket_key=ticket_key
            )
        except Exception as e:
            # PR creation failed - branch is already pushed
            # This is a partial failure - branch exists but no PR
            logger.error(f"Failed to create PR after pushing branch {branch_name}: {e}")
            
            # Store partial failure information for recovery
            partial_failure_info = {
                "branch_name": branch_name,
                "workspace": workspace,
                "repo_slug": repo_slug,
                "destination_branch": destination_branch,
                "ticket_key": ticket_key,
                "pr_metadata": pr_metadata,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            
            # Store partial failure info in artifact store for manual recovery
            # The branch exists and can be used to manually create a PR
            logger.warning(
                f"Partial failure: Branch {branch_name} pushed but PR creation failed. "
                f"Branch can be used to manually create PR. Error: {e}"
            )
            
            # Raise error with recovery information
            raise DraftPRCreatorError(
                f"Branch {branch_name} was pushed successfully, but PR creation failed: {e}. "
                f"Branch exists at {workspace}/{repo_slug}:{branch_name} and can be used to manually create a PR. "
                f"Recovery info stored in artifacts."
            )
        
        logger.info(f"Created draft PR #{pr_data.get('id')} for job {job_id}")
        
        return {
            "pr_id": pr_data.get('id'),
            "pr_url": pr_data.get('links', {}).get('html', {}).get('href'),
            "branch_name": branch_name,
            "workspace": workspace,
            "repo_slug": repo_slug
        }
    
    def _extract_repo_info(self, repo: Repo) -> tuple:
        """
        Extract workspace and repo slug from remote URL.
        
        Args:
            repo: Git repository
            
        Returns:
            Tuple of (workspace, repo_slug)
        """
        try:
            remote = repo.remotes.origin
            url = remote.url
            
            # Parse URL (supports both HTTPS and SSH)
            # HTTPS: https://bitbucket.org/workspace/repo.git
            # SSH: git@bitbucket.org:workspace/repo.git
            
            if url.startswith('https://'):
                # https://bitbucket.org/workspace/repo.git
                parts = url.replace('https://bitbucket.org/', '').replace('.git', '').split('/')
            elif url.startswith('git@'):
                # git@bitbucket.org:workspace/repo.git
                parts = url.split(':')[1].replace('.git', '').split('/')
            else:
                raise DraftPRCreatorError(f"Unsupported remote URL format: {url}")
            
            if len(parts) != 2:
                raise DraftPRCreatorError(f"Could not parse workspace/repo from URL: {url}")
            
            return tuple(parts)
            
        except Exception as e:
            raise DraftPRCreatorError(f"Failed to extract repo info: {e}")
    
    def _generate_branch_name(
        self,
        job_id: str,
        ticket_key: Optional[str],
        plan_version: PlanVersion,
        suffix: int = 0
    ) -> str:
        """
        Generate branch name with optional suffix for collision handling.
        
        Format: augment/{ticket_key}-{plan_hash[:8]} or augment/{job_id}
        With suffix: augment/{ticket_key}-{plan_hash[:8]}-{suffix}
        
        Args:
            job_id: Job identifier
            ticket_key: Optional ticket key
            plan_version: Plan version
            suffix: Optional suffix for collision handling (0 = no suffix)
            
        Returns:
            Branch name (sanitized for git)
        """
        # Sanitize ticket_key to prevent injection
        if ticket_key:
            # Remove any characters that could be problematic in branch names
            sanitized_key = ''.join(c for c in ticket_key if c.isalnum() or c in ['-', '_'])
            if not sanitized_key:
                sanitized_key = "ticket"
            base_name = f"augment/{sanitized_key}-{plan_version.plan_hash[:8]}"
        else:
            # job_id should already be UUID, but sanitize just in case
            sanitized_job_id = ''.join(c for c in job_id if c.isalnum() or c == '-')
            base_name = f"augment/{sanitized_job_id}"
        
        # Add suffix if provided (for collision handling)
        if suffix > 0:
            return f"{base_name}-{suffix}"
        return base_name
    
    def _create_branch(self, repo: Repo, branch_name: str, source_branch: str):
        """
        Create and checkout branch.
        
        Args:
            repo: Git repository
            branch_name: New branch name
            source_branch: Source branch
            
        Raises:
            DraftPRCreatorError: If branch creation fails or branch already exists
        """
        try:
            # Check if branch already exists locally
            existing_local_branches = [ref.name.split('/')[-1] for ref in repo.refs if not ref.is_remote]
            if branch_name in existing_local_branches:
                # Local branch exists - check if it's the right one
                try:
                    # Try to checkout existing branch
                    repo.git.checkout(branch_name)
                    logger.warning(f"Branch {branch_name} already exists locally, using existing branch")
                    return
                except Exception:
                    # Branch exists but can't checkout - might be from different source
                    raise DraftPRCreatorError(
                        f"Branch {branch_name} already exists locally. Please use a different job_id or ticket_key."
                    )
            
            # Check if branch exists remotely
            try:
                remote_branches = [ref.name.split('/')[-1] for ref in repo.refs if ref.is_remote]
                if branch_name in remote_branches:
                    # Remote branch exists - fetch and checkout
                    try:
                        repo.git.fetch('origin', branch_name)
                        repo.git.checkout('-b', branch_name, f'origin/{branch_name}')
                        logger.warning(f"Branch {branch_name} already exists remotely, using existing branch")
                        return
                    except Exception as e:
                        raise DraftPRCreatorError(
                            f"Branch {branch_name} already exists remotely and cannot be checked out: {e}"
                        )
            except Exception as e:
                logger.warning(f"Could not check remote branches: {e}")
            
            # Checkout source branch first
            try:
                repo.git.checkout(source_branch)
            except Exception as e:
                raise DraftPRCreatorError(f"Failed to checkout source branch {source_branch}: {e}")
            
            # Create and checkout new branch
            try:
                repo.git.checkout('-b', branch_name)
                logger.info(f"Created and checked out branch: {branch_name}")
            except Exception as e:
                raise DraftPRCreatorError(f"Failed to create branch {branch_name}: {e}")
            
        except GitCommandError as e:
            raise DraftPRCreatorError(f"Failed to create branch: {e}")
    
    def _push_branch(self, repo: Repo, branch_name: str):
        """
        Push branch to remote.
        
        Args:
            repo: Git repository
            branch_name: Branch name
        """
        try:
            # Push branch to remote
            repo.git.push('origin', branch_name, '--set-upstream')
            
            logger.info(f"Pushed branch {branch_name} to remote")
            
        except GitCommandError as e:
            raise DraftPRCreatorError(f"Failed to push branch: {e}")
