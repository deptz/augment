"""
Workspace Manager
Manages ephemeral workspaces for OpenCode jobs including repo cloning and cleanup
"""
import os
import shutil
import time
import logging
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, quote

import git
from git import Repo, GitCommandError

logger = logging.getLogger(__name__)

# Base directory for all job workspaces
WORKSPACE_BASE_DIR = Path("/tmp/augment/jobs")


class WorkspaceError(Exception):
    """Exception raised for workspace-related errors"""
    pass


class CloneError(WorkspaceError):
    """Exception raised when repository cloning fails"""
    pass


class CloneTimeoutError(CloneError):
    """Exception raised when repository cloning times out"""
    pass


class WorkspaceManager:
    """
    Manages ephemeral workspaces for OpenCode jobs.
    
    Handles:
    - Creating workspace directories
    - Cloning repositories with authentication
    - Cleaning up workspaces
    - Detecting and removing orphaned workspaces
    """
    
    def __init__(
        self,
        git_username: Optional[str] = None,
        git_password: Optional[str] = None,
        clone_timeout_seconds: int = 300,
        shallow_clone: bool = True,
        max_workspace_age_hours: float = 1.0
    ):
        """
        Initialize the workspace manager.
        
        Args:
            git_username: Username for git authentication
            git_password: Password/token for git authentication
            clone_timeout_seconds: Timeout for git clone operations
            shallow_clone: Whether to use shallow clone (--depth 1)
            max_workspace_age_hours: Max age for orphan detection
        """
        self.git_username = git_username
        self.git_password = git_password
        self.clone_timeout_seconds = clone_timeout_seconds
        self.shallow_clone = shallow_clone
        self.max_workspace_age_hours = max_workspace_age_hours
        
        # Ensure base directory exists
        WORKSPACE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    
    def get_workspace_path(self, job_id: str) -> Path:
        """Get the workspace path for a job"""
        return WORKSPACE_BASE_DIR / job_id
    
    def _add_auth_to_url(self, url: str) -> str:
        """
        Add authentication credentials to a git URL.
        
        Args:
            url: Original git URL (https:// or git@)
            
        Returns:
            URL with embedded credentials for HTTPS, or original for SSH
        """
        if not self.git_username or not self.git_password:
            return url
        
        # Only add auth to HTTPS URLs
        if url.startswith("https://"):
            parsed = urlparse(url)
            # URL-encode credentials
            username = quote(self.git_username, safe='')
            password = quote(self.git_password, safe='')
            # Reconstruct URL with credentials
            auth_url = f"https://{username}:{password}@{parsed.netloc}{parsed.path}"
            return auth_url
        
        # SSH URLs use SSH keys, not password auth
        return url
    
    def _get_repo_name(self, url: str) -> str:
        """Extract repository name from URL"""
        # Remove .git suffix if present
        url = url.rstrip('.git')
        # Get last path component
        return url.split('/')[-1]
    
    async def create_workspace(
        self,
        job_id: str,
        repos: List[Dict[str, Any]]
    ) -> Path:
        """
        Create a workspace and clone repositories.
        
        Args:
            job_id: Unique job identifier
            repos: List of repo specs with 'url' and optional 'branch'
            
        Returns:
            Path to the created workspace
            
        Raises:
            WorkspaceError: If workspace creation fails
            CloneError: If repository cloning fails
            CloneTimeoutError: If cloning times out
        """
        workspace_path = self.get_workspace_path(job_id)
        
        try:
            # Create workspace directory
            workspace_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created workspace for job {job_id}: {workspace_path}")
            
            # Clone each repository
            for repo_spec in repos:
                url = repo_spec.get('url')
                branch = repo_spec.get('branch')
                
                if not url:
                    raise CloneError("Repository URL is required")
                
                repo_name = self._get_repo_name(url)
                repo_path = workspace_path / repo_name
                
                await self._clone_repo(url, repo_path, branch)
            
            return workspace_path
            
        except Exception as e:
            # Cleanup on failure
            logger.error(f"Failed to create workspace for job {job_id}: {e}")
            await self.cleanup_workspace(job_id)
            raise
    
    async def _clone_repo(
        self,
        url: str,
        dest_path: Path,
        branch: Optional[str] = None
    ) -> Repo:
        """
        Clone a repository with timeout.
        
        Args:
            url: Repository URL
            dest_path: Destination path for clone
            branch: Optional branch to checkout
            
        Returns:
            Cloned Repo object
            
        Raises:
            CloneError: If cloning fails
            CloneTimeoutError: If cloning times out
        """
        auth_url = self._add_auth_to_url(url)
        
        # Build clone arguments
        clone_kwargs = {
            'to_path': str(dest_path),
        }
        
        if self.shallow_clone and not branch:
            # Shallow clone only works with default branch
            clone_kwargs['depth'] = 1
        
        if branch:
            clone_kwargs['branch'] = branch
            if self.shallow_clone:
                clone_kwargs['depth'] = 1
        
        logger.info(f"Cloning repository: {url} -> {dest_path} (branch: {branch or 'default'})")
        
        try:
            # Run clone in executor to avoid blocking
            loop = asyncio.get_event_loop()
            repo = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: Repo.clone_from(auth_url, **clone_kwargs)
                ),
                timeout=self.clone_timeout_seconds
            )
            
            logger.info(f"Successfully cloned: {url}")
            return repo
            
        except asyncio.TimeoutError:
            logger.error(f"Clone timeout for {url} after {self.clone_timeout_seconds}s")
            # Cleanup partial clone
            if dest_path.exists():
                shutil.rmtree(dest_path, ignore_errors=True)
            raise CloneTimeoutError(f"Clone timeout for {url}")
            
        except GitCommandError as e:
            logger.error(f"Git clone failed for {url}: {e}")
            # Cleanup partial clone
            if dest_path.exists():
                shutil.rmtree(dest_path, ignore_errors=True)
            raise CloneError(f"Failed to clone {url}: {e}")
            
        except Exception as e:
            logger.error(f"Unexpected error cloning {url}: {e}")
            # Cleanup partial clone
            if dest_path.exists():
                shutil.rmtree(dest_path, ignore_errors=True)
            raise CloneError(f"Failed to clone {url}: {e}")
    
    async def cleanup_workspace(self, job_id: str) -> bool:
        """
        Clean up a workspace directory.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if cleanup succeeded, False otherwise
        """
        workspace_path = self.get_workspace_path(job_id)
        
        try:
            if workspace_path.exists():
                shutil.rmtree(workspace_path, ignore_errors=True)
                logger.info(f"Cleaned up workspace for job {job_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cleanup workspace for job {job_id}: {e}")
            return False
    
    async def cleanup_orphaned_workspaces(self) -> int:
        """
        Clean up orphaned workspaces (from crashed jobs).
        
        Returns:
            Number of workspaces cleaned up
        """
        cleaned_count = 0
        max_age_seconds = self.max_workspace_age_hours * 3600
        current_time = time.time()
        
        try:
            if not WORKSPACE_BASE_DIR.exists():
                return 0
            
            for job_dir in WORKSPACE_BASE_DIR.iterdir():
                if not job_dir.is_dir():
                    continue
                
                try:
                    # Check modification time
                    mtime = job_dir.stat().st_mtime
                    age_seconds = current_time - mtime
                    
                    if age_seconds > max_age_seconds:
                        logger.info(
                            f"Removing orphaned workspace: {job_dir.name} "
                            f"(age: {age_seconds / 3600:.1f} hours)"
                        )
                        shutil.rmtree(job_dir, ignore_errors=True)
                        cleaned_count += 1
                        
                except Exception as e:
                    logger.warning(f"Error checking workspace {job_dir}: {e}")
                    
        except Exception as e:
            logger.error(f"Error during orphan cleanup: {e}")
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} orphaned workspaces")
        
        return cleaned_count
    
    def get_workspace_size(self, job_id: str) -> int:
        """
        Get the total size of a workspace in bytes.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Size in bytes, or 0 if workspace doesn't exist
        """
        workspace_path = self.get_workspace_path(job_id)
        
        if not workspace_path.exists():
            return 0
        
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(workspace_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except (OSError, IOError):
                        pass
        except Exception as e:
            logger.warning(f"Error calculating workspace size: {e}")
        
        return total_size
    
    def list_repos_in_workspace(self, job_id: str) -> List[str]:
        """
        List repository names in a workspace.
        
        Args:
            job_id: Job identifier
            
        Returns:
            List of repository directory names
        """
        workspace_path = self.get_workspace_path(job_id)
        
        if not workspace_path.exists():
            return []
        
        repos = []
        for item in workspace_path.iterdir():
            if item.is_dir() and (item / ".git").exists():
                repos.append(item.name)
        
        return repos


# Factory function for creating workspace manager from config
def create_workspace_manager(config: Dict[str, Any]) -> WorkspaceManager:
    """
    Create a WorkspaceManager from configuration.
    
    Args:
        config: Configuration dict with 'opencode' and 'git' sections
        
    Returns:
        Configured WorkspaceManager instance
    """
    opencode_config = config.get('opencode', {})
    git_config = config.get('git', {})
    
    return WorkspaceManager(
        git_username=git_config.get('username') or os.getenv('GIT_USERNAME'),
        git_password=git_config.get('password') or os.getenv('GIT_PASSWORD'),
        clone_timeout_seconds=int(opencode_config.get('clone_timeout_seconds', 300)),
        shallow_clone=opencode_config.get('shallow_clone', True),
        max_workspace_age_hours=1.0  # Orphan detection threshold
    )
