"""
Planning Models
Request and response models for planning endpoints
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, TYPE_CHECKING

# Import TestCaseModel for runtime
from .test_generation import TestCaseModel


class EpicPlanRequest(BaseModel):
    """Request model for epic planning operations"""
    epic_key: str = Field(
        ..., 
        description="JIRA epic key to plan",
        example="EPIC-123"
    )
    dry_run: bool = Field(
        default=True,
        description="Create JIRA tickets (default: true for preview mode)",
        example=True
    )
    split_oversized_tasks: bool = Field(
        default=True,
        description="Automatically split tasks that exceed the cycle time limit",
        example=True
    )
    generate_test_cases: bool = Field(
        default=True,
        description="Generate test cases for stories and tasks",
        example=True
    )
    max_task_cycle_days: float = Field(
        default=3.0,
        ge=0.5,
        le=10.0,
        description="Maximum cycle time allowed per task (in days)",
        example=3.0
    )
    llm_provider: Optional[str] = Field(
        default=None,
        description="LLM provider: openai, claude, gemini, or kimi (uses default if not specified)",
        example="openai"
    )
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM model to use (uses default for provider if not specified)",
        example="gpt-5-mini"
    )


class StoryGenerationRequest(BaseModel):
    """Request model for generating stories for an epic"""
    epic_key: str = Field(
        ..., 
        description="JIRA epic key to generate stories for",
        example="EPIC-123"
    )
    dry_run: bool = Field(
        default=True,
        description="Create JIRA tickets (default: true for preview mode)",
        example=True
    )
    async_mode: bool = Field(
        False,
        description="Process in background (returns job_id for status tracking)",
        example=False
    )
    llm_provider: Optional[str] = Field(
        default=None,
        description="LLM provider: openai, claude, gemini, or kimi (uses default if not specified)",
        example="openai"
    )
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM model to use (uses default for provider if not specified)",
        example="gpt-5-mini"
    )
    generate_test_cases: bool = Field(
        default=False,
        description="Generate test cases for stories (default: false)",
        example=False
    )


class TaskGenerationRequest(BaseModel):
    """Request model for generating tasks for stories"""
    story_keys: List[str] = Field(
        ..., 
        description="List of JIRA story keys or full JIRA URLs to generate tasks for",
        example=["STORY-1", "STORY-2", "https://company.atlassian.net/browse/STORY-3"]
    )
    epic_key: Optional[str] = Field(
        default=None, 
        description="Parent epic key. If not provided, will be auto-derived from the story tickets' parent epic.",
        example="EPIC-123"
    )
    dry_run: bool = Field(
        default=True,
        description="Create JIRA tickets (default: true for preview mode)",
        example=True
    )
    async_mode: bool = Field(
        False,
        description="Process in background (returns job_id for status tracking)",
        example=False
    )
    split_oversized_tasks: bool = Field(
        default=True,
        description="Automatically split tasks that exceed the cycle time limit",
        example=True
    )
    max_task_cycle_days: float = Field(
        default=3.0,
        ge=0.5,
        le=10.0,
        description="Maximum cycle time allowed per task (in days)",
        example=3.0
    )
    llm_provider: Optional[str] = Field(
        default=None,
        description="LLM provider: openai, claude, gemini, or kimi (uses default if not specified)",
        example="openai"
    )
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM model to use (uses default for provider if not specified)",
        example="gpt-5-mini"
    )
    additional_context: Optional[str] = Field(
        default=None,
        description="Additional context for task generation (e.g., technical constraints, architecture decisions)",
        example="Use PostgreSQL for data storage. Follow REST API conventions. Implement rate limiting."
    )
    generate_test_cases: bool = Field(
        default=False,
        description="Generate test cases for tasks (default: false)",
        example=False
    )


class EpicAnalysisResponse(BaseModel):
    """Response model for epic gap analysis"""
    epic_key: str = Field(..., description="Epic that was analyzed")
    existing_stories: List[str] = Field(..., description="Existing story keys")
    missing_stories: List[str] = Field(..., description="Missing story areas identified")
    incomplete_stories: List[str] = Field(..., description="Stories without tasks")
    orphaned_tasks: List[str] = Field(..., description="Tasks without parent stories")
    prd_requirements: List[str] = Field(..., description="Requirements from PRD")
    rfc_requirements: List[str] = Field(..., description="Requirements from RFC")
    needs_stories: bool = Field(..., description="Whether stories need to be created")
    needs_tasks: bool = Field(..., description="Whether tasks need to be created")
    is_complete: bool = Field(..., description="Whether epic structure is complete")
    summary: Dict[str, Any] = Field(..., description="Summary statistics")


class TaskDetail(BaseModel):
    """Detailed task information for API responses"""
    task_id: Optional[str] = Field(None, description="Temporary task ID (UUID) for dependency resolution before JIRA creation")
    summary: str = Field(..., description="Task title/summary")
    description: str = Field(..., description="Full task description")
    team: str = Field(..., description="Team responsible for the task")
    depends_on_tasks: List[str] = Field(default_factory=list, description="Task IDs (task_id or summary) this task depends on. Prefer task_id when available.")
    estimated_days: Optional[float] = Field(None, description="Total estimated cycle time in days")
    test_cases: List[TestCaseModel] = Field(default_factory=list, description="Test cases for this task")
    jira_key: Optional[str] = Field(None, description="JIRA ticket key if created")


class StoryDetail(BaseModel):
    """Detailed story information for API responses"""
    summary: str = Field(..., description="Story title/summary")
    description: str = Field(..., description="Full story description")
    acceptance_criteria: List[str] = Field(default_factory=list, description="Story acceptance criteria (deprecated - now in description)")
    test_cases: List[TestCaseModel] = Field(default_factory=list, description="Test cases for this story")
    tasks: List[TaskDetail] = Field(default_factory=list, description="Tasks under this story")
    jira_key: Optional[str] = Field(None, description="JIRA ticket key if created or found")
    jira_url: Optional[str] = Field(None, description="Full JIRA ticket URL")
    ticket_source: Optional[str] = Field(None, description="Where the JIRA ticket was found: 'prd_table', 'jira_api', 'newly_created', or None")
    action_taken: Optional[str] = Field(None, description="Action taken for this story: 'created', 'updated', 'skipped', or None")
    was_updated: Optional[bool] = Field(None, description="Whether the JIRA ticket was updated/synced during this operation")
    prd_row_uuid: Optional[str] = Field(None, description="Temporary UUID for matching PRD table row (from dry run preview)")


class PlanningResultResponse(BaseModel):
    """Response model for planning operations"""
    epic_key: str = Field(..., description="Epic that was planned")
    operation_mode: str = Field(..., description="Operation mode used")
    success: bool = Field(..., description="Whether planning was successful")
    created_tickets: Dict[str, List[str]] = Field(..., description="Created ticket keys by type")
    story_details: List[StoryDetail] = Field(default_factory=list, description="Detailed information about generated stories with test cases")
    task_details: List[TaskDetail] = Field(default_factory=list, description="Detailed information about generated tasks with test cases")
    summary_stats: Optional[Dict[str, Any]] = Field(None, description="Planning summary statistics")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    warnings: List[str] = Field(default_factory=list, description="Any warnings")
    execution_time_seconds: float = Field(..., description="Time taken for planning")
    system_prompt: Optional[str] = Field(None, description="System prompt sent to LLM")
    user_prompt: Optional[str] = Field(None, description="User prompt sent to LLM")


class CycleTimeEstimateResponse(BaseModel):
    """Response model for cycle time estimates"""
    ticket_key: str = Field(..., description="Ticket that was analyzed")
    development_days: float = Field(..., description="Estimated development time")
    testing_days: float = Field(..., description="Estimated testing time")
    review_days: float = Field(..., description="Estimated review time")
    deployment_days: float = Field(..., description="Estimated deployment time")
    total_days: float = Field(..., description="Total estimated cycle time")
    confidence_level: float = Field(..., description="Confidence in estimate (0-1)")
    exceeds_limit: bool = Field(..., description="Whether estimate exceeds configured limit")
    split_recommendations: Optional[List[str]] = Field(None, description="Task split suggestions if oversized")


class PRDStorySyncRequest(BaseModel):
    """Request model for syncing story tickets from PRD table"""
    epic_key: Optional[str] = Field(
        default=None,
        description="JIRA epic key. If provided, PRD URL will be read from epic's PRD custom field.",
        example="EPIC-123"
    )
    prd_url: Optional[str] = Field(
        default=None,
        description="PRD document URL. Required if epic_key is not provided.",
        example="https://company.atlassian.net/wiki/spaces/PROJ/pages/123456789/PRD"
    )
    dry_run: bool = Field(
        default=True,
        description="Create JIRA tickets (default: true for preview mode)",
        example=True
    )
    async_mode: bool = Field(
        default=False,
        description="Process in background (returns job_id for status tracking)",
        example=False
    )
    existing_ticket_action: str = Field(
        default="skip",
        description="Action to take when story ticket already exists: 'skip' (don't create), 'update' (update existing), 'error' (return error)",
        example="skip"
    )
    llm_provider: Optional[str] = Field(
        default=None,
        description="LLM provider: openai, claude, gemini, or kimi (uses default if not specified)",
        example="openai"
    )
    llm_model: Optional[str] = Field(
        default=None,
        description="LLM model to use (uses default for provider if not specified)",
        example="gpt-5-mini"
    )


class PRDStorySyncResponse(PlanningResultResponse):
    """Response model for PRD story sync operations"""
    pass

