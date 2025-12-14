"""
Bulk Creation Models
Request and response models for bulk ticket creation
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class BulkTicketCreationRequest(BaseModel):
    """Request for bulk ticket creation"""
    epic_key: str = Field(..., description="Epic key for ticket creation")
    create_tickets: bool = Field(False, description="Create tickets (false for dry run)")
    operation_mode: str = Field("hybrid", description="Operation mode: documentation, planning, or hybrid")
    async_mode: bool = Field(False, description="Process in background (returns job_id for status tracking)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "epic_key": "PROJ-123",
                "create_tickets": False,
                "operation_mode": "hybrid"
            }
        }


class BulkCreationResponse(BaseModel):
    """Response for bulk ticket creation"""
    epic_key: str
    create_tickets: bool
    success: bool
    planning_results: Optional[Dict[str, Any]] = None
    creation_results: Optional[Dict[str, Any]] = None
    rollback_info: Optional[Dict[str, Any]] = None
    errors: List[str] = []
    execution_time_seconds: float
    job_id: Optional[str] = Field(None, description="Job ID for async processing (only present if async_mode=true)")
    status_url: Optional[str] = Field(None, description="URL to check job status (only present if async_mode=true)")


class StoryCreationRequest(BaseModel):
    """Request for creating stories only"""
    epic_key: str = Field(..., description="Epic key")
    story_count: Optional[int] = Field(5, description="Number of stories to generate")
    create_tickets: bool = Field(False, description="Create tickets")
    async_mode: bool = Field(False, description="Process in background (returns job_id for status tracking)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "epic_key": "PROJ-123",
                "story_count": 5,
                "create_tickets": False
            }
        }


class TaskCreationRequest(BaseModel):
    """Request for creating tasks"""
    story_keys: List[str] = Field(..., description="List of story keys")
    tasks_per_story: Optional[int] = Field(3, description="Tasks per story")
    create_tickets: bool = Field(False, description="Create tickets")
    async_mode: bool = Field(False, description="Process in background (returns job_id for status tracking)")

