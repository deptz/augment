"""
Story Analysis Models
Request and response models for story coverage analysis endpoints
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any


class StoryCoverageRequest(BaseModel):
    """Request model for story coverage analysis"""
    story_key: str = Field(
        ..., 
        description="Story ticket key to analyze",
        example="PROJ-123",
        pattern=r"^[A-Z]+-\d+$"
    )
    include_test_cases: bool = Field(
        default=True,
        description="Include test case coverage analysis"
    )
    async_mode: bool = Field(
        False,
        description="Process in background (returns job_id for status tracking)",
        example=False
    )
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider: openai, claude, gemini, or kimi (uses default if not specified)"
    )
    llm_model: Optional[str] = Field(
        None,
        description="LLM model to use (uses default if not specified)"
    )
    
    @validator('llm_provider')
    def validate_provider(cls, v):
        if v is not None:
            supported_providers = ['openai', 'claude', 'gemini', 'kimi']
            if v not in supported_providers:
                raise ValueError(f"Unsupported LLM provider: {v}. Supported: {supported_providers}")
        return v


class TaskSummaryModel(BaseModel):
    """Summary of a task ticket"""
    task_key: str = Field(..., description="Task ticket key")
    summary: str = Field(..., description="Task summary/title")
    description: str = Field(..., description="Task description")
    test_cases: Optional[str] = Field(None, description="Test cases if available")


class CoverageGap(BaseModel):
    """A gap in requirement coverage"""
    requirement: str = Field(..., description="The unmet requirement from story")
    severity: str = Field(..., description="Gap severity: critical, important, or minor")
    suggestion: str = Field(..., description="Suggestion for addressing the gap")


class UpdateTaskSuggestion(BaseModel):
    """Suggestion for updating an existing task"""
    task_key: str = Field(..., description="Task key to update")
    current_description: str = Field(..., description="Current task description")
    suggested_description: str = Field(..., description="Suggested updated description")
    suggested_test_cases: Optional[str] = Field(None, description="Suggested updated test cases")
    ready_to_submit: Dict[str, Any] = Field(..., description="Ready-to-paste JSON for /analyze/story-coverage/update-task endpoint")


class NewTaskSuggestion(BaseModel):
    """Suggestion for creating a new task"""
    summary: str = Field(..., description="Suggested task summary")
    description: str = Field(..., description="Suggested task description")
    test_cases: Optional[str] = Field(None, description="Suggested test cases")
    gap_addressed: str = Field(..., description="Which coverage gap this task addresses")
    ready_to_submit: Dict[str, Any] = Field(..., description="Ready-to-paste JSON for /analyze/story-coverage/create-task endpoint")


class StoryCoverageResponse(BaseModel):
    """Response model for story coverage analysis"""
    success: bool = Field(..., description="Whether analysis was successful")
    story_key: str = Field(..., description="Story ticket key")
    story_description: str = Field(..., description="Story description")
    tasks: List[TaskSummaryModel] = Field(default_factory=list, description="Existing tasks under this story")
    coverage_percentage: float = Field(..., description="Estimated coverage percentage (0-100)")
    gaps: List[CoverageGap] = Field(default_factory=list, description="Identified coverage gaps")
    overall_assessment: str = Field(..., description="Overall assessment summary")
    suggestions_for_updates: List[UpdateTaskSuggestion] = Field(
        default_factory=list,
        description="Suggestions for updating existing tasks with ready-to-submit JSON"
    )
    suggestions_for_new_tasks: List[NewTaskSuggestion] = Field(
        default_factory=list,
        description="Suggestions for new tasks with ready-to-submit JSON"
    )
    error: Optional[str] = Field(None, description="Error message if analysis failed")
    system_prompt: Optional[str] = Field(None, description="System prompt sent to LLM")
    user_prompt: Optional[str] = Field(None, description="User prompt sent to LLM")


class UpdateTaskRequest(BaseModel):
    """Request to update an existing task with suggested improvements"""
    task_key: str = Field(
        ...,
        description="Task ticket key to update",
        example="PROJ-124"
    )
    updated_description: str = Field(
        ...,
        description="Updated task description (user can copy from suggestions and edit)"
    )
    updated_test_cases: Optional[str] = Field(
        None,
        description="Updated test cases (optional)"
    )
    update_jira: bool = Field(
        default=False,
        description="Update JIRA (default: false for preview)"
    )


class CreateTaskRequest(BaseModel):
    """Request to create a new task from suggestions"""
    story_key: str = Field(
        ...,
        description="Parent story ticket key",
        example="PROJ-123"
    )
    task_summary: str = Field(
        ...,
        description="Task summary/title (user can copy from suggestions and edit)"
    )
    task_description: str = Field(
        ...,
        description="Task description (user can copy from suggestions and edit)"
    )
    test_cases: Optional[str] = Field(
        None,
        description="Test cases (optional)"
    )
    create_ticket: bool = Field(
        default=False,
        description="Create ticket in JIRA (default: false for preview)"
    )


class UpdateTaskResponse(BaseModel):
    """Response from updating a task"""
    success: bool = Field(..., description="Whether update was successful")
    task_key: str = Field(..., description="Task key that was updated")
    updated_in_jira: bool = Field(..., description="Whether JIRA was actually updated")
    preview_description: Optional[str] = Field(None, description="Preview of description (if not updated in JIRA)")
    preview_test_cases: Optional[str] = Field(None, description="Preview of test cases (if not updated in JIRA)")
    message: str = Field(..., description="Status message")
    error: Optional[str] = Field(None, description="Error message if failed")


class CreateTaskResponse(BaseModel):
    """Response from creating a new task"""
    success: bool = Field(..., description="Whether creation was successful")
    story_key: str = Field(..., description="Parent story key")
    task_key: Optional[str] = Field(None, description="Created task key (if actually created)")
    created_in_jira: bool = Field(..., description="Whether task was actually created in JIRA")
    preview_summary: Optional[str] = Field(None, description="Preview of task summary")
    preview_description: Optional[str] = Field(None, description="Preview of task description")
    preview_test_cases: Optional[str] = Field(None, description="Preview of test cases")
    message: str = Field(..., description="Status message")
    error: Optional[str] = Field(None, description="Error message if failed")

