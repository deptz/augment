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
        
        # Extract workspace and repo slug from remote URL
        workspace, repo_slug = self._extract_repo_info(repo)
        
        # Generate branch name
        branch_name = self._generate_branch_name(job_id, ticket_key, plan_version)
        
        # Create and checkout branch
        self._create_branch(repo, branch_name, destination_branch)
        
        # Push branch to remote
        try:
            self._push_branch(repo, branch_name)
        except Exception as e:
            # If push fails, try to delete local branch to clean up
            try:
                repo.git.checkout(destination_branch)
                repo.git.branch('-D', branch_name)
            except Exception:
                pass
            raise DraftPRCreatorError(f"Failed to push branch {branch_name}: {e}")
        
        # Create draft PR via Bitbucket API
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
            raise DraftPRCreatorError(
                f"Branch {branch_name} was pushed successfully, but PR creation failed: {e}. "
                f"Branch exists but PR was not created."
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
        plan_version: PlanVersion
    ) -> str:
        """
        Generate branch name.
        
        Format: augment/{ticket_key}-{plan_hash[:8]} or augment/{job_id}
        
        Args:
            job_id: Job identifier
            ticket_key: Optional ticket key
            plan_version: Plan version
            
        Returns:
            Branch name (sanitized for git)
        """
        # Sanitize ticket_key to prevent injection
        if ticket_key:
            # Remove any characters that could be problematic in branch names
            sanitized_key = ''.join(c for c in ticket_key if c.isalnum() or c in ['-', '_'])
            if not sanitized_key:
                sanitized_key = "ticket"
            return f"augment/{sanitized_key}-{plan_version.plan_hash[:8]}"
        else:
            # job_id should already be UUID, but sanitize just in case
            sanitized_job_id = ''.join(c for c in job_id if c.isalnum() or c == '-')
            return f"augment/{sanitized_job_id}"
    
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
            # Check if branch already exists
            existing_branches = [ref.name.split('/')[-1] for ref in repo.refs]
            if branch_name in existing_branches:
                # Branch exists - check if it's local or remote
                try:
                    # Try to checkout existing branch
                    repo.git.checkout(branch_name)
                    logger.warning(f"Branch {branch_name} already exists, using existing branch")
                    return
                except Exception:
                    # Branch exists but can't checkout - might be from different source
                    raise DraftPRCreatorError(
                        f"Branch {branch_name} already exists. Please use a different job_id or ticket_key."
                    )
            
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
