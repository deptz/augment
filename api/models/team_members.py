"""
Team Member Models
Request and response models for team member management endpoints
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class TeamMemberRequest(BaseModel):
    """Request model for creating/updating team member"""
    name: str = Field(..., description="Member name")
    email: str = Field(..., description="Member email (unique)")
    level: str = Field(..., description="Career level (Junior, Mid, Senior, Lead, Principal)")
    capacity_days_per_sprint: float = Field(default=5.0, description="Available days per sprint")
    team_ids: List[int] = Field(default_factory=list, description="Team IDs to assign member to")
    roles: Optional[List[str]] = Field(None, description="Optional roles within each team")


class TeamMemberResponse(BaseModel):
    """Response model for team member details"""
    id: int = Field(..., description="Member ID")
    name: str = Field(..., description="Member name")
    email: str = Field(..., description="Member email")
    level: str = Field(..., description="Career level")
    capacity_days_per_sprint: float = Field(..., description="Available days per sprint")
    is_active: bool = Field(..., description="Whether member is active")
    teams: List[Dict[str, Any]] = Field(default_factory=list, description="Teams member belongs to")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class TeamRequest(BaseModel):
    """Request model for creating/updating team"""
    name: str = Field(..., description="Team name (unique)")
    description: Optional[str] = Field(None, description="Team description")
    board_ids: List[int] = Field(default_factory=list, description="Board IDs to assign team to")


class TeamResponse(BaseModel):
    """Response model for team details"""
    id: int = Field(..., description="Team ID")
    name: str = Field(..., description="Team name")
    description: Optional[str] = Field(None, description="Team description")
    is_active: bool = Field(..., description="Whether team is active")
    members: List[Dict[str, Any]] = Field(default_factory=list, description="Team members")
    boards: List[Dict[str, Any]] = Field(default_factory=list, description="Boards team is assigned to")
    member_count: Optional[int] = Field(None, description="Number of active members")
    board_count: Optional[int] = Field(None, description="Number of assigned boards")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class BoardRequest(BaseModel):
    """Request model for creating/updating board"""
    jira_board_id: int = Field(..., description="JIRA board ID")
    name: str = Field(..., description="Board name")
    project_key: Optional[str] = Field(None, description="JIRA project key")
    team_ids: List[int] = Field(default_factory=list, description="Team IDs to assign to board")


class BoardResponse(BaseModel):
    """Response model for board details"""
    id: int = Field(..., description="Board ID")
    jira_board_id: int = Field(..., description="JIRA board ID")
    name: str = Field(..., description="Board name")
    project_key: Optional[str] = Field(None, description="JIRA project key")
    is_active: bool = Field(..., description="Whether board is active")
    teams: List[Dict[str, Any]] = Field(default_factory=list, description="Teams assigned to board")
    created_at: Optional[str] = Field(None, description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")


class RoleCapacityResponse(BaseModel):
    """Response model for role capacity information"""
    role_id: int = Field(..., description="Team ID")
    role_name: str = Field(..., description="Team name")
    total_capacity_days: float = Field(..., description="Total capacity in days")
    active_members: int = Field(..., description="Number of active members")
    board_id: Optional[int] = Field(None, description="Board ID if filtered by board")


