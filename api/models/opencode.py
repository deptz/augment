"""
OpenCode Models
Request and response models for OpenCode integration
"""
import re
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Union


class RepoSpec(BaseModel):
    """Repository specification with URL and optional branch"""
    url: str = Field(
        ...,
        description="Full git clone URL (https:// or git@)",
        example="https://bitbucket.org/company/crm-api.git"
    )
    branch: Optional[str] = Field(
        None,
        description="Branch, tag, or commit hash (uses default branch if not specified)",
        example="develop"
    )

    @validator('url')
    def validate_url(cls, v):
        """Validate that URL is a valid git URL (HTTPS or SSH only)"""
        if not v:
            raise ValueError("URL cannot be empty")
        
        # Only allow HTTPS or SSH git URLs
        if not (v.startswith("https://") or v.startswith("git@")):
            raise ValueError("Only HTTPS (https://) or SSH (git@) git URLs are allowed")
        
        # Block potentially dangerous patterns
        dangerous_patterns = ["file://", "ftp://", "..", "://localhost", "://127.0.0.1"]
        for pattern in dangerous_patterns:
            if pattern in v.lower():
                raise ValueError(f"Invalid URL pattern: {pattern} is not allowed")
        
        return v

    @validator('branch')
    def sanitize_branch(cls, v):
        """Sanitize branch name to prevent command injection"""
        if v is None:
            return v
        
        # Allow alphanumeric, dash, underscore, dot, and forward slash (for refs like feature/xyz)
        if not re.match(r'^[\w\-\.\/]+$', v):
            raise ValueError(
                "Invalid branch name. Only alphanumeric characters, "
                "dashes, underscores, dots, and forward slashes are allowed."
            )
        
        # Prevent path traversal
        if ".." in v:
            raise ValueError("Branch name cannot contain '..'")
        
        return v


# Type alias for repos parameter - can be string URLs or RepoSpec objects
RepoInput = Union[str, RepoSpec]


def normalize_repo_input(repo: RepoInput) -> RepoSpec:
    """
    Normalize repository input to RepoSpec.
    
    Accepts either:
    - A string URL (converted to RepoSpec with default branch)
    - A RepoSpec object
    - A dict with 'url' and optional 'branch' keys
    """
    if isinstance(repo, str):
        return RepoSpec(url=repo)
    elif isinstance(repo, dict):
        return RepoSpec(**repo)
    elif isinstance(repo, RepoSpec):
        return repo
    else:
        raise ValueError(f"Invalid repo specification type: {type(repo)}")


def validate_repos_list(repos: Optional[List[RepoInput]], max_repos: int = 5) -> Optional[List[RepoSpec]]:
    """
    Validate and normalize a list of repository inputs.
    
    Args:
        repos: List of repo specifications (strings or RepoSpec objects)
        max_repos: Maximum number of repos allowed per job
        
    Returns:
        List of validated RepoSpec objects, or None if repos is None/empty
        
    Raises:
        ValueError: If validation fails
    """
    if not repos:
        return None
    
    if len(repos) > max_repos:
        raise ValueError(f"Too many repositories: {len(repos)}. Maximum allowed: {max_repos}")
    
    normalized = []
    for i, repo in enumerate(repos):
        try:
            normalized.append(normalize_repo_input(repo))
        except Exception as e:
            raise ValueError(f"Invalid repository at index {i}: {e}")
    
    return normalized


class OpenCodeJobResult(BaseModel):
    """Base result from OpenCode execution"""
    success: bool = Field(..., description="Whether the job completed successfully")
    error: Optional[str] = Field(None, description="Error message if failed")
    execution_time_seconds: Optional[float] = Field(None, description="Time taken to execute")


class TicketDescriptionResult(OpenCodeJobResult):
    """Result from ticket description generation via OpenCode"""
    description: Optional[str] = Field(None, description="Generated ticket description")
    impacted_files: List[str] = Field(default_factory=list, description="Files identified as impacted")
    components: List[str] = Field(default_factory=list, description="Components identified")
    acceptance_criteria: List[str] = Field(default_factory=list, description="Generated acceptance criteria")
    confidence: Optional[str] = Field(None, description="Confidence level: high, medium, or low")


class TaskBreakdownTask(BaseModel):
    """Individual task from task breakdown"""
    summary: str = Field(..., description="Task summary")
    description: str = Field(..., description="Task description")
    files_to_modify: List[str] = Field(default_factory=list, description="Files that need modification")
    estimated_effort: Optional[str] = Field(None, description="Effort estimate: small, medium, or large")
    dependencies: List[str] = Field(default_factory=list, description="Dependencies on other tasks")


class TaskBreakdownResult(OpenCodeJobResult):
    """Result from task breakdown via OpenCode"""
    tasks: List[TaskBreakdownTask] = Field(default_factory=list, description="Generated tasks")
    warnings: List[str] = Field(default_factory=list, description="Warnings or concerns")


class CoverageRequirement(BaseModel):
    """Requirement coverage mapping"""
    requirement: str = Field(..., description="The requirement being checked")
    tasks: List[str] = Field(default_factory=list, description="Tasks covering this requirement")
    files: List[str] = Field(default_factory=list, description="Files related to this requirement")


class CoverageGap(BaseModel):
    """Identified coverage gap"""
    requirement: str = Field(..., description="The uncovered requirement")
    missing_tasks: str = Field(..., description="Description of missing tasks")
    affected_files: List[str] = Field(default_factory=list, description="Files that would be affected")


class CoverageCheckResult(OpenCodeJobResult):
    """Result from coverage check via OpenCode"""
    coverage_percentage: float = Field(..., description="Overall coverage percentage")
    covered_requirements: List[CoverageRequirement] = Field(
        default_factory=list, description="Requirements that are covered"
    )
    gaps: List[CoverageGap] = Field(default_factory=list, description="Identified coverage gaps")
    risks: List[str] = Field(default_factory=list, description="Risky assumptions identified")
