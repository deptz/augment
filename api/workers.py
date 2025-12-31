"""
ARQ Workers
Background job processing functions for ARQ worker process
"""
from arq import cron
from datetime import datetime
from typing import Optional, List, Dict, Any
import logging
from .dependencies import get_jira_client, get_llm_client, get_generator, jobs, get_config, unregister_ticket_job, get_active_job_for_ticket, register_ticket_job
from .models.generation import TicketResponse, JobStatus
from .utils import create_custom_llm_client

logger = logging.getLogger(__name__)


class WorkerSettings:
    """ARQ worker configuration"""
    redis_settings = None  # Will be set at startup
    max_jobs = 10  # Default, will be overridden by config
    job_timeout = 3600  # Default 1 hour, will be overridden by config
    keep_result = 3600  # Default 1 hour, will be overridden by config


def _initialize_services_if_needed():
    """Helper to initialize services if needed"""
    from .dependencies import initialize_services
    try:
        get_generator()
    except RuntimeError:
        initialize_services()


def _get_or_create_job(job_id: str, job_type: str, initial_message: str) -> JobStatus:
    """Helper to get or create job status"""
    if job_id in jobs:
        job = jobs[job_id]
        job.status = "processing"
        job.progress = {"message": initial_message}
    else:
        job = JobStatus(
            job_id=job_id,
            job_type=job_type,
            status="processing",
            progress={"message": initial_message},
            started_at=datetime.now(),
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0
        )
        jobs[job_id] = job
    return job


async def process_single_ticket_worker(ctx, job_id: str, ticket_key: str, update_jira: bool,
                                     llm_model: Optional[str] = None, llm_provider: Optional[str] = None,
                                     additional_context: Optional[str] = None):
    """ARQ worker function for processing a single ticket"""
    _initialize_services_if_needed()
    generator = get_generator()
    jira_client = get_jira_client()
    
    try:
        job = _get_or_create_job(job_id, "single", f"Processing ticket {ticket_key}...")
        job.ticket_key = ticket_key
        
        # Check if cancelled
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            unregister_ticket_job(ticket_key)
            return
        
        # Get ticket info
        ticket_data = jira_client.get_ticket(ticket_key)
        if not ticket_data:
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = "Ticket not found"
            job.progress = {"message": "Ticket not found"}
            return
        
        # Extract basic info
        summary = ticket_data.get('fields', {}).get('summary', '')
        assignee = ticket_data.get('fields', {}).get('assignee')
        assignee_name = assignee.get('displayName') if assignee else None
        parent = ticket_data.get('fields', {}).get('parent')
        parent_name = parent.get('fields', {}).get('summary') if parent else None
        
        # Process ticket
        result = generator.process_ticket(
            ticket_key=ticket_key,
            dry_run=not update_jira,
            llm_model=llm_model,
            llm_provider=llm_provider,
            additional_context=additional_context
        )
        
        # Extract results
        generated_description = None
        system_prompt = None
        user_prompt = None
        if result.description:
            generated_description = result.description.description
            system_prompt = result.description.system_prompt
            user_prompt = result.description.user_prompt
        
        ticket_response = TicketResponse(
            ticket_key=ticket_key,
            summary=summary,
            assignee_name=assignee_name,
            parent_name=parent_name,
            generated_description=generated_description,
            success=result.success,
            error=result.error,
            skipped_reason=result.skipped_reason,
            updated_in_jira=update_jira and result.success,
            llm_provider=result.llm_provider,
            llm_model=result.llm_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt
        )
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = ticket_response.dict()
        job.progress = {"message": "Completed successfully" if result.success else f"Completed with error: {result.error}"}
        job.successful_tickets = 1 if result.success else 0
        job.failed_tickets = 0 if result.success else 1
        
        # Unregister ticket key when job completes
        unregister_ticket_job(ticket_key)
        
        logger.info(f"Job {job_id} completed: ticket {ticket_key} processed")
        
        # Return results so ARQ stores them in Redis for persistence
        return ticket_response.dict()
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister ticket key on failure
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_batch_tickets_worker(ctx, job_id: str, jql: str, max_results: int, 
                                      update_jira: bool, llm_model: Optional[str] = None,
                                      llm_provider: Optional[str] = None):
    """ARQ worker function for processing batch tickets"""
    _initialize_services_if_needed()
    generator = get_generator()
    jira_client = get_jira_client()
    
    try:
        job = _get_or_create_job(job_id, "batch", "Fetching tickets from JIRA...")
        
        # Get tickets from JQL
        tickets = jira_client.search_issues(jql, max_results=max_results)
        job.total_tickets = len(tickets)
        
        # Track all ticket keys for this batch job
        ticket_keys_list = [ticket.key for ticket in tickets]
        job.ticket_keys = ticket_keys_list
        
        # Check for duplicate active jobs per ticket
        skipped_tickets = []
        active_duplicates = {}
        for ticket in tickets:
            active_job_id = get_active_job_for_ticket(ticket.key)
            if active_job_id and active_job_id != job_id:
                skipped_tickets.append(ticket.key)
                active_duplicates[ticket.key] = active_job_id
                logger.warning(f"Job {job_id}: Skipping ticket {ticket.key} - already being processed in job {active_job_id}")
        
        if skipped_tickets:
            job.progress = {"message": f"Found {len(tickets)} tickets, {len(skipped_tickets)} skipped (duplicates), processing {len(tickets) - len(skipped_tickets)}..."}
        else:
            job.progress = {"message": f"Found {len(tickets)} tickets, processing..."}
        
        # Register all ticket keys for this job (even skipped ones, to prevent duplicates)
        for ticket_key in ticket_keys_list:
            register_ticket_job(ticket_key, job_id)
        
        results = []
        for i, ticket in enumerate(tickets):
            try:
                # Check if job was cancelled (via ctx)
                if hasattr(ctx, 'job') and ctx.job.cancelled:
                    job.status = "cancelled"
                    job.completed_at = datetime.now()
                    job.progress = {"message": "Job was cancelled"}
                    # Unregister all ticket keys
                    for ticket_key in ticket_keys_list:
                        unregister_ticket_job(ticket_key)
                    logger.info(f"Job {job_id} was cancelled")
                    return
                
                # Skip if this ticket is being processed by another job
                if ticket.key in skipped_tickets:
                    results.append(TicketResponse(
                        ticket_key=ticket.key,
                        summary=ticket.fields.summary if hasattr(ticket.fields, 'summary') else '',
                        assignee_name=None,
                        parent_name=None,
                        generated_description=None,
                        success=False,
                        error=f"Ticket is already being processed in job {active_duplicates[ticket.key]}",
                        skipped_reason="duplicate_active_job",
                        updated_in_jira=False,
                        llm_provider=llm_provider,
                        llm_model=llm_model
                    ))
                    job.failed_tickets += 1
                    job.processed_tickets += 1
                    continue
                
                # Extract basic ticket information
                summary = ticket.fields.summary if hasattr(ticket.fields, 'summary') else ''
                assignee = ticket.fields.assignee if hasattr(ticket.fields, 'assignee') else None
                assignee_name = assignee.displayName if assignee else None
                
                parent = ticket.fields.parent if hasattr(ticket.fields, 'parent') else None
                parent_name = parent.fields.summary if parent and hasattr(parent.fields, 'summary') else None
                
                # Process each ticket
                result = generator.process_ticket(
                    ticket_key=ticket.key,
                    dry_run=not update_jira,
                    llm_model=llm_model,
                    llm_provider=llm_provider
                )
                
                # Extract generated description
                generated_description = None
                if result.description:
                    generated_description = result.description.description
                
                # Convert to response format
                ticket_response = TicketResponse(
                    ticket_key=ticket.key,
                    summary=summary,
                    assignee_name=assignee_name,
                    parent_name=parent_name,
                    generated_description=generated_description,
                    success=result.success,
                    error=result.error,
                    skipped_reason=result.skipped_reason,
                    updated_in_jira=update_jira and result.success,
                    llm_provider=result.llm_provider,
                    llm_model=result.llm_model
                )
                
                results.append(ticket_response)
                
                if result.success:
                    job.successful_tickets += 1
                else:
                    job.failed_tickets += 1
                    
                job.processed_tickets += 1
                job.progress = {
                    "message": f"Processed {job.processed_tickets}/{job.total_tickets} tickets",
                    "percentage": (job.processed_tickets / job.total_tickets) * 100
                }
                
                logger.info(f"Job {job_id}: Processed ticket {ticket.key} ({i+1}/{len(tickets)})")
                
            except Exception as e:
                logger.error(f"Job {job_id}: Error processing ticket {ticket.key}: {e}")
                results.append(TicketResponse(
                    ticket_key=ticket.key,
                    summary="",
                    assignee_name=None,
                    parent_name=None,
                    generated_description=None,
                    success=False,
                    error=str(e),
                    skipped_reason=None,
                    updated_in_jira=False,
                    llm_provider=llm_provider,
                    llm_model=llm_model
                ))
                job.failed_tickets += 1
                job.processed_tickets += 1
        
        # Mark job as completed
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = results
        job.progress = {
            "message": f"Completed: {job.successful_tickets} successful, {job.failed_tickets} failed",
            "percentage": 100
        }
        
        # Unregister all ticket keys when job completes
        for ticket_key in ticket_keys_list:
            unregister_ticket_job(ticket_key)
        
        logger.info(f"Job {job_id} completed: {job.successful_tickets} successful, {job.failed_tickets} failed")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister all ticket keys on failure
            if job.ticket_keys:
                for ticket_key in job.ticket_keys:
                    unregister_ticket_job(ticket_key)
        raise


async def process_story_generation_worker(ctx, job_id: str, epic_key: str, dry_run: bool,
                                         llm_model: Optional[str] = None, llm_provider: Optional[str] = None,
                                         generate_test_cases: bool = False):
    """ARQ worker function for generating stories for an epic"""
    _initialize_services_if_needed()
    generator = get_generator()
    
    try:
        job = _get_or_create_job(job_id, "story_generation", f"Generating stories for epic {epic_key}...")
        # Epic key is tracked as ticket_key for story generation
        job.ticket_key = epic_key
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            return
        
        if not generator.planning_service:
            raise RuntimeError("Planning service not available - requires Confluence client configuration")
        
        custom_llm_client = None
        if llm_provider or llm_model:
            custom_llm_client = create_custom_llm_client(llm_provider, llm_model)
        
        planning_result = generator.generate_stories_for_epic(
            epic_key=epic_key,
            dry_run=dry_run,
            generate_test_cases=generate_test_cases
        )
        
        # Convert to dict for storage
        from .routes.planning import extract_story_details_with_tests, extract_task_details_with_tests
        story_details = extract_story_details_with_tests(planning_result, generate_test_cases=generate_test_cases)
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=generate_test_cases)
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = {
            "epic_key": planning_result.epic_key,
            "operation_mode": planning_result.mode.value,
            "success": planning_result.success,
            "created_tickets": planning_result.created_tickets,
            "story_details": [s.dict() for s in story_details],
            "task_details": [t.dict() for t in task_details],
            "summary_stats": planning_result.summary_stats,
            "errors": planning_result.errors,
            "warnings": planning_result.warnings,
            "execution_time_seconds": planning_result.execution_time_seconds,
            "system_prompt": planning_result.system_prompt,
            "user_prompt": planning_result.user_prompt
        }
        job.progress = {"message": f"Generated {len(story_details)} stories successfully"}
        job.successful_tickets = len(planning_result.created_tickets)
        
        # Unregister epic key when job completes
        unregister_ticket_job(epic_key)
        
        logger.info(f"Job {job_id} completed: generated stories for epic {epic_key}")
        
        # Return results so ARQ stores them in Redis for persistence
        return job.results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister epic key on failure
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_task_generation_worker(ctx, job_id: str, story_keys: List[str], epic_key: str,
                                        dry_run: bool, split_oversized_tasks: bool,
                                        max_task_cycle_days: float, llm_model: Optional[str] = None,
                                        llm_provider: Optional[str] = None, additional_context: Optional[str] = None,
                                        generate_test_cases: bool = False):
    """ARQ worker function for generating tasks for stories"""
    _initialize_services_if_needed()
    generator = get_generator()
    config = get_config()
    
    try:
        job = _get_or_create_job(job_id, "task_generation", f"Generating tasks for {len(story_keys)} stories...")
        # Track all story keys for this job
        job.ticket_keys = story_keys.copy()
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            # Unregister all story keys
            for story_key in story_keys:
                unregister_ticket_job(story_key)
            return
        
        if not generator.planning_service:
            raise RuntimeError("Planning service not available - requires Confluence client configuration")
        
        custom_llm_client = None
        if llm_provider or llm_model:
            custom_llm_client = create_custom_llm_client(llm_provider, llm_model)
        
        planning_result = generator.generate_tasks_for_stories(
            story_keys=story_keys,
            epic_key=epic_key,
            dry_run=dry_run,
            split_oversized_tasks=split_oversized_tasks,
            max_task_cycle_days=max_task_cycle_days,
            max_tasks_per_story=config.get_max_tasks_per_story(),
            custom_llm_client=custom_llm_client,
            additional_context=additional_context,
            generate_test_cases=generate_test_cases
        )
        
        from .routes.planning import extract_story_details_with_tests, extract_task_details_with_tests
        story_details = extract_story_details_with_tests(planning_result, generate_test_cases=generate_test_cases)
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=generate_test_cases)
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = {
            "epic_key": planning_result.epic_key,
            "operation_mode": planning_result.mode.value,
            "success": planning_result.success,
            "created_tickets": planning_result.created_tickets,
            "story_details": [s.dict() for s in story_details],
            "task_details": [t.dict() for t in task_details],
            "summary_stats": planning_result.summary_stats,
            "errors": planning_result.errors,
            "warnings": planning_result.warnings,
            "execution_time_seconds": planning_result.execution_time_seconds,
            "system_prompt": planning_result.system_prompt,
            "user_prompt": planning_result.user_prompt
        }
        job.progress = {"message": f"Generated {len(task_details)} tasks successfully"}
        job.successful_tickets = len(planning_result.created_tickets)
        
        # Unregister all story keys when job completes
        for story_key in story_keys:
            unregister_ticket_job(story_key)
        
        logger.info(f"Job {job_id} completed: generated tasks for {len(story_keys)} stories")
        
        # Return results so ARQ stores them in Redis for persistence
        return job.results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister all story keys on failure
            if job.ticket_keys:
                for story_key in job.ticket_keys:
                    unregister_ticket_job(story_key)
        raise


async def process_test_generation_worker(ctx, job_id: str, test_type: str, epic_key: Optional[str] = None,
                                        story_key: Optional[str] = None, task_key: Optional[str] = None,
                                        coverage_level: str = "standard", domain_context: Optional[str] = None,
                                        technical_context: Optional[str] = None, include_documents: bool = True,
                                        llm_model: Optional[str] = None, llm_provider: Optional[str] = None):
    """ARQ worker function for generating test cases"""
    _initialize_services_if_needed()
    generator = get_generator()
    
    try:
        job = _get_or_create_job(job_id, "test_generation", f"Generating {test_type} tests...")
        # Track the relevant ticket key based on test type
        if task_key:
            job.ticket_key = task_key
        elif story_key:
            job.ticket_key = story_key
        elif epic_key:
            job.ticket_key = epic_key
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
            return
        
        if not generator.planning_service:
            raise RuntimeError("Planning service not available - requires Confluence client configuration")
        
        custom_llm_client = None
        if llm_provider or llm_model:
            custom_llm_client = create_custom_llm_client(llm_provider, llm_model)
        
        from src.enhanced_test_generator import TestCoverageLevel
        coverage_level_enum = TestCoverageLevel(coverage_level)
        
        if test_type == "comprehensive" and epic_key:
            test_results = generator.planning_service.generate_comprehensive_test_suite(
                epic_key=epic_key,
                coverage_level=coverage_level_enum
            )
        elif test_type == "story" and story_key:
            test_results = generator.planning_service.generate_story_tests(
                story_key=story_key,
                coverage_level=coverage_level_enum,
                domain_context=domain_context,
                technical_context=technical_context,
                include_documents=include_documents
            )
        elif test_type == "task" and task_key:
            test_results = generator.planning_service.generate_task_tests(
                task_key=task_key,
                coverage_level=coverage_level_enum,
                domain_context=domain_context,
                technical_context=technical_context,
                include_documents=include_documents
            )
        else:
            raise ValueError(f"Invalid test_type or missing required key: test_type={test_type}, epic_key={epic_key}, story_key={story_key}, task_key={task_key}")
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = test_results
        job.progress = {"message": f"Generated {test_results.get('total_test_cases', 0)} test cases successfully"}
        job.successful_tickets = 1 if test_results.get("success") else 0
        
        # Unregister ticket key when job completes
        if job.ticket_key:
            unregister_ticket_job(job.ticket_key)
        
        logger.info(f"Job {job_id} completed: generated {test_type} tests")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister ticket key on failure
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_prd_story_sync_worker(ctx, job_id: str, epic_key: str, prd_url: str, dry_run: bool,
                                        existing_ticket_action: str, llm_model: Optional[str] = None,
                                        llm_provider: Optional[str] = None):
    """ARQ worker function for syncing stories from PRD table"""
    _initialize_services_if_needed()
    generator = get_generator()
    
    try:
        job = _get_or_create_job(job_id, "prd_story_sync", f"Syncing stories from PRD for epic {epic_key}...")
        job.ticket_key = epic_key
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            unregister_ticket_job(epic_key)
            return
        
        if not generator.planning_service:
            raise RuntimeError("Planning service not available - requires Confluence client configuration")
        
        job.progress = {"message": "Parsing PRD content..."}
        
        planning_result = generator.sync_stories_from_prd(
            epic_key=epic_key,
            prd_url=prd_url,
            dry_run=dry_run,
            existing_ticket_action=existing_ticket_action
        )
        
        # Log planning result for debugging
        logger.info(f"Planning result: success={planning_result.success}, has_epic_plan={hasattr(planning_result, 'epic_plan') and planning_result.epic_plan is not None}")
        if hasattr(planning_result, 'epic_plan') and planning_result.epic_plan:
            story_count = len(planning_result.epic_plan.stories) if hasattr(planning_result.epic_plan, 'stories') else 0
            logger.info(f"Epic plan has {story_count} stories")
        else:
            logger.warning(f"Planning result has no epic_plan! Errors: {planning_result.errors if hasattr(planning_result, 'errors') else 'N/A'}")
        
        # Update job progress during processing
        if job_id in jobs:
            job = jobs[job_id]
            story_count = len(planning_result.epic_plan.stories) if (planning_result.epic_plan and hasattr(planning_result.epic_plan, 'stories')) else 0
            job.progress = {"message": f"Processed {story_count} stories"}
        
        job.progress = {"message": "Processing stories..."}
        
        # Convert to dict for storage
        from .routes.planning import extract_story_details_with_tests, extract_task_details_with_tests
        story_details = extract_story_details_with_tests(planning_result, generate_test_cases=generate_test_cases)
        task_details = extract_task_details_with_tests(planning_result, generate_test_cases=generate_test_cases)
        
        logger.info(f"Extracted {len(story_details)} story details and {len(task_details)} task details")
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = {
            "epic_key": planning_result.epic_key,
            "operation_mode": planning_result.mode.value,
            "success": planning_result.success,
            "created_tickets": planning_result.created_tickets,
            "story_details": [s.dict() for s in story_details],
            "task_details": [t.dict() for t in task_details],
            "summary_stats": planning_result.summary_stats,
            "errors": planning_result.errors,
            "warnings": planning_result.warnings,
            "execution_time_seconds": planning_result.execution_time_seconds,
            "system_prompt": planning_result.system_prompt,
            "user_prompt": planning_result.user_prompt
        }
        job.progress = {"message": f"Synced {len(story_details)} stories successfully"}
        job.successful_tickets = len(planning_result.created_tickets.get('stories', []))
        
        # Unregister epic key when job completes
        unregister_ticket_job(epic_key)
        
        logger.info(f"Job {job_id} completed: synced stories from PRD for epic {epic_key}")
        
        # Return results so ARQ stores them in Redis for persistence
        return job.results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister epic key on failure
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_bulk_story_update_worker(ctx, job_id: str, stories_data: List[Dict[str, Any]], dry_run: bool):
    """ARQ worker function for bulk updating story tickets"""
    _initialize_services_if_needed()
    jira_client = get_jira_client()
    
    try:
        job = _get_or_create_job(job_id, "bulk_story_update", f"Bulk updating {len(stories_data)} stories...")
        job.total_tickets = len(stories_data)
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            return
        
        if not jira_client:
            raise RuntimeError("JIRA client not initialized")
        
        from .models.jira_operations import StoryUpdateItem, StoryUpdateResult
        from .routes.jira_operations import _process_single_story_update
        
        results = []
        successful = 0
        failed = 0
        
        # Process each story
        for i, story_dict in enumerate(stories_data, 1):
            if hasattr(ctx, 'job') and ctx.job.cancelled:
                job.status = "cancelled"
                job.completed_at = datetime.now()
                job.progress = {"message": "Job was cancelled"}
                break
            
            story_item = StoryUpdateItem(**story_dict)
            job.progress = {"message": f"Processing story {i}/{len(stories_data)}: {story_item.story_key}"}
            job.processed_tickets = i
            
            logger.info(f"Processing story {i}/{len(stories_data)}: {story_item.story_key}")
            
            result = _process_single_story_update(
                jira_client=jira_client,
                story_item=story_item,
                dry_run=dry_run
            )
            
            results.append(result.dict())
            
            if result.success:
                successful += 1
                job.successful_tickets = successful
            else:
                failed += 1
                job.failed_tickets = failed
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = {
            "total_stories": len(stories_data),
            "successful": successful,
            "failed": failed,
            "results": results
        }
        job.progress = {"message": f"Bulk update completed: {successful} successful, {failed} failed"}
        
        logger.info(f"Job {job_id} completed: bulk updated {len(stories_data)} stories ({successful} successful, {failed} failed)")
        
        return job.results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
        raise


async def process_bulk_task_creation_worker(ctx, job_id: str, tasks_data: List[Dict[str, Any]], create_tickets: bool):
    """ARQ worker function for bulk creating task tickets"""
    _initialize_services_if_needed()
    jira_client = get_jira_client()
    from .dependencies import get_confluence_client
    
    try:
        job = _get_or_create_job(job_id, "bulk_task_creation", f"Creating {len(tasks_data)} task tickets...")
        job.total_tickets = len(tasks_data)
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            # Unregister story keys
            story_keys = list(set([task.get("story_key") for task in tasks_data]))
            for story_key in story_keys:
                unregister_ticket_job(story_key)
            return
        
        if not jira_client:
            raise RuntimeError("JIRA client not initialized")
        
        if not create_tickets:
            # Preview mode - return preview results
            preview_results = []
            for i, task_dict in enumerate(tasks_data):
                preview_results.append({
                    "index": i,
                    "success": True,
                    "ticket_key": None,
                    "error": None,
                    "links_created": []
                })
            
            job.status = "completed"
            job.completed_at = datetime.now()
            job.results = {
                "total_tasks": len(tasks_data),
                "successful": len(tasks_data),
                "failed": 0,
                "results": preview_results,
                "created_tickets": [],
                "message": f"Preview: {len(tasks_data)} task tickets would be created. Set create_tickets=true to commit."
            }
            job.progress = {"message": f"Preview completed: {len(tasks_data)} tasks"}
            job.successful_tickets = len(tasks_data)
            
            story_keys = list(set([task.get("story_key") for task in tasks_data]))
            for story_key in story_keys:
                unregister_ticket_job(story_key)
            
            return job.results
        
        # Get Confluence server URL if available
        confluence_client = get_confluence_client()
        confluence_server_url = None
        if confluence_client:
            confluence_server_url = confluence_client.server_url
        
        # Get project key from first task's parent epic
        project_key = jira_client.get_project_key_from_epic(tasks_data[0]["parent_key"])
        if not project_key:
            raise RuntimeError(f"Could not determine project key from epic {tasks_data[0]['parent_key']}")
        
        # Build issue data for all tasks
        from src.planning_models import TaskPlan, CycleTimeEstimate, TaskScope
        
        tickets_data = []
        task_index_to_item = {}  # Map index to task item for link creation later
        pending_links = []  # Collect all links to create after tickets are created
        
        job.progress = {"message": "Preparing task data..."}
        
        for i, task_dict in enumerate(tasks_data):
            task_item = type('TaskItem', (), task_dict)()  # Simple object from dict
            
            # Create cycle time estimate if mandays provided
            cycle_time_estimate = None
            if task_dict.get("mandays") is not None:
                mandays = task_dict["mandays"]
                cycle_time_estimate = CycleTimeEstimate(
                    development_days=mandays * 0.6,
                    testing_days=mandays * 0.2,
                    review_days=mandays * 0.15,
                    deployment_days=mandays * 0.05,
                    total_days=mandays,
                    confidence_level=0.7
                )
            
            # Create TaskPlan
            task_plan = TaskPlan(
                summary=task_dict["summary"],
                purpose=task_dict["description"],
                scopes=[TaskScope(
                    description=task_dict["description"],
                    deliverable="Task completion"
                )],
                expected_outcomes=["Task completed successfully"],
                test_cases=[],
                cycle_time_estimate=cycle_time_estimate,
                epic_key=task_dict["parent_key"]
            )
            
            # Build issue data
            description_adf = jira_client._convert_markdown_to_adf(task_dict["description"])
            
            issue_data = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": task_dict["summary"],
                    "description": description_adf,
                    "issuetype": {"name": "Task"}
                }
            }
            
            # Add parent epic
            if task_dict["parent_key"]:
                epic_type = jira_client.get_ticket_type(task_dict["parent_key"])
                if epic_type and 'epic' in epic_type.lower():
                    issue_data["fields"]["parent"] = {"key": task_dict["parent_key"]}
            
            # Add mandays if available
            if cycle_time_estimate and jira_client.mandays_custom_field:
                issue_data["fields"][jira_client.mandays_custom_field] = cycle_time_estimate.total_days
            
            # Add test cases if available
            if task_dict.get("test_cases") and jira_client.test_case_custom_field:
                test_cases_adf = jira_client._convert_markdown_to_adf(task_dict["test_cases"])
                issue_data["fields"][jira_client.test_case_custom_field] = test_cases_adf
            
            tickets_data.append(issue_data)
            task_index_to_item[i] = task_dict
            
            # Collect link information for later
            if task_dict.get("story_key"):
                pending_links.append({
                    "index": i,
                    "from": None,  # Will be set after ticket creation
                    "to": task_dict["story_key"],
                    "type": "Work item split",
                    "direction": "outward"
                })
            
            if task_dict.get("blocks"):
                for blocked_key in task_dict["blocks"]:
                    pending_links.append({
                        "index": i,
                        "from": None,  # Will be set after ticket creation
                        "to": blocked_key,
                        "type": "Blocks",
                        "direction": "outward"
                    })
        
        # Create all tickets first
        job.progress = {"message": f"Creating {len(tickets_data)} task tickets in bulk..."}
        logger.info(f"Creating {len(tickets_data)} task tickets in bulk...")
        bulk_results = jira_client.bulk_create_tickets(tickets_data)
        
        created_ticket_keys = bulk_results.get("created_tickets", [])
        failed_tickets = bulk_results.get("failed_tickets", [])
        
        # Build results and mappings for dependency resolution
        results = []
        successful = 0
        failed = 0
        index_to_ticket_key = {}  # Map index to created ticket key
        task_id_to_ticket_key = {}  # Map task_id (UUID) to created ticket key for dependency resolution
        
        for i in range(len(tasks_data)):
            if i < len(created_ticket_keys):
                ticket_key = created_ticket_keys[i]
                index_to_ticket_key[i] = ticket_key
                
                # Build task_id -> ticket_key mapping for UUID-based dependency resolution
                task_id = tasks_data[i].get("task_id")
                if task_id:
                    task_id_to_ticket_key[task_id] = ticket_key
                    logger.debug(f"Mapped task_id {task_id} -> {ticket_key}")
                
                results.append({
                    "index": i,
                    "success": True,
                    "ticket_key": ticket_key,
                    "error": None,
                    "links_created": []
                })
                successful += 1
            else:
                error_msg = "Failed to create ticket"
                if i < len(failed_tickets):
                    error_msg = str(failed_tickets[i])
                results.append({
                    "index": i,
                    "success": False,
                    "ticket_key": None,
                    "error": error_msg,
                    "links_created": []
                })
                failed += 1
        
        logger.info(f"Built task_id mapping with {len(task_id_to_ticket_key)} entries for dependency resolution")
        
        # Also build summary -> ticket_key mapping for summary-based dependency resolution
        summary_to_ticket_key = {}
        for i, task_dict in enumerate(tasks_data):
            if i in index_to_ticket_key:
                summary = task_dict.get("summary")
                if summary:
                    summary_to_ticket_key[summary] = index_to_ticket_key[i]
        logger.info(f"Built summary mapping with {len(summary_to_ticket_key)} entries for dependency resolution")
        
        # Now create all links after all tickets are created
        job.progress = {"message": f"All tickets created. Creating {len(pending_links)} pending links..."}
        logger.info(f"All tickets created. Creating {len(pending_links)} pending links...")
        
        # Helper function to check if a string is a UUID
        def is_uuid(value: str) -> bool:
            import uuid as uuid_module
            try:
                uuid_module.UUID(value)
                return True
            except (ValueError, AttributeError):
                return False
        
        for link_info in pending_links:
            if hasattr(ctx, 'job') and ctx.job.cancelled:
                break
            
            index = link_info["index"]
            if index not in index_to_ticket_key:
                continue  # Skip if ticket creation failed
            
            source_key = index_to_ticket_key[index]
            target_key = link_info["to"]
            link_type = link_info["type"]
            direction = link_info.get("direction", "outward")
            
            # Resolve target_key if it's a task_id (UUID) or task summary
            original_target = target_key
            resolved = False
            
            # First, try to resolve as UUID (task_id)
            if is_uuid(target_key):
                resolved_key = task_id_to_ticket_key.get(target_key)
                if resolved_key:
                    target_key = resolved_key
                    resolved = True
                    logger.info(f"Resolved task_id {original_target} -> {target_key} for {link_type} link")
            
            # If not a UUID or not resolved, try to resolve as task summary
            if not resolved and target_key in summary_to_ticket_key:
                resolved_key = summary_to_ticket_key[target_key]
                target_key = resolved_key
                resolved = True
                logger.info(f"Resolved task summary '{original_target}' -> {target_key} for {link_type} link")
            
            # If it's a UUID that couldn't be resolved, skip this link
            if not resolved and is_uuid(original_target):
                logger.warning(f"Could not resolve task_id {original_target} to JIRA key - task may not exist in this batch or was not created")
                results[index]["links_created"].append({
                    "link_type": link_type,
                    "source_key": source_key,
                    "target_key": original_target,
                    "status": "failed",
                    "error": f"Could not resolve task_id {original_target} to JIRA key"
                })
                continue
            
            # If still not resolved, assume it's already a JIRA key (e.g., "BIF-1234")
            
            # For "Work item split", we need to swap source and target to get correct relationship
            # With direction="outward": inwardIssue=source, outwardIssue=target
            # So: source=story, target=task, direction="outward"
            # This creates: inwardIssue=story, outwardIssue=task
            # This makes Task show "split from" Story correctly
            if link_type == "Work item split":
                # Swap: Story as source, Task as target, direction="outward"
                # This creates: inwardIssue=story, outwardIssue=task
                link_success = jira_client.create_issue_link_generic(
                    source_key=target_key,  # Story as source
                    target_key=source_key,  # Task as target
                    link_type=link_type,
                    direction="outward"  # This makes: inwardIssue=source (story), outwardIssue=target (task)
                )
            else:
                # For other link types, use original parameters
                link_success = jira_client.create_issue_link_generic(
                    source_key=source_key,
                    target_key=target_key,
                    link_type=link_type,
                    direction=direction
                )
            
            if link_success:
                results[index]["links_created"].append({
                    "link_type": link_type,
                    "source_key": source_key,
                    "target_key": target_key,
                    "status": "created"
                })
            else:
                results[index]["links_created"].append({
                    "link_type": link_type,
                    "source_key": source_key,
                    "target_key": target_key,
                    "status": "failed"
                })
        
        message = f"Bulk creation completed: {successful} successful, {failed} failed"
        logger.info(message)
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = {
            "total_tasks": len(tasks_data),
            "successful": successful,
            "failed": failed,
            "results": results,
            "created_tickets": created_ticket_keys,
            "message": message
        }
        job.progress = {"message": message}
        job.processed_tickets = len(tasks_data)
        job.successful_tickets = successful
        job.failed_tickets = failed
        
        # Unregister all story keys when job completes
        story_keys = list(set([task.get("story_key") for task in tasks_data]))
        for story_key in story_keys:
            unregister_ticket_job(story_key)
        
        logger.info(f"Job {job_id} completed: bulk created {len(tasks_data)} tasks ({successful} successful, {failed} failed)")
        
        return job.results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister story keys on failure
            story_keys = list(set([task.get("story_key") for task in tasks_data]))
            for story_key in story_keys:
                unregister_ticket_job(story_key)
        raise


async def process_story_coverage_worker(ctx, job_id: str, story_key: str, include_test_cases: bool = True,
                                       additional_context: Optional[str] = None,
                                       llm_model: Optional[str] = None, llm_provider: Optional[str] = None):
    """ARQ worker function for analyzing story coverage"""
    _initialize_services_if_needed()
    jira_client = get_jira_client()
    llm_client = get_llm_client()
    config = get_config()
    
    try:
        job = _get_or_create_job(job_id, "story_coverage", f"Analyzing coverage for story {story_key}...")
        job.ticket_key = story_key
        
        # Check if cancelled
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            unregister_ticket_job(story_key)
            return
        
        if not jira_client:
            raise RuntimeError("JIRA client not initialized")
        
        if not llm_client:
            raise RuntimeError("LLM client not initialized")
        
        # Create custom LLM client if specified
        analysis_llm_client = llm_client
        if llm_provider or llm_model:
            from .utils import create_custom_llm_client
            analysis_llm_client = create_custom_llm_client(llm_provider, llm_model)
        
        job.progress = {"message": "Initializing analyzer..."}
        
        # Import and create the analyzer
        from src.story_coverage_analyzer import StoryCoverageAnalyzer
        
        analyzer = StoryCoverageAnalyzer(
            jira_client=jira_client,
            llm_client=analysis_llm_client,
            config=config.__dict__ if hasattr(config, '__dict__') else {}
        )
        
        job.progress = {"message": "Fetching story and tasks..."}
        
        # Perform analysis
        result = analyzer.analyze_coverage(
            story_key=story_key,
            include_test_cases=include_test_cases,
            additional_context=additional_context
        )
        
        if not result.get('success', False):
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = result.get('error', 'Analysis failed')
            job.progress = {"message": f"Analysis failed: {result.get('error', 'Unknown error')}"}
            unregister_ticket_job(story_key)
            return
        
        # Convert result to response format
        from .models.story_analysis import StoryCoverageResponse
        coverage_response = StoryCoverageResponse(**result)
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = coverage_response.dict()
        job.progress = {
            "message": f"Analysis completed: {result.get('coverage_percentage', 0)}% coverage",
            "coverage_percentage": result.get('coverage_percentage', 0)
        }
        job.successful_tickets = 1
        
        # Unregister story key when job completes
        unregister_ticket_job(story_key)
        
        logger.info(f"Job {job_id} completed: analyzed coverage for story {story_key} - {result.get('coverage_percentage', 0)}% coverage")
        
        # Return results so ARQ stores them in Redis for persistence
        return coverage_response.dict()
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister story key on failure
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_epic_creation_worker(ctx, job_id: str, epic_key: str, operation_mode: str, create_tickets: bool):
    """ARQ worker function for epic planning and creation"""
    _initialize_services_if_needed()
    generator = get_generator()
    
    try:
        job = _get_or_create_job(job_id, "epic_creation", f"Planning and creating tickets for epic {epic_key}...")
        job.ticket_key = epic_key
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            unregister_ticket_job(epic_key)
            return
        
        if not generator.planning_service:
            raise RuntimeError("Planning service not available - requires Confluence client configuration")
        
        # Create planning context
        from src.planning_models import PlanningContext, OperationMode
        
        mode_map = {
            "documentation": OperationMode.DOCUMENTATION,
            "planning": OperationMode.PLANNING,
            "hybrid": OperationMode.HYBRID
        }
        
        job.progress = {"message": "Creating planning context..."}
        
        context = PlanningContext(
            epic_key=epic_key,
            mode=mode_map.get(operation_mode, OperationMode.HYBRID),
            include_analysis=True,
            max_stories_per_epic=20,
            max_tasks_per_story=8
        )
        
        job.progress = {"message": "Executing planning and creation..."}
        
        # Execute planning with creation
        results = generator.planning_service.execute_planning_with_creation(
            context, 
            create_tickets=create_tickets
        )
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = results
        job.progress = {"message": f"Epic planning and creation completed: {results.get('success', False)}"}
        
        # Count created tickets
        if results.get("creation_results"):
            created_tickets = results["creation_results"].get("created_tickets", {})
            total_created = len(created_tickets.get("stories", [])) + len(created_tickets.get("tasks", []))
            job.successful_tickets = total_created
        
        # Unregister epic key when job completes
        unregister_ticket_job(epic_key)
        
        logger.info(f"Job {job_id} completed: epic planning and creation for {epic_key}")
        
        # Return results so ARQ stores them in Redis for persistence
        return results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister epic key on failure
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_story_creation_worker(ctx, job_id: str, epic_key: str, story_count: Optional[int], create_tickets: bool):
    """ARQ worker function for creating stories for an epic"""
    _initialize_services_if_needed()
    generator = get_generator()
    
    try:
        job = _get_or_create_job(job_id, "story_creation", f"Creating stories for epic {epic_key}...")
        job.ticket_key = epic_key
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            unregister_ticket_job(epic_key)
            return
        
        if not generator.planning_service:
            raise RuntimeError("Planning service not available - requires Confluence client configuration")
        
        # Generate stories first
        from src.planning_models import PlanningContext, OperationMode
        
        job.progress = {"message": "Generating stories..."}
        
        context = PlanningContext(
            epic_key=epic_key,
            mode=OperationMode.PLANNING,
            max_stories_per_epic=story_count or 5
        )
        
        planning_result = generator.planning_service.generate_stories_for_epic(context)
        
        if not planning_result.success or not planning_result.epic_plan:
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = "Story generation failed"
            job.progress = {"message": f"Story generation failed: {planning_result.errors}"}
            job.results = {
                "success": False,
                "errors": planning_result.errors,
                "epic_key": epic_key
            }
            unregister_ticket_job(epic_key)
            return job.results
        
        # Create stories if requested
        job.progress = {"message": "Creating story tickets..."}
        
        creation_results = generator.planning_service.create_stories_for_epic(
            epic_key,
            planning_result.epic_plan.stories,
            dry_run=not create_tickets
        )
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = {
            "epic_key": epic_key,
            "planning_results": planning_result.dict(),
            "creation_results": creation_results,
            "success": creation_results.get("success", False)
        }
        
        # Count created stories
        if creation_results.get("created_tickets"):
            created_stories = creation_results["created_tickets"].get("stories", [])
            job.successful_tickets = len(created_stories)
        
        job.progress = {"message": f"Story creation completed: {job.successful_tickets} stories created"}
        
        # Unregister epic key when job completes
        unregister_ticket_job(epic_key)
        
        logger.info(f"Job {job_id} completed: created stories for epic {epic_key}")
        
        # Return results so ARQ stores them in Redis for persistence
        return job.results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister epic key on failure
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_task_creation_worker(ctx, job_id: str, story_keys: List[str], tasks_per_story: Optional[int], create_tickets: bool):
    """ARQ worker function for creating tasks for stories"""
    _initialize_services_if_needed()
    generator = get_generator()
    
    try:
        job = _get_or_create_job(job_id, "task_creation", f"Creating tasks for {len(story_keys)} stories...")
        job.ticket_keys = story_keys.copy()
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            # Unregister all story keys
            for story_key in story_keys:
                unregister_ticket_job(story_key)
            return
        
        if not generator.planning_service:
            raise RuntimeError("Planning service not available - requires Confluence client configuration")
        
        # Generate tasks first
        from src.planning_models import PlanningContext, OperationMode
        
        # Derive epic_key from first story_key
        epic_key = story_keys[0].split('-')[0] + "-000"
        
        job.progress = {"message": "Generating tasks..."}
        
        context = PlanningContext(
            epic_key=epic_key,
            mode=OperationMode.PLANNING,
            max_tasks_per_story=tasks_per_story or 3
        )
        
        planning_result = generator.planning_service.generate_tasks_for_stories(
            story_keys, context
        )
        
        if not planning_result.success or not planning_result.epic_plan:
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = "Task generation failed"
            job.progress = {"message": f"Task generation failed: {planning_result.errors}"}
            job.results = {
                "success": False,
                "errors": planning_result.errors,
                "story_keys": story_keys
            }
            # Unregister all story keys on failure
            for story_key in story_keys:
                unregister_ticket_job(story_key)
            return job.results
        
        # Extract all tasks from stories
        all_tasks = []
        for story in planning_result.epic_plan.stories:
            all_tasks.extend(story.tasks)
        
        # Create tasks if requested
        job.progress = {"message": "Creating task tickets..."}
        
        creation_results = generator.planning_service.create_tasks_for_stories(
            all_tasks,
            story_keys,
            dry_run=not create_tickets
        )
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = {
            "story_keys": story_keys,
            "planning_results": planning_result.dict(),
            "creation_results": creation_results,
            "success": creation_results.get("success", False)
        }
        
        # Count created tasks
        if creation_results.get("created_tickets"):
            created_tasks = creation_results["created_tickets"].get("tasks", [])
            job.successful_tickets = len(created_tasks)
        
        job.progress = {"message": f"Task creation completed: {job.successful_tickets} tasks created"}
        
        # Unregister all story keys when job completes
        for story_key in story_keys:
            unregister_ticket_job(story_key)
        
        logger.info(f"Job {job_id} completed: created tasks for {len(story_keys)} stories")
        
        # Return results so ARQ stores them in Redis for persistence
        return job.results
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            # Unregister all story keys on failure
            if job.ticket_keys:
                for story_key in job.ticket_keys:
                    unregister_ticket_job(story_key)
        raise


async def process_sprint_planning_worker(ctx, job_id: str, epic_key: str, board_id: int,
                                         sprint_capacity_days: float, start_date: Optional[str] = None,
                                         sprint_duration_days: int = 14, team_id: Optional[str] = None,
                                         auto_create_sprints: bool = False, dry_run: bool = True):
    """ARQ worker function for sprint planning"""
    _initialize_services_if_needed()
    
    try:
        job = _get_or_create_job(job_id, "sprint_planning", f"Planning sprint for epic {epic_key}...")
        job.ticket_key = epic_key
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            unregister_ticket_job(epic_key)
            return
        
        # Get sprint planning service
        from .routes.sprint_planning import get_sprint_planning_service
        sprint_service = get_sprint_planning_service()
        
        if not sprint_service:
            raise RuntimeError("Sprint planning service not available")
        
        job.progress = {"message": "Planning epic tasks to sprints..."}
        
        result = sprint_service.plan_epic_to_sprints(
            epic_key=epic_key,
            board_id=board_id,
            sprint_capacity_days=sprint_capacity_days,
            start_date=start_date,
            sprint_duration_days=sprint_duration_days,
            team_id=team_id,
            auto_create_sprints=auto_create_sprints,
            dry_run=dry_run
        )
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = result
        job.progress = {"message": f"Sprint planning completed: {result.get('total_tasks', 0)} tasks across {result.get('total_sprints', 0)} sprints"}
        job.successful_tickets = result.get('total_tasks', 0) if result.get('success') else 0
        
        # Unregister epic key when job completes
        unregister_ticket_job(epic_key)
        
        logger.info(f"Job {job_id} completed: sprint planning for epic {epic_key}")
        
        return result
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise


async def process_timeline_planning_worker(ctx, job_id: str, epic_key: str, board_id: int,
                                           start_date: Optional[str] = None, sprint_duration_days: int = 14,
                                           team_capacity_days: Optional[float] = None,
                                           team_id: Optional[str] = None, dry_run: bool = True):
    """ARQ worker function for timeline planning"""
    _initialize_services_if_needed()
    
    try:
        job = _get_or_create_job(job_id, "timeline_planning", f"Creating timeline for epic {epic_key}...")
        job.ticket_key = epic_key
        
        if hasattr(ctx, 'job') and ctx.job.cancelled:
            job.status = "cancelled"
            job.completed_at = datetime.now()
            job.progress = {"message": "Job was cancelled"}
            unregister_ticket_job(epic_key)
            return
        
        # Get sprint planning service
        from .routes.sprint_planning import get_sprint_planning_service
        sprint_service = get_sprint_planning_service()
        
        if not sprint_service:
            raise RuntimeError("Sprint planning service not available")
        
        job.progress = {"message": "Creating timeline schedule..."}
        
        result = sprint_service.schedule_timeline(
            epic_key=epic_key,
            board_id=board_id,
            start_date=start_date,
            sprint_duration_days=sprint_duration_days,
            team_capacity_days=team_capacity_days,
            team_id=team_id,
            dry_run=dry_run
        )
        
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = result
        job.progress = {"message": f"Timeline created: {len(result.get('sprints', []))} sprints scheduled"}
        job.successful_tickets = len(result.get('sprints', [])) if result.get('success') else 0
        
        # Unregister epic key when job completes
        unregister_ticket_job(epic_key)
        
        logger.info(f"Job {job_id} completed: timeline planning for epic {epic_key}")
        
        return result
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        if job_id in jobs:
            job = jobs[job_id]
            job.status = "failed"
            job.completed_at = datetime.now()
            job.error = str(e)
            job.progress = {"message": f"Job failed: {str(e)}"}
            if job.ticket_key:
                unregister_ticket_job(job.ticket_key)
        raise
