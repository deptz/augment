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
        """
        Extract repository name from URL with path sanitization.
        
        Args:
            url: Repository URL
            
        Returns:
            Sanitized repository name safe for filesystem use
        """
        # Remove .git suffix if present
        url = url.rstrip('.git')
        # Get last path component
        repo_name = url.split('/')[-1]
        
        # Sanitize to prevent path traversal and filesystem issues
        # Remove any path components (/, \)
        repo_name = repo_name.replace('/', '_').replace('\\', '_')
        # Remove path traversal attempts
        repo_name = repo_name.replace('..', '_')
        # Remove null bytes
        repo_name = repo_name.replace('\x00', '_')
        # Remove leading/trailing dots and spaces (Windows filesystem issues)
        repo_name = repo_name.strip('. ')
        
        # If empty after sanitization, use a default
        if not repo_name:
            repo_name = 'repository'
        
        return repo_name
    
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
            
            # Distribute Agents.md to all repos and workspace root
            await self._distribute_agents_md(workspace_path, repos)
            
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
    
    def _load_opencode_agents_template(self) -> str:
        """
        Load the OpenCode-specific Agents.md template.
        
        Returns:
            Template content as string
            
        Raises:
            WorkspaceError: If template file cannot be read or is invalid
        """
        # Find template file relative to this module
        # workspace_manager.py is in src/, template is in src/prompts/
        template_path = Path(__file__).parent / "prompts" / "opencode_agents.md"
        
        if not template_path.exists():
            raise WorkspaceError(
                f"OpenCode Agents.md template not found at {template_path}. "
                "Ensure src/prompts/opencode_agents.md exists."
            )
        
        # Check if it's a file (not a directory)
        if not template_path.is_file():
            raise WorkspaceError(
                f"OpenCode Agents.md template path exists but is not a file: {template_path}"
            )
        
        # Check file size (max 1MB for template)
        max_template_size = 1024 * 1024  # 1MB
        try:
            file_size = template_path.stat().st_size
            if file_size > max_template_size:
                raise WorkspaceError(
                    f"OpenCode Agents.md template is too large ({file_size} bytes, max {max_template_size} bytes)"
                )
        except OSError as e:
            raise WorkspaceError(f"Failed to check template file size: {e}")
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Validate content is not empty
            if not content or not content.strip():
                raise WorkspaceError("OpenCode Agents.md template is empty")
            
            return content
        except UnicodeDecodeError as e:
            raise WorkspaceError(
                f"OpenCode Agents.md template has invalid UTF-8 encoding: {e}"
            )
        except Exception as e:
            raise WorkspaceError(f"Failed to read OpenCode Agents.md template: {e}")
    
    def _find_agents_md_file(self, directory: Path) -> Optional[Path]:
        """
        Find Agents.md file in a directory (case-insensitive).
        
        Args:
            directory: Directory to search
            
        Returns:
            Path to Agents.md file if found, None otherwise
        """
        if not directory.exists() or not directory.is_dir():
            return None
        
        # Check for common variations
        for filename in ['Agents.md', 'AGENTS.md', 'agents.md', 'Agents.MD', 'AGENTS.MD']:
            file_path = directory / filename
            if file_path.exists():
                # Ensure it's a file, not a directory
                if file_path.is_file():
                    return file_path
                else:
                    # Log warning if it's a directory
                    logger.warning(
                        f"Found {filename} but it's a directory, not a file. Skipping."
                    )
        
        return None
    
    def _write_agents_md(self, file_path: Path, content: str, append: bool = False):
        """
        Write or append content to Agents.md file with safety checks.
        
        Args:
            file_path: Path to Agents.md file
            content: Content to write/append
            append: If True, append to existing file; if False, overwrite
        """
        # Maximum file size for existing files (10MB)
        max_file_size = 10 * 1024 * 1024  # 10MB
        
        try:
            # Check if target is a directory
            if file_path.exists() and file_path.is_dir():
                logger.warning(
                    f"Cannot write Agents.md: {file_path} is a directory, not a file"
                )
                return
            
            if append and file_path.exists():
                # Check file size before reading
                try:
                    file_size = file_path.stat().st_size
                    if file_size > max_file_size:
                        logger.warning(
                            f"Existing Agents.md at {file_path} is too large "
                            f"({file_size} bytes, max {max_file_size} bytes). Skipping append."
                        )
                        return
                except OSError as e:
                    logger.warning(f"Failed to check file size for {file_path}: {e}")
                    return
                
                # Read existing content with encoding fallback
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                except UnicodeDecodeError:
                    # Try with error handling
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                            existing_content = f.read()
                        logger.warning(
                            f"Existing Agents.md at {file_path} had encoding issues, "
                            "replaced invalid characters"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to read existing Agents.md at {file_path}: {e}"
                        )
                        return
                
                # Check if content is already appended (idempotency)
                # Look for the OpenCode MCP Integration header
                if "## OpenCode MCP Integration" in existing_content:
                    logger.debug(
                        f"Agents.md at {file_path} already contains OpenCode content. Skipping."
                    )
                    return
                
                # Append with separator
                separator = "\n\n---\n\n"
                new_content = existing_content + separator + content
            else:
                new_content = content
            
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file atomically (write to temp then rename)
            temp_path = file_path.with_suffix('.md.tmp')
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                # Atomic rename
                temp_path.replace(file_path)
                logger.debug(f"Updated Agents.md at {file_path} (append={append})")
            except Exception as e:
                # Clean up temp file on error
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass
                raise
            
        except PermissionError as e:
            logger.warning(
                f"Permission denied writing Agents.md to {file_path}: {e}"
            )
        except OSError as e:
            logger.warning(f"OS error writing Agents.md to {file_path}: {e}")
        except Exception as e:
            logger.warning(f"Failed to write Agents.md to {file_path}: {e}")
            # Don't raise - this is non-critical
    
    async def _distribute_agents_md(
        self,
        workspace_path: Path,
        repos: List[Dict[str, Any]]
    ):
        """
        Distribute OpenCode-specific Agents.md to all cloned repositories and workspace root.
        
        For each repository:
        - If Agents.md exists: Append OpenCode section with separator
        - If Agents.md doesn't exist: Create new file with OpenCode content
        
        Also creates/updates Agents.md at workspace root level.
        
        Args:
            workspace_path: Path to workspace directory
            repos: List of repo specs that were cloned
        """
        # Handle empty repos list gracefully
        if not repos:
            logger.debug("No repositories to distribute Agents.md to")
            # Still create at workspace root
            try:
                opencode_content = self._load_opencode_agents_template()
                workspace_agents_md = workspace_path / "Agents.md"
                existing_workspace_agents = self._find_agents_md_file(workspace_path)
                
                if existing_workspace_agents:
                    logger.info("Found existing Agents.md at workspace root, appending OpenCode content")
                    self._write_agents_md(existing_workspace_agents, opencode_content, append=True)
                else:
                    logger.info("Creating Agents.md at workspace root")
                    self._write_agents_md(workspace_agents_md, opencode_content, append=False)
            except Exception as e:
                logger.warning(f"Failed to create Agents.md at workspace root: {e}")
            return
        
        try:
            # Load template
            opencode_content = self._load_opencode_agents_template()
            
            # Validate workspace path
            if not workspace_path.exists():
                logger.warning(f"Workspace path does not exist: {workspace_path}")
                return
            
            if not workspace_path.is_dir():
                logger.warning(f"Workspace path is not a directory: {workspace_path}")
                return
            
            # Distribute to each cloned repository
            for repo_spec in repos:
                url = repo_spec.get('url')
                if not url:
                    logger.debug("Skipping repo spec with no URL")
                    continue
                
                repo_name = self._get_repo_name(url)
                repo_path = workspace_path / repo_name
                
                if not repo_path.exists():
                    logger.debug(f"Repo path does not exist, skipping: {repo_path}")
                    continue
                
                if not repo_path.is_dir():
                    logger.warning(f"Repo path is not a directory, skipping: {repo_path}")
                    continue
                
                # Find existing Agents.md (case-insensitive)
                agents_md_path = self._find_agents_md_file(repo_path)
                
                if agents_md_path:
                    # File exists - append
                    logger.info(f"Found existing Agents.md in {repo_name}, appending OpenCode content")
                    self._write_agents_md(agents_md_path, opencode_content, append=True)
                else:
                    # File doesn't exist - create new
                    agents_md_path = repo_path / "Agents.md"
                    logger.info(f"Creating new Agents.md in {repo_name}")
                    self._write_agents_md(agents_md_path, opencode_content, append=False)
            
            # Also create/update at workspace root
            workspace_agents_md = workspace_path / "Agents.md"
            existing_workspace_agents = self._find_agents_md_file(workspace_path)
            
            if existing_workspace_agents:
                logger.info("Found existing Agents.md at workspace root, appending OpenCode content")
                self._write_agents_md(existing_workspace_agents, opencode_content, append=True)
            else:
                logger.info("Creating Agents.md at workspace root")
                self._write_agents_md(workspace_agents_md, opencode_content, append=False)
            
        except WorkspaceError as e:
            # Template loading errors - log but don't fail
            logger.warning(f"Failed to load OpenCode Agents.md template: {e}")
        except Exception as e:
            # Log error but don't fail workspace creation
            logger.warning(f"Failed to distribute Agents.md to workspace: {e}")


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
