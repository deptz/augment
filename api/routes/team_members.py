"""
Team Member Routes
Endpoints for managing team members, teams, and boards
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
import logging

from ..models.team_members import (
    TeamMemberRequest,
    TeamMemberResponse,
    TeamRequest,
    TeamResponse,
    BoardRequest,
    BoardResponse,
    RoleCapacityResponse
)
from ..auth import get_current_user
from src.team_member_service import TeamMemberService

router = APIRouter()
logger = logging.getLogger(__name__)


def get_team_service() -> TeamMemberService:
    """Get team member service instance"""
    return TeamMemberService()


@router.get("/team-members",
         tags=["Team Management"],
         response_model=List[TeamMemberResponse],
         summary="List team members",
         description="Get list of team members, optionally filtered by team or level")
async def list_team_members(
    team_id: Optional[int] = Query(None, description="Filter by team ID"),
    level: Optional[str] = Query(None, description="Filter by career level"),
    active_only: bool = Query(True, description="Show only active members"),
    current_user: str = Depends(get_current_user)
):
    """List team members"""
    service = get_team_service()
    
    try:
        logger.info(f"User {current_user} listing team members")
        members = service.get_members(team_id=team_id, level=level, active_only=active_only)
        
        return [TeamMemberResponse(**member) for member in members]
        
    except Exception as e:
        logger.error(f"Error listing team members: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list team members: {str(e)}")


@router.get("/team-members/{member_id}",
         tags=["Team Management"],
         response_model=TeamMemberResponse,
         summary="Get team member details",
         description="Get detailed information about a specific team member")
async def get_team_member(
    member_id: int,
    current_user: str = Depends(get_current_user)
):
    """Get team member details"""
    service = get_team_service()
    
    try:
        logger.info(f"User {current_user} getting team member {member_id}")
        member = service.get_member(member_id)
        
        if not member:
            raise HTTPException(status_code=404, detail=f"Team member {member_id} not found")
        
        return TeamMemberResponse(**member)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting team member: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get team member: {str(e)}")


@router.post("/team-members",
          tags=["Team Management"],
          response_model=TeamMemberResponse,
          summary="Create team member",
          description="Create a new team member and assign to teams")
async def create_team_member(
    request: TeamMemberRequest,
    current_user: str = Depends(get_current_user)
):
    """Create team member"""
    service = get_team_service()
    
    try:
        logger.info(f"User {current_user} creating team member {request.email}")
        member = service.create_member(
            name=request.name,
            email=request.email,
            level=request.level,
            capacity_days_per_sprint=request.capacity_days_per_sprint,
            team_ids=request.team_ids,
            roles=request.roles
        )
        
        return TeamMemberResponse(**member)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating team member: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create team member: {str(e)}")


@router.put("/team-members/{member_id}",
         tags=["Team Management"],
         response_model=TeamMemberResponse,
         summary="Update team member",
         description="Update team member information")
async def update_team_member(
    member_id: int,
    request: TeamMemberRequest,
    current_user: str = Depends(get_current_user)
):
    """Update team member"""
    service = get_team_service()
    
    try:
        logger.info(f"User {current_user} updating team member {member_id}")
        
        # Update basic fields
        update_data = {
            'name': request.name,
            'email': request.email,
            'level': request.level,
            'capacity_days_per_sprint': request.capacity_days_per_sprint
        }
        member = service.update_member(member_id, **update_data)
        
        # Update team assignments
        if request.team_ids:
            service.assign_member_to_teams(member_id, request.team_ids, request.roles)
        
        return TeamMemberResponse(**member)
        
    except Exception as e:
        logger.error(f"Error updating team member: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update team member: {str(e)}")


@router.delete("/team-members/{member_id}",
            tags=["Team Management"],
            summary="Delete team member",
            description="Soft delete a team member (sets is_active=false)")
async def delete_team_member(
    member_id: int,
    current_user: str = Depends(get_current_user)
):
    """Delete team member (soft delete)"""
    service = get_team_service()
    
    try:
        logger.info(f"User {current_user} deleting team member {member_id}")
        success = service.delete_member(member_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Team member {member_id} not found")
        
        return {"success": True, "message": f"Team member {member_id} deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting team member: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete team member: {str(e)}")


@router.get("/team-members/roles",
         tags=["Team Management"],
         summary="Get list of all roles",
         description="Get list of all team roles (teams)")
async def get_all_roles(
    current_user: str = Depends(get_current_user)
):
    """Get all roles (teams)"""
    service = get_team_service()
    
    try:
        teams = service.get_teams(active_only=True)
        return [{"id": team['id'], "name": team['name']} for team in teams]
        
    except Exception as e:
        logger.error(f"Error getting roles: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get roles: {str(e)}")


@router.get("/team-members/levels",
         tags=["Team Management"],
         summary="Get list of all career levels",
         description="Get list of all career levels")
async def get_all_levels(
    current_user: str = Depends(get_current_user)
):
    """Get all career levels"""
    service = get_team_service()
    
    try:
        levels = service.get_all_levels()
        return {"levels": levels}
        
    except Exception as e:
        logger.error(f"Error getting levels: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get levels: {str(e)}")


@router.get("/team-members/role/{role_id}/capacity",
         tags=["Team Management"],
         response_model=RoleCapacityResponse,
         summary="Get role capacity",
         description="Get total capacity for a role (team)")
async def get_role_capacity(
    role_id: int,
    board_id: Optional[int] = Query(None, description="Filter by board ID"),
    current_user: str = Depends(get_current_user)
):
    """Get role capacity"""
    service = get_team_service()
    
    try:
        team = service.get_team(role_id)
        if not team:
            raise HTTPException(status_code=404, detail=f"Team {role_id} not found")
        
        capacity = service.get_team_capacity(role_id, board_id)
        members = service.get_members(team_id=role_id, active_only=True)
        
        return RoleCapacityResponse(
            role_id=role_id,
            role_name=team['name'],
            total_capacity_days=capacity,
            active_members=len(members),
            board_id=board_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting role capacity: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get role capacity: {str(e)}")


