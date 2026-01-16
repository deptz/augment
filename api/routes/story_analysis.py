"""
Story Analysis Routes
Endpoints for story coverage analysis
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from typing import Union
import uuid
import logging

from ..models.story_analysis import (
    StoryCoverageRequest,
    StoryCoverageResponse,
    UpdateTaskRequest,
    CreateTaskRequest,
    UpdateTaskResponse,
    CreateTaskResponse
)
from ..models.generation import BatchResponse, JobStatus
from ..models.opencode import validate_repos_list
from ..dependencies import get_jira_client, get_llm_client, get_config
from ..dependencies import jobs, get_active_job_for_ticket, register_ticket_job
from ..utils import create_custom_llm_client, normalize_ticket_key
from ..auth import get_current_user
from ..job_queue import get_redis_pool

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/analyze/story-coverage",
         tags=["Story Analysis"],
         summary="Analyze story requirements coverage by tasks",
         description="Check if existing tasks cover all story requirements. Returns coverage percentage and suggestions for updating or creating tasks. Read-only - no JIRA changes. Use async_mode=true for background processing.")
async def analyze_story_coverage(
    request: StoryCoverageRequest,
    current_user: str = Depends(get_current_user)
) -> Union[StoryCoverageResponse, BatchResponse]:
    """Analyze whether task tickets adequately cover story requirements"""
    jira_client = get_jira_client()
    llm_client = get_llm_client()
    config = get_config()
    
    try:
        # Normalize story_key from URL if needed
        story_key = normalize_ticket_key(request.story_key)
        if not story_key:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid story key format: {request.story_key}. Please provide a valid JIRA ticket key or URL."
            )
        
        logger.info(f"User {current_user} analyzing coverage for story {story_key} (async_mode={request.async_mode})")
        
        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")
        
        if not llm_client:
            raise HTTPException(status_code=503, detail="LLM client not initialized")
        
        # Validate and normalize repos if provided
        repos_normalized = None
        repos_urls = None
        if request.repos:
            try:
                max_repos = config.get_opencode_config().get('max_repos_per_job', 5)
                repos_normalized = validate_repos_list(request.repos, max_repos=max_repos)
                repos_urls = [r.url for r in repos_normalized] if repos_normalized else None
                
                # Check if OpenCode is enabled when repos are provided
                if repos_normalized and not config.is_opencode_enabled():
                    raise HTTPException(
                        status_code=503,
                        detail="OpenCode is not enabled. Remove repos parameter to use direct LLM, or enable OpenCode in configuration."
                    )
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        
        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active job
            active_job_id = get_active_job_for_ticket(story_key)
            if active_job_id:
                # Verify job actually exists (defensive check)
                if active_job_id in jobs:
                    active_job = jobs[active_job_id]
                    raise HTTPException(
                        status_code=409,
                        detail=f"Story {story_key} is already being processed in job {active_job_id}",
                        headers={"X-Active-Job-Id": active_job_id, "X-Active-Job-Status-Url": f"/jobs/{active_job_id}"}
                    )
                else:
                    # Job ID returned but job doesn't exist - clean up stale mapping
                    logger.warning(f"Stale ticket_jobs mapping found: {story_key} -> {active_job_id} (job not in jobs dict)")
                    from ..dependencies import unregister_ticket_job
                    unregister_ticket_job(story_key)
                    # Continue to create new job
            
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="story_coverage",
                status="started",
                progress={"message": f"Queued for analyzing story coverage for {story_key}" + (" (with OpenCode)" if repos_urls else "")},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                story_key=story_key,
                repos=repos_urls
            )
            
            # Register story key for duplicate prevention
            register_ticket_job(story_key, job_id)
            
            # Convert repos to serializable format for worker
            repos_for_worker = None
            if repos_normalized:
                repos_for_worker = [{"url": r.url, "branch": r.branch} for r in repos_normalized]
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_story_coverage_worker',
                job_id=job_id,
                story_key=story_key,
                include_test_cases=request.include_test_cases,
                additional_context=request.additional_context,
                llm_model=request.llm_model,
                llm_provider=request.llm_provider,
                repos=repos_for_worker,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued story coverage analysis job {job_id} for story {story_key}" + (" (with OpenCode)" if repos_urls else ""))
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Story coverage analysis for {story_key} queued for processing" + (" (with OpenCode)" if repos_urls else ""),
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable for story coverage
                max_results=1,
                update_jira=False,  # Story coverage is read-only
                safety_note="This is a read-only analysis operation - no JIRA updates are made"
            )
        
        # Synchronous mode (original behavior)
        # Note: repos (OpenCode) requires async_mode due to long execution time
        if repos_normalized:
            raise HTTPException(
                status_code=400,
                detail="repos parameter requires async_mode=true due to long execution time. Please set async_mode=true to use OpenCode."
            )
        
        # Create custom LLM client if specified
        analysis_llm_client = llm_client
        if request.llm_provider or request.llm_model:
            analysis_llm_client = create_custom_llm_client(request.llm_provider, request.llm_model)
        
        # Get confluence client and planning service for PRD/RFC fetching
        from ..dependencies import get_confluence_client, get_generator
        confluence_client = get_confluence_client()
        generator = get_generator()
        planning_service = generator.planning_service if generator else None
        
        # Import and create the analyzer
        from src.story_coverage_analyzer import StoryCoverageAnalyzer
        
        analyzer = StoryCoverageAnalyzer(
            jira_client=jira_client,
            llm_client=analysis_llm_client,
            config=config.__dict__ if hasattr(config, '__dict__') else {},
            confluence_client=confluence_client,
            planning_service=planning_service
        )
        
        # Perform analysis
        result = analyzer.analyze_coverage(
            story_key=story_key,
            include_test_cases=request.include_test_cases,
            additional_context=request.additional_context
        )
        
        if not result.get('success', False):
            raise HTTPException(
                status_code=404 if 'not found' in result.get('error', '').lower() else 500,
                detail=result.get('error', 'Analysis failed')
            )
        
        logger.info(f"Coverage analysis completed for {story_key}: {result.get('coverage_percentage', 0)}% coverage")
        
        # Ensure additional_context is included in response
        result_with_context = result.copy()
        result_with_context['additional_context'] = request.additional_context
        return StoryCoverageResponse(**result_with_context)
        
    except HTTPException:
        raise
    except Exception as e:
        # Use normalized key if available, otherwise fall back to original
        error_key = story_key if 'story_key' in dir() else request.story_key
        logger.error(f"Error analyzing story coverage for {error_key}: {str(e)}", exc_info=True)
        if request.async_mode:
            raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to analyze story coverage: {str(e)}")


@router.post("/analyze/story-coverage/update-task",
         tags=["Story Analysis"],
         response_model=UpdateTaskResponse,
         summary="Update existing task with improved description and test cases",
         description="Update a task with improved description and test cases from coverage analysis. Preview mode by default. Set update_jira=true to apply changes.")
async def update_task_from_suggestion(
    request: UpdateTaskRequest,
    current_user: str = Depends(get_current_user)
):
    """Update an existing task with suggested improvements"""
    jira_client = get_jira_client()
    from ..dependencies import get_confluence_client
    
    try:
        # Normalize task_key from URL if needed
        task_key = normalize_ticket_key(request.task_key)
        if not task_key:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid task key format: {request.task_key}. Please provide a valid JIRA ticket key or URL."
            )
        
        logger.info(f"User {current_user} updating task {task_key} (update_jira={request.update_jira})")
        
        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")
        
        # Verify task exists
        task_data = jira_client.get_ticket(task_key)
        if not task_data:
            raise HTTPException(status_code=404, detail=f"Task {task_key} not found")
        
        if not request.update_jira:
            # Preview mode - just return what would be updated
            logger.info(f"Preview mode for {task_key} - not updating JIRA")
            return UpdateTaskResponse(
                success=True,
                task_key=task_key,
                updated_in_jira=False,
                preview_description=request.updated_description,
                preview_test_cases=request.updated_test_cases,
                message=f"Preview: Task {task_key} would be updated with provided content. Set update_jira=true to commit."
            )
        
        # Actually update JIRA
        logger.info(f"Updating task {task_key} in JIRA")
        
        # Update description
        description_updated = jira_client.update_ticket_description(
            ticket_key=task_key,
            description=request.updated_description,
            dry_run=False
        )
        
        if not description_updated:
            raise HTTPException(status_code=500, detail=f"Failed to update description for {task_key}")
        
        # Handle image attachments if description contains images
        confluence_client = get_confluence_client()
        confluence_server_url = None
        if confluence_client:
            confluence_server_url = confluence_client.server_url
        
        jira_client._attach_images_from_description(
            task_key, 
            request.updated_description, 
            confluence_server_url
        )
        
        # Update test cases if provided
        if request.updated_test_cases:
            test_cases_updated = jira_client.update_test_case_custom_field(
                ticket_key=task_key,
                test_cases_content=request.updated_test_cases
            )
            
            if not test_cases_updated:
                logger.warning(f"Failed to update test cases for {task_key}")
        
        logger.info(f"Successfully updated task {task_key} in JIRA")
        
        return UpdateTaskResponse(
            success=True,
            task_key=task_key,
            updated_in_jira=True,
            message=f"Successfully updated task {task_key} in JIRA"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        # Use normalized key if available, otherwise fall back to original
        error_key = task_key if 'task_key' in dir() else request.task_key
        logger.error(f"Error updating task {error_key}: {str(e)}", exc_info=True)
        return UpdateTaskResponse(
            success=False,
            task_key=error_key,
            updated_in_jira=False,
            message=f"Failed to update task",
            error=str(e)
        )


@router.post("/analyze/story-coverage/create-task",
         tags=["Story Analysis"],
         response_model=CreateTaskResponse,
         summary="Create new task from coverage analysis suggestions",
         description="Create a new task to fill coverage gaps. Typically used with suggestions from coverage analysis. Preview mode by default. Set create_ticket=true to create in JIRA. Automatically links to parent story.")
async def create_task_from_suggestion(
    request: CreateTaskRequest,
    current_user: str = Depends(get_current_user)
):
    """Create a new task to fill coverage gaps"""
    jira_client = get_jira_client()
    
    try:
        # Normalize story_key from URL if needed
        story_key = normalize_ticket_key(request.story_key)
        if not story_key:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid story key format: {request.story_key}. Please provide a valid JIRA ticket key or URL."
            )
        
        logger.info(f"User {current_user} creating task for story {story_key} (create_ticket={request.create_ticket})")
        
        if not jira_client:
            raise HTTPException(status_code=503, detail="JIRA client not initialized")
        
        # Verify story exists
        story_data = jira_client.get_ticket(story_key)
        if not story_data:
            raise HTTPException(status_code=404, detail=f"Story {story_key} not found")
        
        # Get project key from story
        project_key = jira_client.get_project_key_from_epic(story_key)
        if not project_key:
            raise HTTPException(status_code=400, detail=f"Could not determine project key from {story_key}")
        
        if not request.create_ticket:
            # Preview mode - just return what would be created
            logger.info(f"Preview mode for new task under {story_key} - not creating in JIRA")
            return CreateTaskResponse(
                success=True,
                story_key=story_key,
                task_key=None,
                created_in_jira=False,
                preview_summary=request.task_summary,
                preview_description=request.task_description,
                preview_test_cases=request.test_cases,
                message=f"Preview: Task would be created under story {story_key}. Set create_ticket=true to commit."
            )
        
        # Actually create in JIRA
        logger.info(f"Creating new task under story {story_key} in JIRA")
        
        # Prepare task data following existing patterns
        from src.planning_models import TaskPlan, CycleTimeEstimate, TaskScope
        
        # Create a minimal TaskPlan for creation
        # Get epic key from story's parent if available
        story_fields = story_data.get('fields', {})
        epic_key = None
        if story_fields.get('parent'):
            epic_key = story_fields['parent'].get('key')
        
        # Create minimal TaskPlan with required fields
        task_plan = TaskPlan(
            summary=request.task_summary,
            purpose=request.task_description,  # Use description as purpose
            scopes=[TaskScope(
                description=request.task_description,
                deliverable="Task completion"
            )],
            expected_outcomes=["Task completed successfully"],
            test_cases=[],  # Empty - will update test_case_custom_field separately
            cycle_time_estimate=CycleTimeEstimate(
                development_days=1.0,
                testing_days=0.5,
                review_days=0.5,
                deployment_days=0.0,
                total_days=2.0,
                confidence_level=0.7
            ),
            epic_key=epic_key
        )
        
        # Create the task ticket with raw description to avoid duplication
        created_task_key = jira_client.create_task_ticket(
            task_plan=task_plan,
            project_key=project_key,
            story_key=story_key,
            raw_description=request.task_description
        )
        
        if not created_task_key:
            raise HTTPException(status_code=500, detail="Failed to create task ticket")
        
        # Update test cases separately if provided (as raw string for custom field)
        if request.test_cases:
            test_cases_updated = jira_client.update_test_case_custom_field(
                ticket_key=created_task_key,
                test_cases_content=request.test_cases
            )
            if test_cases_updated:
                logger.info(f"Added test cases to task {created_task_key}")
        
        # Link task to story using "Work item split" relationship
        link_created = jira_client.create_issue_link(
            inward_key=created_task_key,      # Task is inward (split from)
            outward_key=story_key,  # Story is outward (split to)
            link_type="Work item split"
        )
        
        if not link_created:
            logger.warning(f"Failed to create 'Work item split' link between {created_task_key} and {story_key}")
            # Try alternative link type
            jira_client.create_issue_link(
                inward_key=created_task_key,      # Task is inward (split from)
                outward_key=story_key,  # Story is outward (split to)
                link_type="Relates"
            )
        
        logger.info(f"Successfully created task {created_task_key} under story {story_key}")
        
        return CreateTaskResponse(
            success=True,
            story_key=story_key,
            task_key=created_task_key,
            created_in_jira=True,
            message=f"Successfully created task {created_task_key} under story {story_key}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        # Use normalized key if available, otherwise fall back to original
        error_key = story_key if 'story_key' in dir() else request.story_key
        logger.error(f"Error creating task for story {error_key}: {str(e)}", exc_info=True)
        return CreateTaskResponse(
            success=False,
            story_key=error_key,
            task_key=None,
            created_in_jira=False,
            message=f"Failed to create task",
            error=str(e)
        )
