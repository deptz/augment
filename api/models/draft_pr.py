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
    feedback: str = Field(..., description="Free-form feedback text")
    specific_concerns: List[str] = Field(default_factory=list, description="List of specific concerns")
    requested_changes: Optional[str] = Field(None, description="Structured change requests")
    feedback_type: FeedbackType = Field(default=FeedbackType.GENERAL, description="Type of feedback")


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
