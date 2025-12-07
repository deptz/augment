"""
Sprint Planning Models
Request and response models for sprint planning endpoints
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class SprintInfo(BaseModel):
    """Sprint details"""
    id: int = Field(..., description="JIRA sprint ID")
    name: str = Field(..., description="Sprint name")
    state: str = Field(..., description="Sprint state (active, closed, future)")
    start_date: Optional[str] = Field(None, description="Sprint start date (ISO format)")
    end_date: Optional[str] = Field(None, description="Sprint end date (ISO format)")
    board_id: Optional[int] = Field(None, description="Board ID")
    goal: Optional[str] = Field(None, description="Sprint goal")
    complete_date: Optional[str] = Field(None, description="Sprint completion date")


class SprintCapacityRequest(BaseModel):
    """Capacity planning request"""
    sprint_id: int = Field(..., description="Sprint ID")
    team_capacity_days: Optional[float] = Field(None, description="Team capacity in days (overrides team member data)")
    board_id: Optional[int] = Field(None, description="Board ID for team capacity calculation")


class SprintAssignmentRequest(BaseModel):
    """Assign tickets to sprint"""
    sprint_id: int = Field(..., description="Sprint ID")
    issue_keys: List[str] = Field(..., description="List of issue keys to assign")
    dry_run: bool = Field(default=True, description="Preview mode (don't actually assign)")


class SprintPlanningRequest(BaseModel):
    """Plan epic/stories to sprints"""
    epic_key: str = Field(..., description="Epic key to plan")
    board_id: int = Field(..., description="Board ID")
    sprint_capacity_days: Optional[float] = Field(None, description="Sprint capacity in days (if not provided, uses team member data)")
    start_date: Optional[str] = Field(None, description="Start date for timeline (ISO format: YYYY-MM-DD)")
    sprint_duration_days: int = Field(default=14, description="Sprint duration in days")
    dry_run: bool = Field(default=True, description="Preview mode (don't create/assign sprints)")
    async_mode: bool = Field(default=False, description="Process in background (returns job_id for status tracking)")
    auto_create_sprints: bool = Field(default=False, description="Auto-create sprints if needed")
    team_id: Optional[int] = Field(None, description="Team ID for capacity calculation (optional)")


class SprintAssignment(BaseModel):
    """Sprint assignment for a task"""
    task_key: str = Field(..., description="Task key")
    task_summary: str = Field(..., description="Task summary")
    sprint_id: Optional[int] = Field(None, description="Assigned sprint ID")
    sprint_name: Optional[str] = Field(None, description="Assigned sprint name")
    estimated_days: float = Field(..., description="Task estimated days")
    team: Optional[str] = Field(None, description="Task team")


class SprintPlanningResponse(BaseModel):
    """Planning results with sprint assignments"""
    epic_key: str = Field(..., description="Epic that was planned")
    board_id: int = Field(..., description="Board ID used")
    success: bool = Field(..., description="Whether planning was successful")
    assignments: List[SprintAssignment] = Field(..., description="Task sprint assignments")
    sprints_created: List[SprintInfo] = Field(default_factory=list, description="Sprints created (if auto_create_sprints=true)")
    total_tasks: int = Field(..., description="Total number of tasks")
    total_sprints: int = Field(..., description="Total number of sprints needed")
    capacity_utilization: Dict[str, float] = Field(default_factory=dict, description="Capacity utilization per sprint")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    warnings: List[str] = Field(default_factory=list, description="Any warnings")


class TimelineRequest(BaseModel):
    """Timeline scheduling request"""
    epic_key: str = Field(..., description="Epic key")
    board_id: int = Field(..., description="Board ID")
    start_date: str = Field(..., description="Start date for timeline (ISO format: YYYY-MM-DD)")
    sprint_duration_days: int = Field(default=14, description="Sprint duration in days")
    team_capacity_days: Optional[float] = Field(None, description="Team capacity in days (if not provided, uses team member data)")
    team_id: Optional[int] = Field(None, description="Team ID for capacity calculation (optional)")
    dry_run: bool = Field(default=True, description="Preview mode")
    async_mode: bool = Field(default=False, description="Process in background (returns job_id for status tracking)")


class SprintTimelineItem(BaseModel):
    """Timeline item for a sprint"""
    sprint_id: Optional[int] = Field(None, description="Sprint ID")
    sprint_name: str = Field(..., description="Sprint name")
    start_date: str = Field(..., description="Sprint start date")
    end_date: str = Field(..., description="Sprint end date")
    tasks: List[SprintAssignment] = Field(..., description="Tasks in this sprint")
    total_estimated_days: float = Field(..., description="Total estimated days for tasks")
    capacity_days: float = Field(..., description="Sprint capacity in days")
    utilization_percent: float = Field(..., description="Capacity utilization percentage")


class TimelineResponse(BaseModel):
    """Timeline with scheduled sprints and dates"""
    epic_key: str = Field(..., description="Epic key")
    board_id: int = Field(..., description="Board ID")
    start_date: str = Field(..., description="Timeline start date")
    sprint_duration_days: int = Field(..., description="Sprint duration")
    sprints: List[SprintTimelineItem] = Field(..., description="Sprint timeline items")
    total_sprints: int = Field(..., description="Total number of sprints")
    total_tasks: int = Field(..., description="Total number of tasks")
    estimated_completion_date: Optional[str] = Field(None, description="Estimated completion date")
    errors: List[str] = Field(default_factory=list, description="Any errors encountered")
    warnings: List[str] = Field(default_factory=list, description="Any warnings")

