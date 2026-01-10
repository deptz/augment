"""
Generation Models
Request and response models for ticket generation endpoints
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List
from datetime import datetime


class JQLRequest(BaseModel):
    """Request model for batch processing tickets using JQL query"""
    jql: str = Field(
        ..., 
        description="JQL (JIRA Query Language) query to find tickets",
        example="project = MYPROJ AND description is EMPTY AND created >= '2025-01-01'"
    )
    max_results: int = Field(
        default=100, 
        ge=1, 
        le=1000, 
        description="Maximum number of tickets to process (1-1000)"
    )
    update_jira: bool = Field(
        False,
        description="Update JIRA (default: false for preview mode)",
        example=False
    )
    llm_model: Optional[str] = Field(
        None,
        description="LLM model to use (uses default if not provided)",
        example="gpt-5-mini"
    )
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider to use: openai, claude, gemini, or kimi (uses default if not provided)",
        example="openai"
    )
    
    @validator('llm_provider')
    def validate_provider(cls, v):
        if v is not None:
            supported_providers = ['openai', 'claude', 'gemini', 'kimi']
            if v not in supported_providers:
                raise ValueError(f"Unsupported LLM provider: {v}. Supported providers: {supported_providers}")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "jql": "project = MYPROJ AND description is EMPTY",
                "max_results": 50,
                "update_jira": False,
                "llm_provider": "openai",
                "llm_model": "gpt-5-mini"
            }
        }


class SingleTicketRequest(BaseModel):
    ticket_key: str = Field(
        ..., 
        description="JIRA ticket key or full JIRA URL (e.g., PROJ-123 or https://company.atlassian.net/browse/PROJ-123)",
        example="PROJ-123"
    )
    update_jira: bool = Field(
        False,
        description="Update JIRA (default: false for preview mode)",
        example=False
    )
    async_mode: bool = Field(
        False,
        description="Process in background (returns job_id for status tracking)",
        example=False
    )
    llm_model: Optional[str] = Field(
        None,
        description="LLM model to use (uses default if not provided)",
        example="gpt-5-mini"
    )
    llm_provider: Optional[str] = Field(
        None,
        description="LLM provider to use: openai, claude, gemini, or kimi (uses default if not provided)",
        example="openai"
    )
    additional_context: Optional[str] = Field(
        default=None,
        description="Additional context for description generation (e.g., technical constraints, architecture decisions)",
        example="Use PostgreSQL for data storage. Follows microservice architecture pattern."
    )
    
    @validator('llm_provider')
    def validate_provider(cls, v):
        if v is not None:
            supported_providers = ['openai', 'claude', 'gemini', 'kimi']
            if v not in supported_providers:
                raise ValueError(f"Unsupported LLM provider: {v}. Supported providers: {supported_providers}")
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "ticket_key": "PROJ-123",
                "update_jira": False,
                "llm_provider": "openai",
                "llm_model": "gpt-5-mini",
                "additional_context": "Uses Redis for caching. Must be compatible with Python 3.10."
            },
            "examples": [
                {
                    "ticket_key": "PROJ-123",
                    "update_jira": False
                },
                {
                    "ticket_key": "https://company.atlassian.net/browse/PROJ-123",
                    "update_jira": False
                }
            ]
        }


class TicketResponse(BaseModel):
    """Response model for processed tickets"""
    ticket_key: str = Field(..., description="JIRA ticket key")
    summary: str = Field(..., description="Ticket summary")
    assignee_name: Optional[str] = Field(None, description="Assignee display name")
    parent_name: Optional[str] = Field(None, description="Parent/Epic name")
    generated_description: Optional[str] = Field(None, description="AI-generated description")
    success: bool = Field(..., description="Whether processing was successful")
    error: Optional[str] = Field(None, description="Error message if failed")
    skipped_reason: Optional[str] = Field(None, description="Reason for skipping if applicable")
    updated_in_jira: bool = Field(..., description="Whether the ticket was actually updated in JIRA")
    llm_provider: Optional[str] = Field(None, description="LLM provider used for generation")
    llm_model: Optional[str] = Field(None, description="LLM model used for generation")
    system_prompt: Optional[str] = Field(None, description="System prompt sent to LLM")
    user_prompt: Optional[str] = Field(None, description="User prompt sent to LLM")


class BatchResponse(BaseModel):
    """Response model for batch processing jobs"""
    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(..., description="Job status (started, processing, completed, failed)")
    message: str = Field(..., description="Human-readable status message")
    status_url: str = Field(..., description="URL to check job status")
    jql: str = Field(..., description="JQL query used")
    max_results: int = Field(..., description="Maximum tickets to process")
    update_jira: bool = Field(..., description="Whether tickets will be updated in JIRA")
    safety_note: str = Field(default="JIRA will only be updated if update_jira is explicitly set to true")


class JobStatus(BaseModel):
    """Status information for background processing jobs"""
    job_id: str = Field(..., description="Job identifier")
    job_type: str = Field(default="batch", description="Type of job (batch, single, story_generation, task_generation, test_generation, etc.)")
    status: str = Field(..., description="Current job status")
    progress: dict = Field(..., description="Progress information")
    results: Optional[dict] = Field(None, description="Processing results (if completed) - format depends on job_type")
    started_at: datetime = Field(..., description="Job start timestamp")
    completed_at: Optional[datetime] = Field(None, description="Job completion timestamp")
    total_tickets: Optional[int] = Field(None, description="Total number of tickets to process (for batch jobs)")
    processed_tickets: int = Field(default=0, description="Number of tickets processed so far")
    successful_tickets: int = Field(default=0, description="Number of successfully processed tickets")
    failed_tickets: int = Field(default=0, description="Number of failed tickets")
    error: Optional[str] = Field(None, description="Error message if job failed")
    ticket_key: Optional[str] = Field(None, description="Primary ticket key being processed (for single ticket jobs)")
    ticket_keys: Optional[List[str]] = Field(None, description="List of ticket keys being processed (for batch or multi-ticket jobs)")
    story_key: Optional[str] = Field(None, description="Primary story key being processed (for single story jobs, e.g., story_coverage)")
    story_keys: Optional[List[str]] = Field(None, description="List of story keys being processed (for multi-story jobs, e.g., task_generation)")
    prd_url: Optional[str] = Field(None, description="PRD document URL (for prd_story_sync jobs)")

