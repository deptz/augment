"""
Draft PR Models
Request and response models for draft PR orchestrator endpoints
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.draft_pr_models import FeedbackType


class CreateDraftPRRequest(BaseModel):
    """Request to create a new draft PR job"""
    story_key: str = Field(..., description="JIRA story key")
    repos: List[Dict[str, Any]] = Field(..., description="List of repositories with url and optional branch")
    scope: Optional[Dict[str, Any]] = Field(None, description="Optional scope constraints")
    additional_context: Optional[str] = Field(None, description="Additional context")
    mode: str = Field(default="normal", description="Pipeline mode: 'normal' or 'yolo'")
    
    @validator('mode')
    def validate_mode(cls, v):
        if v not in ['normal', 'yolo']:
            raise ValueError("mode must be 'normal' or 'yolo'")
        return v
    
    @validator('repos')
    def validate_repos(cls, v):
        if not v or len(v) == 0:
            raise ValueError("At least one repository must be provided")
        if len(v) > 5:  # Reasonable limit
            raise ValueError("Maximum 5 repositories allowed per job")
        return v


class RevisePlanRequest(BaseModel):
    """Request to revise a plan based on feedback"""
    feedback: str = Field(..., min_length=1, max_length=5000, description="Free-form feedback text")
    specific_concerns: List[str] = Field(default_factory=list, description="List of specific concerns")
    requested_changes: Optional[str] = Field(None, max_length=5000, description="Structured change requests")
    feedback_type: FeedbackType = Field(default=FeedbackType.GENERAL, description="Type of feedback")
    
    @validator('specific_concerns')
    def validate_concerns(cls, v):
        if len(v) > 20:
            raise ValueError("Maximum 20 specific concerns allowed")
        # Validate each concern
        for concern in v:
            if not concern or len(concern) > 500:
                raise ValueError("Each concern must be 1-500 characters")
        return v


class ApprovePlanRequest(BaseModel):
    """Request to approve a plan"""
    plan_hash: str = Field(..., description="Hash of the plan to approve")


class PlanRevisionResponse(BaseModel):
    """Response from plan revision"""
    plan_version: int = Field(..., description="New plan version number")
    plan_hash: str = Field(..., description="Hash of the new plan")
    changes_summary: str = Field(..., description="Summary of changes from previous version")


class PlanComparisonResponse(BaseModel):
    """Response from plan comparison"""
    from_version: int = Field(..., description="Source version")
    to_version: int = Field(..., description="Target version")
    changes: Dict[str, Any] = Field(..., description="Structured changes")
    summary: str = Field(..., description="Human-readable summary")
    changed_sections: List[str] = Field(..., description="List of changed sections")


class StructuredPlanComparison(BaseModel):
    """Enhanced response from plan comparison with structured diff"""
    from_version: int = Field(..., description="Source version")
    to_version: int = Field(..., description="Target version")
    summary: str = Field(..., description="Human-readable summary")
    changed_sections: List[str] = Field(..., description="List of changed sections")
    file_changes: List[Dict[str, Any]] = Field(default_factory=list, description="File-level changes")
    section_diffs: List[Dict[str, Any]] = Field(default_factory=list, description="Section-level diffs")
    additions: int = Field(default=0, description="Count of additions")
    deletions: int = Field(default=0, description="Count of deletions")
    modifications: int = Field(default=0, description="Count of modifications")


class RetryJobRequest(BaseModel):
    """Request to retry a failed job"""
    stage: Optional[str] = Field(None, max_length=50, description="Stage to retry from (PLANNING, APPLYING, VERIFYING, etc.)")
    force: bool = Field(False, description="Force retry even if job is not in failed state")
    
    @validator('stage')
    def validate_stage(cls, v):
        if v is not None:
            valid_stages = ["PLANNING", "APPLYING", "VERIFYING", "PACKAGING", "DRAFTING"]
            if v not in valid_stages:
                raise ValueError(f"Invalid stage: {v}. Valid stages: {', '.join(valid_stages)}")
        return v


class ProgressResponse(BaseModel):
    """Response from progress tracking endpoint"""
    job_id: str = Field(..., description="Job identifier")
    stage: str = Field(..., description="Current pipeline stage")
    percentage: int = Field(..., ge=0, le=100, description="Percentage completion (0-100)")
    current_step: str = Field(..., description="Current step description")
    total_steps: int = Field(..., description="Total number of steps in current stage")
    steps_completed: int = Field(..., description="Number of steps completed")
    estimated_time_remaining: Optional[int] = Field(None, description="Estimated seconds remaining")
    stage_started_at: Optional[datetime] = Field(None, description="When current stage started")
    stage_duration: Optional[int] = Field(None, description="Seconds elapsed in current stage")


class StoryValidationResponse(BaseModel):
    """Response from story validation"""
    exists: bool = Field(..., description="Whether story exists in JIRA")
    valid: bool = Field(..., description="Whether story is valid for draft PR")
    story_key: str = Field(..., description="Story key")
    summary: Optional[str] = Field(None, description="Story summary")
    status: Optional[str] = Field(None, description="Story status")
    error: Optional[str] = Field(None, description="Error message if invalid")


class RepoValidationRequest(BaseModel):
    """Request to validate repository access"""
    url: str = Field(..., description="Repository URL")
    branch: Optional[str] = Field(None, description="Optional branch name")


class RepoValidationResponse(BaseModel):
    """Response from repository validation"""
    accessible: bool = Field(..., description="Whether repository is accessible")
    url: str = Field(..., description="Repository URL")
    branch: Optional[str] = Field(None, description="Branch name")
    default_branch: Optional[str] = Field(None, description="Default branch name")
    error: Optional[str] = Field(None, description="Error message if not accessible")
    workspace: Optional[str] = Field(None, description="Extracted workspace name")
    repo_slug: Optional[str] = Field(None, description="Extracted repository slug")


class ArtifactMetadata(BaseModel):
    """Metadata for an artifact"""
    artifact_type: str = Field(..., description="Type of artifact")
    size_bytes: int = Field(..., description="Size in bytes")
    content_type: str = Field(..., description="Content type (MIME type)")
    encoding: Optional[str] = Field(None, description="Character encoding")
    created_at: datetime = Field(..., description="When artifact was created")
    updated_at: Optional[datetime] = Field(None, description="When artifact was last updated")
    checksum: Optional[str] = Field(None, description="SHA256 checksum of artifact content")


class TemplateCreateRequest(BaseModel):
    """Request to create a template"""
    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    description: Optional[str] = Field(None, max_length=500, description="Template description")
    repos: List[Dict[str, Any]] = Field(..., description="List of repositories")
    scope: Optional[Dict[str, Any]] = Field(None, description="Scope constraints")
    additional_context: Optional[str] = Field(None, max_length=5000, description="Additional context")
    
    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Template name cannot be empty")
        # Prevent dangerous characters
        if any(char in v for char in ['..', '/', '\\', '\x00']):
            raise ValueError("Template name contains invalid characters")
        return v.strip()


class TemplateUpdateRequest(BaseModel):
    """Request to update a template"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Template name")
    description: Optional[str] = Field(None, max_length=500, description="Template description")
    repos: Optional[List[Dict[str, Any]]] = Field(None, description="List of repositories")
    scope: Optional[Dict[str, Any]] = Field(None, description="Scope constraints")
    additional_context: Optional[str] = Field(None, max_length=5000, description="Additional context")
    
    @validator('name')
    def validate_name(cls, v):
        if v is not None:
            if not v.strip():
                raise ValueError("Template name cannot be empty")
            # Prevent dangerous characters
            if any(char in v for char in ['..', '/', '\\', '\x00']):
                raise ValueError("Template name contains invalid characters")
            return v.strip()
        return v


class TemplateResponse(BaseModel):
    """Response for template operations"""
    template_id: str = Field(..., description="Template identifier")
    name: str = Field(..., description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    repos: List[Dict[str, Any]] = Field(..., description="List of repositories")
    scope: Optional[Dict[str, Any]] = Field(None, description="Scope constraints")
    additional_context: Optional[str] = Field(None, description="Additional context")
    created_at: datetime = Field(..., description="When template was created")
    created_by: str = Field(..., description="User who created the template")
    updated_at: Optional[datetime] = Field(None, description="When template was last updated")


class TemplateSummary(BaseModel):
    """Summary of a template (for list operations)"""
    template_id: str = Field(..., description="Template identifier")
    name: str = Field(..., description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    created_at: Optional[datetime] = Field(None, description="When template was created")
    updated_at: Optional[datetime] = Field(None, description="When template was last updated")


class BulkCreateRequest(BaseModel):
    """Request to create multiple draft PR jobs"""
    jobs: List[CreateDraftPRRequest] = Field(..., description="List of jobs to create")
    max_concurrent: int = Field(5, ge=1, le=10, description="Maximum concurrent jobs")


class BulkApproveRequest(BaseModel):
    """Request to approve multiple plans"""
    approvals: List[Dict[str, str]] = Field(..., description="List of approvals with job_id and plan_hash")


class BulkResponse(BaseModel):
    """Response for bulk operations"""
    total: int = Field(..., description="Total number of operations")
    successful: int = Field(..., description="Number of successful operations")
    failed: int = Field(..., description="Number of failed operations")
    results: List[Dict[str, Any]] = Field(..., description="Detailed results for each operation")


class AnalyticsStats(BaseModel):
    """Overall analytics statistics"""
    total_jobs: int = Field(..., description="Total number of jobs")
    successful_jobs: int = Field(..., description="Number of successful jobs")
    failed_jobs: int = Field(..., description="Number of failed jobs")
    success_rate: float = Field(..., description="Success rate percentage")
    avg_duration_seconds: float = Field(..., description="Average job duration in seconds")
    avg_planning_duration: Optional[float] = Field(None, description="Average planning stage duration")
    avg_applying_duration: Optional[float] = Field(None, description="Average applying stage duration")
    avg_verifying_duration: Optional[float] = Field(None, description="Average verifying stage duration")
    common_failure_reasons: List[Dict[str, Any]] = Field(default_factory=list, description="Most common failure reasons")
    jobs_by_stage: Dict[str, int] = Field(default_factory=dict, description="Job count by stage")


class JobAnalyticsRequest(BaseModel):
    """Request for job analytics"""
    start_date: Optional[datetime] = Field(None, description="Start date filter")
    end_date: Optional[datetime] = Field(None, description="End date filter")
    status: Optional[str] = Field(None, description="Status filter")
