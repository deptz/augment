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
    max_jobs = 10
    job_timeout = 3600  # 1 hour


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
                                         llm_model: Optional[str] = None, llm_provider: Optional[str] = None):
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
            dry_run=dry_run
        )
        
        # Convert to dict for storage
        from .routes.planning import extract_story_details_with_tests, extract_task_details_with_tests
        story_details = extract_story_details_with_tests(planning_result)
        task_details = extract_task_details_with_tests(planning_result)
        
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
                                        llm_provider: Optional[str] = None, additional_context: Optional[str] = None):
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
            additional_context=additional_context
        )
        
        from .routes.planning import extract_story_details_with_tests, extract_task_details_with_tests
        story_details = extract_story_details_with_tests(planning_result)
        task_details = extract_task_details_with_tests(planning_result)
        
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
        story_details = extract_story_details_with_tests(planning_result)
        task_details = extract_task_details_with_tests(planning_result)
        
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


async def process_story_coverage_worker(ctx, job_id: str, story_key: str, include_test_cases: bool = True,
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
            include_test_cases=include_test_cases
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

