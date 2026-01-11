"""
Planning Routes
Endpoints for planning operations (epic analysis, story/task generation)
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Union
import logging

from ..models.planning import (
    EpicPlanRequest,
    StoryGenerationRequest,
    TaskGenerationRequest,
    EpicAnalysisResponse,
    PlanningResultResponse,
    CycleTimeEstimateResponse,
    PRDStorySyncRequest,
    PRDStorySyncResponse
)
from ..models.generation import BatchResponse
from ..dependencies import get_generator, get_jira_client, get_config, get_active_job_for_ticket, register_ticket_job, unregister_ticket_job
from ..utils import create_custom_llm_client, extract_story_details_with_tests, extract_task_details_with_tests, parse_story_keys_from_input, normalize_ticket_key
from ..auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/plan/epic/{epic_key}/analyze", 
         tags=["Planning"],
         response_model=EpicAnalysisResponse,
         summary="Analyze epic structure and identify gaps",
         description="Analyze an epic to find missing stories, incomplete stories, and orphaned tasks. Returns gap analysis with recommendations.")
async def analyze_epic_gaps(epic_key: str, current_user: str = Depends(get_current_user)):
    """Analyze epic structure and identify planning gaps"""
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} analyzing epic gaps for {epic_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        gap_analysis_result = generator.analyze_epic_gaps(epic_key)
        
        if "error" in gap_analysis_result:
            raise HTTPException(status_code=400, detail=gap_analysis_result["error"])
        
        return EpicAnalysisResponse(**gap_analysis_result)
        
    except Exception as e:
        logger.error(f"Error analyzing epic {epic_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze epic: {str(e)}")


@router.post("/plan/epic/complete", 
          tags=["Planning"],
          response_model=PlanningResultResponse,
          summary="Complete epic planning",
          description="Complete planning workflow: gap analysis, story generation, task breakdown, cycle time validation, and test case generation. Preview mode by default.")
async def plan_epic_complete(request: EpicPlanRequest, current_user: str = Depends(get_current_user)):
    """Complete planning for an epic - generate all missing stories and tasks"""
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} starting complete epic planning for {request.epic_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Create custom LLM client if provider/model specified
        custom_llm_client = None
        if request.llm_provider or request.llm_model:
            custom_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        planning_result = generator.plan_epic_complete(
            epic_key=request.epic_key,
            dry_run=request.dry_run,
            split_oversized_tasks=request.split_oversized_tasks,
            generate_test_cases=request.generate_test_cases,
            max_task_cycle_days=request.max_task_cycle_days
        )
        
        # Convert to API response format
        story_details = extract_story_details_with_tests(planning_result, generate_test_cases=request.generate_test_cases)
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=request.generate_test_cases)
        
        response = PlanningResultResponse(
            epic_key=planning_result.epic_key,
            operation_mode=planning_result.mode.value,
            success=planning_result.success,
            created_tickets=planning_result.created_tickets,
            story_details=story_details,
            task_details=task_details,
            summary_stats=planning_result.summary_stats,
            errors=planning_result.errors,
            warnings=planning_result.warnings,
            execution_time_seconds=planning_result.execution_time_seconds
        )
        
        logger.info(f"Epic planning completed for {request.epic_key}: {response.success}")
        return response
        
    except Exception as e:
        logger.error(f"Error in complete epic planning for {request.epic_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to plan epic: {str(e)}")


@router.post("/plan/stories/generate", 
          tags=["Planning"],
          response_model=Union[PlanningResultResponse, BatchResponse],
          summary="Generate stories for an epic",
          description="Generate missing stories from PRD/RFC requirements with acceptance criteria and test cases. Preview mode by default. Set dry_run=false to create tickets.")
async def generate_stories_for_epic(request: StoryGenerationRequest, current_user: str = Depends(get_current_user)):
    """Generate stories for an epic based on requirements"""
    from ..job_queue import get_redis_pool
    from ..models.generation import BatchResponse, JobStatus
    from datetime import datetime
    import uuid
    
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} generating stories for epic {request.epic_key}")
        
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
                from ..dependencies import jobs
                active_job = jobs[active_job_id]
                raise HTTPException(
                    status_code=409,
                    detail=f"Epic {request.epic_key} is already being processed in job {active_job_id}",
                    headers={"X-Active-Job-Id": active_job_id, "X-Active-Job-Status-Url": f"/jobs/{active_job_id}"}
                )
            
            job_id = str(uuid.uuid4())
            
            from ..dependencies import jobs
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="story_generation",
                status="started",
                progress={"message": f"Queued for generating stories for epic {request.epic_key}"},
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
                'process_story_generation_worker',
                job_id=job_id,
                epic_key=request.epic_key,
                dry_run=request.dry_run,
                llm_model=request.llm_model,
                llm_provider=request.llm_provider,
                generate_test_cases=request.generate_test_cases,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued story generation job {job_id} for epic {request.epic_key}")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Story generation for epic {request.epic_key} queued",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=0,
                update_jira=not request.dry_run,
                safety_note="JIRA will only be updated if dry_run is false"
            )
        
        # Synchronous mode (original behavior)
        custom_llm_client = None
        if request.llm_provider or request.llm_model:
            custom_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        planning_result = generator.generate_stories_for_epic(
            epic_key=request.epic_key,
            dry_run=request.dry_run,
            generate_test_cases=request.generate_test_cases
        )
        
        # Convert to API response format
        story_details = extract_story_details_with_tests(planning_result, generate_test_cases=request.generate_test_cases)
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=request.generate_test_cases)
        
        response = PlanningResultResponse(
            epic_key=planning_result.epic_key,
            operation_mode=planning_result.mode.value,
            success=planning_result.success,
            created_tickets=planning_result.created_tickets,
            story_details=story_details,
            task_details=task_details,
            summary_stats=planning_result.summary_stats,
            errors=planning_result.errors,
            warnings=planning_result.warnings,
            execution_time_seconds=planning_result.execution_time_seconds
        )
        
        logger.info(f"Story generation completed for {request.epic_key}: {response.success}")
        return response
        
    except Exception as e:
        logger.error(f"Error generating stories for {request.epic_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate stories: {str(e)}")


@router.post("/plan/tasks/generate", 
          tags=["Planning"],
          response_model=Union[PlanningResultResponse, BatchResponse],
          summary="Generate tasks for stories",
          description="Generate tasks for stories with breakdown and custom LLM configuration. Supports both story keys and full JIRA URLs. Epic key is optional - if not provided, it will be derived from the story tickets' parent epic. Preview mode by default. Set dry_run=false to create tickets.")
async def generate_tasks_for_stories(request: TaskGenerationRequest, current_user: str = Depends(get_current_user)):
    """Generate tasks for specific stories"""
    from ..job_queue import get_redis_pool
    from ..models.generation import BatchResponse, JobStatus
    from ..dependencies import jobs
    from datetime import datetime
    import uuid
    
    generator = get_generator()
    config = get_config()
    jira_client = get_jira_client()
    
    try:
        # Parse story keys from URLs if needed
        story_keys = parse_story_keys_from_input(request.story_keys)
        if not story_keys:
            raise HTTPException(
                status_code=400,
                detail="No valid JIRA story keys found in the provided input"
            )
        
        logger.info(f"User {current_user} generating tasks for {len(story_keys)} stories: {story_keys}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Derive epic_key from story tickets if not provided
        epic_key = request.epic_key
        # Normalize epic_key if provided (might be a full URL)
        if epic_key:
            epic_key = normalize_ticket_key(epic_key)
            if not epic_key:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid epic_key format: {request.epic_key}. Please provide a valid JIRA epic key or URL."
                )
        
        if not epic_key:
            logger.info("No epic_key provided, deriving from story tickets...")
            
            # Fetch the first story to get its parent epic
            first_story_data = jira_client.get_ticket(story_keys[0])
            if not first_story_data:
                raise HTTPException(
                    status_code=404,
                    detail=f"Story ticket {story_keys[0]} not found in JIRA"
                )
            
            # Extract parent epic from story
            parent = first_story_data.get('fields', {}).get('parent')
            if parent and parent.get('key'):
                # Normalize parent key (should be just a key, but normalize to be safe)
                epic_key = normalize_ticket_key(parent['key'])
                if not epic_key:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid parent epic key format: {parent['key']}"
                    )
                logger.info(f"Derived epic_key from story {story_keys[0]}: {epic_key}")
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Story {story_keys[0]} has no parent epic. Please provide epic_key explicitly."
                )
        
        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active jobs per story
            duplicate_stories = []
            active_duplicates = {}
            for story_key in story_keys:
                active_job_id = get_active_job_for_ticket(story_key)
                if active_job_id:
                    duplicate_stories.append(story_key)
                    active_duplicates[story_key] = active_job_id
                    logger.warning(f"Skipping story {story_key} - already being processed in job {active_job_id}")
            
            if duplicate_stories:
                # Return error with details about which stories are duplicates
                duplicate_info = ", ".join([f"{sk} (job {active_duplicates[sk]})" for sk in duplicate_stories])
                raise HTTPException(
                    status_code=409,
                    detail=f"One or more stories are already being processed: {duplicate_info}",
                    headers={"X-Duplicate-Stories": ",".join(duplicate_stories)}
                )
            
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="task_generation",
                status="started",
                progress={"message": f"Queued for generating tasks for {len(story_keys)} stories"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                ticket_key=epic_key,
                story_keys=story_keys.copy()
            )
            
            # Register all story keys for duplicate prevention
            for story_key in story_keys:
                register_ticket_job(story_key, job_id)
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_task_generation_worker',
                job_id=job_id,
                story_keys=story_keys,
                epic_key=epic_key,
                dry_run=request.dry_run,
                split_oversized_tasks=request.split_oversized_tasks,
                max_task_cycle_days=request.max_task_cycle_days,
                llm_model=request.llm_model,
                llm_provider=request.llm_provider,
                additional_context=request.additional_context,
                generate_test_cases=request.generate_test_cases,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued task generation job {job_id} for {len(story_keys)} stories")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Task generation for {len(story_keys)} stories queued",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=len(story_keys),
                update_jira=not request.dry_run,
                safety_note="JIRA will only be updated if dry_run is false"
            )
        
        # Synchronous mode (original behavior)
        custom_llm_client = None
        if request.llm_provider or request.llm_model:
            custom_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        planning_result = generator.generate_tasks_for_stories(
            story_keys=story_keys,
            epic_key=epic_key,
            dry_run=request.dry_run,
            split_oversized_tasks=request.split_oversized_tasks,
            max_task_cycle_days=request.max_task_cycle_days,
            max_tasks_per_story=config.get_max_tasks_per_story(),
            custom_llm_client=custom_llm_client,
            additional_context=request.additional_context,
            generate_test_cases=request.generate_test_cases
        )
        
        # Convert to API response format
        story_details = extract_story_details_with_tests(planning_result, generate_test_cases=request.generate_test_cases)
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=request.generate_test_cases)
        
        response = PlanningResultResponse(
            epic_key=planning_result.epic_key,
            operation_mode=planning_result.mode.value,
            success=planning_result.success,
            created_tickets=planning_result.created_tickets,
            task_details=task_details,
            summary_stats=planning_result.summary_stats,
            errors=planning_result.errors,
            warnings=planning_result.warnings,
            execution_time_seconds=planning_result.execution_time_seconds,
            system_prompt=planning_result.system_prompt,
            user_prompt=planning_result.user_prompt,
            additional_context=request.additional_context
        )
        
        logger.info(f"Task generation completed for stories {story_keys}: {response.success}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating tasks for stories {request.story_keys}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate tasks: {str(e)}")


@router.get("/plan/estimate/{ticket_key}", 
         tags=["Planning"],
         response_model=CycleTimeEstimateResponse,
         summary="Get cycle time estimate for a ticket",
         description="Get cycle time estimate including development, testing, review, and deployment time. Includes confidence level and split recommendations for oversized tasks.")
async def estimate_cycle_time(ticket_key: str, current_user: str = Depends(get_current_user)):
    """Get cycle time estimate for a ticket"""
    generator = get_generator()
    jira_client = get_jira_client()
    
    try:
        logger.info(f"User {current_user} estimating cycle time for {ticket_key}")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Get ticket details
        ticket_data = jira_client.get_ticket(ticket_key)
        if not ticket_data:
            raise HTTPException(status_code=404, detail=f"Ticket {ticket_key} not found")
        
        ticket_summary = ticket_data.get('fields', {}).get('summary', '')
        
        # Generate estimate
        estimate = generator.planning_service.analysis_engine.estimate_cycle_time(ticket_summary)
        
        # Check if splitting is recommended
        split_recommendations = None
        if estimate.exceeds_limit:
            split_recommendations = generator.planning_service.analysis_engine.suggest_task_split(
                ticket_summary, estimate
            )
        
        response = CycleTimeEstimateResponse(
            ticket_key=ticket_key,
            development_days=estimate.development_days,
            testing_days=estimate.testing_days,
            review_days=estimate.review_days,
            deployment_days=estimate.deployment_days,
            total_days=estimate.total_days,
            confidence_level=estimate.confidence_level,
            exceeds_limit=estimate.exceeds_limit,
            split_recommendations=split_recommendations
        )
        
        logger.info(f"Cycle time estimation completed for {ticket_key}: {estimate.total_days} days")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error estimating cycle time for {ticket_key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to estimate cycle time: {str(e)}")


@router.post("/plan/tasks/team-based", 
          tags=["Planning"],
          response_model=PlanningResultResponse,
          summary="Generate team-separated tasks",
          description="Generate tasks separated by team (Backend, Frontend, QA) with dependencies and cycle time optimization. Preview mode by default. Set dry_run=false to create tickets.")
async def generate_team_based_tasks(
    request: TaskGenerationRequest, 
    current_user: str = Depends(get_current_user)
):
    """Generate tasks with intelligent Backend/Frontend/QA team separation"""
    generator = get_generator()
    config = get_config()
    
    try:
        logger.info(f"User {current_user} generating team-based tasks for {len(request.story_keys)} stories")
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503, 
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Create custom LLM client if provider/model specified
        custom_llm_client = None
        if request.llm_provider or request.llm_model:
            custom_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        # Generate team-separated tasks using the enhanced planning service
        planning_result = generator.generate_tasks_for_stories(
            story_keys=request.story_keys,
            epic_key=request.epic_key,
            dry_run=request.dry_run,
            split_oversized_tasks=request.split_oversized_tasks,
            max_task_cycle_days=request.max_task_cycle_days,
            max_tasks_per_story=config.get_max_tasks_per_story(),
            custom_llm_client=custom_llm_client,
            generate_test_cases=request.generate_test_cases
        )
        
        # Convert to API response format
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=request.generate_test_cases)
        
        response = PlanningResultResponse(
            epic_key=planning_result.epic_key,
            operation_mode=planning_result.mode.value,
            success=planning_result.success,
            created_tickets=planning_result.created_tickets,
            task_details=task_details,
            summary_stats=planning_result.summary_stats,
            errors=planning_result.errors,
            warnings=planning_result.warnings,
            execution_time_seconds=planning_result.execution_time_seconds
        )
        
        # Add team separation info to summary stats
        if hasattr(planning_result, 'epic_plan') and planning_result.epic_plan:
            all_tasks = []
            for story in planning_result.epic_plan.stories:
                all_tasks.extend(story.tasks)
            
            backend_count = len([t for t in all_tasks if hasattr(t, 'team') and t.team and 'backend' in str(t.team).lower()])
            frontend_count = len([t for t in all_tasks if hasattr(t, 'team') and t.team and 'frontend' in str(t.team).lower()])
            qa_count = len([t for t in all_tasks if hasattr(t, 'team') and t.team and 'qa' in str(t.team).lower()])
            
            if not response.summary_stats:
                response.summary_stats = {}
            
            response.summary_stats.update({
                "team_separation": {
                    "backend_tasks": backend_count,
                    "frontend_tasks": frontend_count,
                    "qa_tasks": qa_count
                }
            })
        
        logger.info(f"Team-based task generation completed for stories {request.story_keys}: {response.success}")
        return response
        
    except Exception as e:
        logger.error(f"Error generating team-based tasks for stories {request.story_keys}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate team-based tasks: {str(e)}")


@router.post("/plan/stories/sync-from-prd",
          tags=["Planning"],
          response_model=Union[PRDStorySyncResponse, BatchResponse],
          summary="Sync story tickets from PRD table to JIRA",
          description="Sync story tickets from PRD table to JIRA. Supports both synchronous and asynchronous processing.")
async def sync_stories_from_prd(request: PRDStorySyncRequest, current_user: str = Depends(get_current_user)):
    """Sync story tickets from PRD table to JIRA"""
    from ..job_queue import get_redis_pool
    from ..models.generation import BatchResponse, JobStatus
    from datetime import datetime
    import uuid
    
    generator = get_generator()
    
    try:
        logger.info(f"User {current_user} syncing stories from PRD")
        
        # Normalize epic_key from URL if needed (supports full JIRA URLs like single ticket and task breakdown)
        epic_key = None
        if request.epic_key:
            epic_key = normalize_ticket_key(request.epic_key)
            if not epic_key:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid epic_key format: {request.epic_key}. Please provide a valid JIRA epic key or URL (e.g., EPIC-123 or https://company.atlassian.net/browse/EPIC-123)."
                )
        
        # Validate input
        if not epic_key and not request.prd_url:
            raise HTTPException(
                status_code=400,
                detail="Either epic_key or prd_url must be provided. epic_key can be a JIRA ticket key or full JIRA URL."
            )
        
        if not generator.planning_service:
            raise HTTPException(
                status_code=503,
                detail="Planning service not available - requires Confluence client configuration"
            )
        
        # Determine prd_url
        prd_url = request.prd_url
        
        # If epic_key provided, get PRD URL from epic
        if epic_key and not prd_url:
            try:
                epic_issue = generator.jira_client.get_ticket(epic_key)
                if epic_issue:
                    prd_url = generator.planning_service._get_custom_field_value(epic_issue, 'PRD')
                    if not prd_url:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Epic {epic_key} does not have a PRD custom field set"
                        )
            except Exception as e:
                logger.error(f"Error getting PRD URL from epic {epic_key}: {e}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to get PRD URL from epic {epic_key}: {str(e)}"
                )
        
        # If only prd_url provided, epic_key is required
        if prd_url and not epic_key:
            raise HTTPException(
                status_code=400,
                detail="epic_key is required when prd_url is provided directly"
            )
        
        # Validate existing_ticket_action
        if request.existing_ticket_action not in ["skip", "update", "error"]:
            raise HTTPException(
                status_code=400,
                detail="existing_ticket_action must be one of: skip, update, error"
            )
        
        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active job
            active_job_id = get_active_job_for_ticket(epic_key)
            if active_job_id:
                from ..dependencies import jobs
                active_job = jobs[active_job_id]
                raise HTTPException(
                    status_code=409,
                    detail=f"Epic {epic_key} is already being processed in job {active_job_id}",
                    headers={"X-Active-Job-Id": active_job_id, "X-Active-Job-Status-Url": f"/jobs/{active_job_id}"}
                )
            
            job_id = str(uuid.uuid4())
            
            from ..dependencies import jobs
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="prd_story_sync",
                status="started",
                progress={"message": f"Queued for syncing stories from PRD for epic {epic_key}"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                ticket_key=epic_key,
                prd_url=prd_url
            )
            
            # Register epic key for duplicate prevention
            register_ticket_job(epic_key, job_id)
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_prd_story_sync_worker',
                job_id=job_id,
                epic_key=epic_key,
                prd_url=prd_url,
                dry_run=request.dry_run,
                existing_ticket_action=request.existing_ticket_action,
                llm_model=request.llm_model,
                llm_provider=request.llm_provider,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued PRD story sync job {job_id} for epic {epic_key}")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"PRD story sync for epic {epic_key} queued",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable
                max_results=0,
                update_jira=not request.dry_run,
                safety_note="JIRA will only be updated if dry_run is false"
            )
        
        # Synchronous mode
        planning_result = generator.sync_stories_from_prd(
            epic_key=epic_key,
            prd_url=prd_url,
            dry_run=request.dry_run,
            existing_ticket_action=request.existing_ticket_action
        )
        
        # Convert to API response format (PRD sync doesn't have generate_test_cases, default to False)
        story_details = extract_story_details_with_tests(planning_result, generate_test_cases=False)
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=False)
        
        response = PRDStorySyncResponse(
            epic_key=planning_result.epic_key,
            operation_mode=planning_result.mode.value,
            success=planning_result.success,
            created_tickets=planning_result.created_tickets,
            story_details=story_details,
            task_details=task_details,
            summary_stats=planning_result.summary_stats,
            errors=planning_result.errors,
            warnings=planning_result.warnings,
            execution_time_seconds=planning_result.execution_time_seconds
        )
        
        logger.info(f"PRD story sync completed for epic {epic_key}: {response.success}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing stories from PRD: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to sync stories from PRD: {str(e)}")
