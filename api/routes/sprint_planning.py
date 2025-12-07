"""
Sprint Planning Routes
Endpoints for sprint planning and timeline management
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional, Union
import logging

from ..models.sprint_planning import (
    SprintInfo,
    SprintCapacityRequest,
    SprintAssignmentRequest,
    SprintPlanningRequest,
    SprintPlanningResponse,
    TimelineRequest,
    TimelineResponse
)
from ..models.generation import BatchResponse, JobStatus
from ..dependencies import get_jira_client, get_active_job_for_ticket, register_ticket_job
from ..auth import get_current_user
from src.sprint_planning_service import SprintPlanningService
from src.team_member_service import TeamMemberService

router = APIRouter()
logger = logging.getLogger(__name__)


def get_sprint_planning_service() -> SprintPlanningService:
    """Get sprint planning service instance"""
    jira_client = get_jira_client()
    team_service = TeamMemberService()
    return SprintPlanningService(jira_client, team_service)


@router.get("/sprint/board/{board_id}/sprints",
         tags=["Sprint Planning"],
         response_model=List[SprintInfo],
         summary="List sprints for a board",
         description="Get all sprints for a JIRA board, optionally filtered by state")
async def list_board_sprints(
    board_id: int,
    state: Optional[str] = None,
    current_user: str = Depends(get_current_user)
):
    """List sprints for a board"""
    jira_client = get_jira_client()
    
    try:
        logger.info(f"User {current_user} listing sprints for board {board_id}")
        sprints = jira_client.get_board_sprints(board_id, state)
        
        sprint_infos = []
        for sprint in sprints:
            sprint_infos.append(SprintInfo(
                id=sprint.get('id'),
                name=sprint.get('name', ''),
                state=sprint.get('state', 'active'),
                start_date=sprint.get('startDate'),
                end_date=sprint.get('endDate'),
                board_id=sprint.get('originBoardId'),
                goal=sprint.get('goal'),
                complete_date=sprint.get('completeDate')
            ))
        
        return sprint_infos
        
    except Exception as e:
        logger.error(f"Error listing sprints for board {board_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list sprints: {str(e)}")


@router.get("/sprint/{sprint_id}",
         tags=["Sprint Planning"],
         response_model=SprintInfo,
         summary="Get sprint details",
         description="Get detailed information about a specific sprint")
async def get_sprint(
    sprint_id: int,
    current_user: str = Depends(get_current_user)
):
    """Get sprint details"""
    jira_client = get_jira_client()
    
    try:
        logger.info(f"User {current_user} getting sprint {sprint_id}")
        sprint = jira_client.get_sprint(sprint_id)
        
        return SprintInfo(
            id=sprint.get('id'),
            name=sprint.get('name', ''),
            state=sprint.get('state', 'active'),
            start_date=sprint.get('startDate'),
            end_date=sprint.get('endDate'),
            board_id=sprint.get('originBoardId'),
            goal=sprint.get('goal'),
            complete_date=sprint.get('completeDate')
        )
        
    except Exception as e:
        logger.error(f"Error getting sprint {sprint_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get sprint: {str(e)}")


@router.post("/sprint/create",
          tags=["Sprint Planning"],
          response_model=SprintInfo,
          summary="Create new sprint",
          description="Create a new sprint on a board")
async def create_sprint(
    name: str,
    board_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: str = Depends(get_current_user)
):
    """Create a new sprint"""
    jira_client = get_jira_client()
    
    try:
        logger.info(f"User {current_user} creating sprint {name} on board {board_id}")
        sprint = jira_client.create_sprint(name, board_id, start_date, end_date)
        
        return SprintInfo(
            id=sprint.get('id'),
            name=sprint.get('name', ''),
            state=sprint.get('state', 'active'),
            start_date=sprint.get('startDate'),
            end_date=sprint.get('endDate'),
            board_id=sprint.get('originBoardId'),
            goal=sprint.get('goal'),
            complete_date=sprint.get('completeDate')
        )
        
    except Exception as e:
        logger.error(f"Error creating sprint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create sprint: {str(e)}")


@router.put("/sprint/{sprint_id}",
         tags=["Sprint Planning"],
         response_model=SprintInfo,
         summary="Update sprint",
         description="Update sprint details (name, dates, state)")
async def update_sprint(
    sprint_id: int,
    name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    state: Optional[str] = None,
    current_user: str = Depends(get_current_user)
):
    """Update sprint"""
    jira_client = get_jira_client()
    
    try:
        logger.info(f"User {current_user} updating sprint {sprint_id}")
        sprint = jira_client.update_sprint(sprint_id, name, start_date, end_date, state)
        
        return SprintInfo(
            id=sprint.get('id'),
            name=sprint.get('name', ''),
            state=sprint.get('state', 'active'),
            start_date=sprint.get('startDate'),
            end_date=sprint.get('endDate'),
            board_id=sprint.get('originBoardId'),
            goal=sprint.get('goal'),
            complete_date=sprint.get('completeDate')
        )
        
    except Exception as e:
        logger.error(f"Error updating sprint {sprint_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update sprint: {str(e)}")


@router.post("/sprint/{sprint_id}/assign",
          tags=["Sprint Planning"],
          summary="Assign tickets to sprint",
          description="Assign one or more tickets to a sprint. Preview mode by default.")
async def assign_tickets_to_sprint(
    request: SprintAssignmentRequest,
    current_user: str = Depends(get_current_user)
):
    """Assign tickets to sprint"""
    sprint_service = get_sprint_planning_service()
    
    try:
        logger.info(f"User {current_user} assigning {len(request.issue_keys)} tickets to sprint {request.sprint_id}")
        
        if request.dry_run:
            logger.info(f"DRY RUN: Would assign tickets {request.issue_keys} to sprint {request.sprint_id}")
            return {
                "success": True,
                "sprint_id": request.sprint_id,
                "issue_keys": request.issue_keys,
                "assigned_in_jira": False,
                "message": "Preview: Tickets would be assigned. Set dry_run=false to commit."
            }
        
        success = sprint_service.assign_tickets_to_sprint(
            request.issue_keys,
            request.sprint_id,
            dry_run=False
        )
        
        return {
            "success": success,
            "sprint_id": request.sprint_id,
            "issue_keys": request.issue_keys,
            "assigned_in_jira": success,
            "message": f"Successfully assigned {len(request.issue_keys)} tickets to sprint {request.sprint_id}" if success else "Failed to assign tickets"
        }
        
    except Exception as e:
        logger.error(f"Error assigning tickets to sprint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to assign tickets: {str(e)}")


@router.post("/sprint/{sprint_id}/remove",
          tags=["Sprint Planning"],
          summary="Remove tickets from sprint",
          description="Remove tickets from their current sprint (move to backlog)")
async def remove_tickets_from_sprint(
    issue_keys: List[str],
    sprint_id: int,
    current_user: str = Depends(get_current_user)
):
    """Remove tickets from sprint"""
    jira_client = get_jira_client()
    
    try:
        logger.info(f"User {current_user} removing {len(issue_keys)} tickets from sprint")
        success = jira_client.remove_issues_from_sprint(issue_keys)
        
        return {
            "success": success,
            "issue_keys": issue_keys,
            "message": f"Successfully removed {len(issue_keys)} tickets from sprint" if success else "Failed to remove tickets"
        }
        
    except Exception as e:
        logger.error(f"Error removing tickets from sprint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to remove tickets: {str(e)}")


@router.get("/sprint/{sprint_id}/issues",
         tags=["Sprint Planning"],
         summary="Get sprint issues",
         description="Get all issues currently in a sprint")
async def get_sprint_issues(
    sprint_id: int,
    current_user: str = Depends(get_current_user)
):
    """Get sprint issues"""
    jira_client = get_jira_client()
    
    try:
        logger.info(f"User {current_user} getting issues for sprint {sprint_id}")
        issues = jira_client.get_sprint_issues(sprint_id)
        
        return {
            "sprint_id": sprint_id,
            "total_issues": len(issues),
            "issues": issues
        }
        
    except Exception as e:
        logger.error(f"Error getting sprint issues: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get sprint issues: {str(e)}")


@router.post("/sprint/plan/epic",
          tags=["Sprint Planning"],
          response_model=Union[SprintPlanningResponse, BatchResponse],
          summary="Plan epic tasks to sprints",
          description="Plan epic tasks across sprints based on capacity and dependencies. Preview mode by default. Use async_mode=true for background processing.")
async def plan_epic_to_sprints(
    request: SprintPlanningRequest,
    current_user: str = Depends(get_current_user)
):
    """Plan epic tasks to sprints"""
    from ..job_queue import get_redis_pool
    from ..dependencies import jobs
    from datetime import datetime
    import uuid
    
    sprint_service = get_sprint_planning_service()
    
    try:
        logger.info(f"User {current_user} planning epic {request.epic_key} to sprints")
        
        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active job
            active_job_id = get_active_job_for_ticket(request.epic_key)
            if active_job_id:
                active_job = jobs[active_job_id]
                raise HTTPException(
                    status_code=409,
                    detail=f"Epic {request.epic_key} is already being processed in job {active_job_id}",
                    headers={"X-Active-Job-Id": active_job_id, "X-Active-Job-Status-Url": f"/jobs/{active_job_id}"}
                )
            
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="sprint_planning",
                status="started",
                progress={"message": f"Queued for sprint planning for epic {request.epic_key}"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                ticket_key=request.epic_key
            )
            
            # Register epic key for duplicate prevention
            register_ticket_job(request.epic_key, job_id)
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_sprint_planning_worker',
                job_id=job_id,
                epic_key=request.epic_key,
                board_id=request.board_id,
                sprint_capacity_days=request.sprint_capacity_days,
                start_date=request.start_date,
                sprint_duration_days=request.sprint_duration_days,
                team_id=request.team_id,
                auto_create_sprints=request.auto_create_sprints,
                dry_run=request.dry_run,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued sprint planning job {job_id} for epic {request.epic_key}")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Sprint planning for epic {request.epic_key} queued",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=0,
                update_jira=not request.dry_run,
                safety_note="JIRA will only be updated if dry_run is false"
            )
        
        # Synchronous mode
        result = sprint_service.plan_epic_to_sprints(
            epic_key=request.epic_key,
            board_id=request.board_id,
            sprint_capacity_days=request.sprint_capacity_days,
            start_date=request.start_date,
            sprint_duration_days=request.sprint_duration_days,
            team_id=request.team_id,
            auto_create_sprints=request.auto_create_sprints,
            dry_run=request.dry_run
        )
        
        # Convert to response model
        assignments = [SprintAssignment(**a) for a in result.get('assignments', [])]
        sprints_created = [SprintInfo(**s) for s in result.get('sprints_created', [])]
        
        return SprintPlanningResponse(
            epic_key=result['epic_key'],
            board_id=result['board_id'],
            success=result['success'],
            assignments=assignments,
            sprints_created=sprints_created,
            total_tasks=result['total_tasks'],
            total_sprints=result['total_sprints'],
            capacity_utilization=result.get('capacity_utilization', {}),
            errors=result.get('errors', []),
            warnings=result.get('warnings', [])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error planning epic to sprints: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to plan epic: {str(e)}")


@router.post("/sprint/timeline",
          tags=["Sprint Planning"],
          response_model=Union[TimelineResponse, BatchResponse],
          summary="Create timeline schedule for epic",
          description="Create a timeline view showing when tasks will be completed across sprints. Preview mode by default. Use async_mode=true for background processing.")
async def create_timeline(
    request: TimelineRequest,
    current_user: str = Depends(get_current_user)
):
    """Create timeline schedule"""
    from ..job_queue import get_redis_pool
    from ..dependencies import jobs
    from datetime import datetime
    import uuid
    
    sprint_service = get_sprint_planning_service()
    
    try:
        logger.info(f"User {current_user} creating timeline for epic {request.epic_key}")
        
        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active job
            active_job_id = get_active_job_for_ticket(request.epic_key)
            if active_job_id:
                active_job = jobs[active_job_id]
                raise HTTPException(
                    status_code=409,
                    detail=f"Epic {request.epic_key} is already being processed in job {active_job_id}",
                    headers={"X-Active-Job-Id": active_job_id, "X-Active-Job-Status-Url": f"/jobs/{active_job_id}"}
                )
            
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="timeline_planning",
                status="started",
                progress={"message": f"Queued for timeline creation for epic {request.epic_key}"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                ticket_key=request.epic_key
            )
            
            # Register epic key for duplicate prevention
            register_ticket_job(request.epic_key, job_id)
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_timeline_planning_worker',
                job_id=job_id,
                epic_key=request.epic_key,
                board_id=request.board_id,
                start_date=request.start_date,
                sprint_duration_days=request.sprint_duration_days,
                team_capacity_days=request.team_capacity_days,
                team_id=request.team_id,
                dry_run=request.dry_run,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued timeline planning job {job_id} for epic {request.epic_key}")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Timeline planning for epic {request.epic_key} queued",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=0,
                update_jira=not request.dry_run,
                safety_note="JIRA will only be updated if dry_run is false"
            )
        
        # Synchronous mode
        result = sprint_service.schedule_timeline(
            epic_key=request.epic_key,
            board_id=request.board_id,
            start_date=request.start_date,
            sprint_duration_days=request.sprint_duration_days,
            team_capacity_days=request.team_capacity_days,
            team_id=request.team_id,
            dry_run=request.dry_run
        )
        
        # Convert to response model
        sprint_items = []
        for sprint_data in result.get('sprints', []):
            tasks = [SprintAssignment(**t) for t in sprint_data.get('tasks', [])]
            sprint_items.append(SprintTimelineItem(
                sprint_id=sprint_data.get('sprint_id'),
                sprint_name=sprint_data.get('sprint_name', ''),
                start_date=sprint_data.get('start_date', ''),
                end_date=sprint_data.get('end_date', ''),
                tasks=tasks,
                total_estimated_days=sprint_data.get('total_estimated_days', 0.0),
                capacity_days=sprint_data.get('capacity_days', 0.0),
                utilization_percent=sprint_data.get('utilization_percent', 0.0)
            ))
        
        return TimelineResponse(
            epic_key=result['epic_key'],
            board_id=result['board_id'],
            start_date=result['start_date'],
            sprint_duration_days=result['sprint_duration_days'],
            sprints=sprint_items,
            total_sprints=result['total_sprints'],
            total_tasks=result['total_tasks'],
            estimated_completion_date=result.get('estimated_completion_date'),
            errors=result.get('errors', []),
            warnings=result.get('warnings', [])
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating timeline: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create timeline: {str(e)}")


@router.get("/sprint/timeline/{epic_key}",
         tags=["Sprint Planning"],
         response_model=TimelineResponse,
         summary="Get timeline for epic",
         description="Get existing timeline for an epic")
async def get_timeline(
    epic_key: str,
    board_id: int,
    current_user: str = Depends(get_current_user)
):
    """Get timeline for epic"""
    # This would retrieve a stored timeline
    # For now, return error as this needs to be implemented with storage
    raise HTTPException(
        status_code=501,
        detail="Timeline retrieval not yet implemented. Use POST /sprint/timeline to create a timeline."
    )

