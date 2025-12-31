"""
Bulk Creation Routes
Endpoints for bulk ticket creation operations
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Union
import logging
import uuid
from datetime import datetime

from ..models.bulk_creation import (
    BulkTicketCreationRequest,
    BulkCreationResponse,
    StoryCreationRequest,
    TaskCreationRequest
)
from ..models.generation import BatchResponse, JobStatus
from ..dependencies import get_generator, get_active_job_for_ticket, register_ticket_job, jobs
from ..job_queue import get_redis_pool
from ..auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/plan/epic/create", 
         tags=["Bulk Creation"],
         response_model=Union[BulkCreationResponse, BatchResponse],
         summary="Execute planning and create tickets",
         description="Execute complete planning workflow and optionally create JIRA tickets. Preview mode by default. Includes validation and error recovery. Supports async_mode for background processing.")
async def execute_planning_with_creation(
    request: BulkTicketCreationRequest,
    current_user: str = Depends(get_current_user)
):
    """Execute complete planning workflow and optionally create tickets"""
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} executing planning with creation for {request.epic_key} (create_tickets={request.create_tickets}, async_mode={request.async_mode})")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
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
                job_type="epic_creation",
                status="started",
                progress={"message": f"Queued for planning and creation for epic {request.epic_key}"},
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
                'process_epic_creation_worker',
                job_id=job_id,
                epic_key=request.epic_key,
                operation_mode=request.operation_mode,
                create_tickets=request.create_tickets,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued epic creation job {job_id} for epic {request.epic_key}")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Epic planning and creation queued for {request.epic_key}",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=1,
                update_jira=request.create_tickets,
                safety_note="JIRA will only be updated if create_tickets is true"
            )
        
        # Synchronous mode - execute planning with creation
        # Create planning context
        from src.planning_models import PlanningContext, OperationMode
        
        mode_map = {
            "documentation": OperationMode.DOCUMENTATION,
            "planning": OperationMode.PLANNING,
            "hybrid": OperationMode.HYBRID
        }
        
        context = PlanningContext(
            epic_key=request.epic_key,
            mode=mode_map.get(request.operation_mode, OperationMode.HYBRID),
            include_analysis=True,
            max_stories_per_epic=20,
            max_tasks_per_story=8
        )
        
        # Execute planning with creation
        results = generator.planning_service.execute_planning_with_creation(
            context, 
            create_tickets=request.create_tickets
        )
        
        # Convert to API response
        response = BulkCreationResponse(
            epic_key=results["epic_key"],
            create_tickets=results["create_tickets"],
            success=results["success"],
            planning_results=results["planning_results"],
            creation_results=results["creation_results"],
            rollback_info=results.get("rollback_info"),
            errors=results["errors"],
            execution_time_seconds=results["execution_time_seconds"],
            job_id=None,
            status_url=None
        )
        
        logger.info(f"Planning with creation completed for {request.epic_key}: {response.success}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in planning with creation for {request.epic_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to execute planning with creation: {str(e)}")


@router.post("/plan/stories/create", 
         tags=["Bulk Creation"],
         response_model=Dict[str, Any],
         summary="Generate and create stories for epic",
         description="Generate and optionally create story tickets for an epic with acceptance criteria. Preview mode by default. Supports async_mode for background processing.")
async def create_stories_for_epic(
    request: StoryCreationRequest,
    current_user: str = Depends(get_current_user)
):
    """Generate and create stories for an epic"""
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} creating stories for epic {request.epic_key} (async_mode={request.async_mode})")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available"
            )
        
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
                job_type="story_creation",
                status="started",
                progress={"message": f"Queued for creating stories for epic {request.epic_key}"},
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
                'process_story_creation_worker',
                job_id=job_id,
                epic_key=request.epic_key,
                story_count=request.story_count,
                create_tickets=request.create_tickets,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued story creation job {job_id} for epic {request.epic_key}")
            
            return {
                "job_id": job_id,
                "status": "started",
                "message": f"Story creation queued for epic {request.epic_key}",
                "status_url": f"/jobs/{job_id}",
                "epic_key": request.epic_key
            }
        
        # Synchronous mode - generate and create stories
        # Generate stories first
        from src.planning_models import PlanningContext, OperationMode
        
        context = PlanningContext(
            epic_key=request.epic_key,
            mode=OperationMode.PLANNING,
            max_stories_per_epic=request.story_count or 5
        )
        
        planning_result = generator.planning_service.generate_stories_for_epic(context)
        
        if not planning_result.success or not planning_result.epic_plan:
            return {
                "success": False,
                "errors": planning_result.errors,
                "epic_key": request.epic_key
            }
        
        # Create stories if requested
        creation_results = generator.planning_service.create_stories_for_epic(
            request.epic_key,
            planning_result.epic_plan.stories,
            dry_run=not request.create_tickets
        )
        
        return {
            "epic_key": request.epic_key,
            "planning_results": planning_result.dict(),
            "creation_results": creation_results,
            "success": creation_results["success"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating stories for epic {request.epic_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create stories: {str(e)}")


@router.post("/plan/tasks/create", 
         tags=["Bulk Creation"],
         response_model=Dict[str, Any],
         summary="Generate and create tasks for stories",
         description="Generate and optionally create task tickets for stories with cycle time estimates. Validates cycle time constraints. Preview mode by default. Supports async_mode for background processing.")
async def create_tasks_for_stories(
    request: TaskCreationRequest,
    current_user: str = Depends(get_current_user)
):
    """Generate and create tasks for stories"""
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} creating tasks for stories {request.story_keys} (async_mode={request.async_mode})")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available"
            )
        
        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active jobs on story keys
            duplicate_stories = []
            active_duplicates = {}
            for story_key in request.story_keys:
                active_job_id = get_active_job_for_ticket(story_key)
                if active_job_id:
                    duplicate_stories.append(story_key)
                    active_duplicates[story_key] = active_job_id
                    logger.warning(f"Skipping story {story_key} - already being processed in job {active_job_id}")
            
            if duplicate_stories:
                # Return error with details about duplicates
                raise HTTPException(
                    status_code=409,
                    detail=f"Some stories are already being processed: {', '.join(duplicate_stories)}",
                    headers={"X-Duplicate-Stories": ",".join(duplicate_stories)}
                )
            
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="task_creation",
                status="started",
                progress={"message": f"Queued for creating tasks for {len(request.story_keys)} stories"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                story_keys=request.story_keys.copy()
            )
            
            # Register all story keys for duplicate prevention
            for story_key in request.story_keys:
                register_ticket_job(story_key, job_id)
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_task_creation_worker',
                job_id=job_id,
                story_keys=request.story_keys,
                tasks_per_story=request.tasks_per_story,
                create_tickets=request.create_tickets,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued task creation job {job_id} for {len(request.story_keys)} stories")
            
            return {
                "job_id": job_id,
                "status": "started",
                "message": f"Task creation queued for {len(request.story_keys)} stories",
                "status_url": f"/jobs/{job_id}",
                "story_keys": request.story_keys
            }
        
        # Synchronous mode - generate and create tasks
        # Generate tasks first
        from src.planning_models import PlanningContext, OperationMode
        
        context = PlanningContext(
            epic_key=request.story_keys[0].split('-')[0] + "-000",  # Approximate epic
            mode=OperationMode.PLANNING,
            max_tasks_per_story=request.tasks_per_story or 3
        )
        
        planning_result = generator.planning_service.generate_tasks_for_stories(
            request.story_keys, context
        )
        
        if not planning_result.success or not planning_result.epic_plan:
            return {
                "success": False,
                "errors": planning_result.errors,
                "story_keys": request.story_keys
            }
        
        # Extract all tasks from stories
        all_tasks = []
        for story in planning_result.epic_plan.stories:
            all_tasks.extend(story.tasks)
        
        # Create tasks if requested
        creation_results = generator.planning_service.create_tasks_for_stories(
            all_tasks,
            request.story_keys,
            dry_run=not request.create_tickets
        )
        
        return {
            "story_keys": request.story_keys,
            "planning_results": planning_result.dict(),
            "creation_results": creation_results,
            "success": creation_results["success"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating tasks for stories {request.story_keys}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create tasks: {str(e)}")


@router.get("/plan/validate/{epic_key}", 
         tags=["Bulk Creation"],
         response_model=Dict[str, Any],
         summary="Validate epic structure integrity",
         description="""
         Validate epic structure: check story-epic links, task-story relationships, and relationship consistency.
         """)
async def validate_epic_structure(
    epic_key: str,
    current_user: str = Depends(get_current_user)
):
    """Validate epic structure integrity"""
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} validating epic structure for {epic_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available"
            )
        
        validation_results = generator.planning_service.validate_epic_structure(epic_key)
        
        return {
            "epic_key": epic_key,
            "validation_results": validation_results,
            "success": validation_results.get("valid", False)
        }
        
    except Exception as e:
        logger.error(f"Error validating epic structure {epic_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to validate structure: {str(e)}")
