"""
Generation Routes
Endpoints for ticket description generation
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime
from typing import Optional
import uuid
import logging

from ..models.generation import SingleTicketRequest, JQLRequest, TicketResponse, BatchResponse, JobStatus
from ..dependencies import get_jira_client, get_generator
from ..dependencies import jobs, get_active_job_for_ticket, register_ticket_job
from ..auth import get_current_user
from ..job_queue import get_redis_pool
from ..utils import normalize_ticket_key

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/generate/single", 
          tags=["Generation"],
          summary="Generate description for a single ticket",
          description="Generate a description for a single JIRA ticket. Supports both ticket keys (e.g., PROJ-123) and full JIRA URLs. Use async_mode=true to process in the background.")
async def generate_single_description(
    request: SingleTicketRequest, 
    current_user: str = Depends(get_current_user)
):
    """Generate description for a single ticket"""
    generator = get_generator()
    
    try:
        if not generator:
            raise HTTPException(status_code=503, detail="Service not initialized")
        
        # Parse ticket_key from URL if needed
        ticket_key = normalize_ticket_key(request.ticket_key)
        if not ticket_key:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid ticket key format: {request.ticket_key}. Please provide a valid JIRA ticket key or URL."
            )
        
        # If async mode, enqueue job
        if request.async_mode:
            # Check for duplicate active job
            active_job_id = get_active_job_for_ticket(ticket_key)
            if active_job_id:
                # Verify job actually exists (defensive check)
                if active_job_id in jobs:
                    active_job = jobs[active_job_id]
                    raise HTTPException(
                        status_code=409,
                        detail=f"Ticket {ticket_key} is already being processed in job {active_job_id}",
                        headers={"X-Active-Job-Id": active_job_id, "X-Active-Job-Status-Url": f"/jobs/{active_job_id}"}
                    )
                else:
                    # Job ID returned but job doesn't exist - clean up stale mapping
                    logger.warning(f"Stale ticket_jobs mapping found: {ticket_key} -> {active_job_id} (job not in jobs dict)")
                    from ..dependencies import unregister_ticket_job
                    unregister_ticket_job(ticket_key)
                    # Continue to create new job
            
            job_id = str(uuid.uuid4())
            
            jobs[job_id] = JobStatus(
                job_id=job_id,
                job_type="single",
                status="started",
                progress={"message": f"Queued for processing ticket {ticket_key}"},
                started_at=datetime.now(),
                processed_tickets=0,
                successful_tickets=0,
                failed_tickets=0,
                ticket_key=ticket_key
            )
            
            # Register ticket key for duplicate prevention
            register_ticket_job(ticket_key, job_id)
            
            redis_pool = await get_redis_pool()
            await redis_pool.enqueue_job(
                'process_single_ticket_worker',
                job_id=job_id,
                ticket_key=ticket_key,
                update_jira=request.update_jira,
                llm_model=request.llm_model,
                llm_provider=request.llm_provider,
                additional_context=request.additional_context,
                _job_id=job_id
            )
            
            logger.info(f"Enqueued single ticket job {job_id} for ticket {ticket_key}")
            
            return BatchResponse(
                job_id=job_id,
                status="started",
                message=f"Ticket {ticket_key} queued for processing",
                status_url=f"/jobs/{job_id}",
                jql="",  # Not applicable for single ticket
                max_results=1,
                update_jira=request.update_jira,
                safety_note="JIRA will only be updated if update_jira is explicitly set to true"
            )
        
        # Synchronous mode (original behavior)
        jira_client = get_jira_client()
        logger.info(f"Processing single ticket: {ticket_key}, update_jira={request.update_jira}")
        
        if request.llm_model or request.llm_provider:
            logger.info(f"Using custom LLM settings - provider: {request.llm_provider or 'default'}, model: {request.llm_model or 'default'}")
        
        ticket_data = jira_client.get_ticket(ticket_key)
        if not ticket_data:
            return TicketResponse(
                ticket_key=ticket_key,
                summary="",
                assignee_name=None,
                parent_name=None,
                generated_description=None,
                success=False,
                error="Ticket not found",
                skipped_reason=None,
                updated_in_jira=False,
                llm_provider=None,
                llm_model=None
            )
        
        summary = ticket_data.get('fields', {}).get('summary', '')
        assignee = ticket_data.get('fields', {}).get('assignee')
        assignee_name = assignee.get('displayName') if assignee else None
        parent = ticket_data.get('fields', {}).get('parent')
        parent_name = parent.get('fields', {}).get('summary') if parent else None
        
        result = generator.process_ticket(
            ticket_key=ticket_key,
            dry_run=not request.update_jira,
            llm_model=request.llm_model,
            llm_provider=request.llm_provider,
            additional_context=request.additional_context
        )
        
        generated_description = None
        system_prompt = None
        user_prompt = None
        if result.description:
            generated_description = result.description.description
            system_prompt = result.description.system_prompt
            user_prompt = result.description.user_prompt
        
        return TicketResponse(
            ticket_key=ticket_key,
            summary=summary,
            assignee_name=assignee_name,
            parent_name=parent_name,
            generated_description=generated_description,
            success=result.success,
            error=result.error,
            skipped_reason=result.skipped_reason,
            updated_in_jira=request.update_jira and result.success,
            llm_provider=result.llm_provider,
            llm_model=result.llm_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            additional_context=request.additional_context
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing ticket {request.ticket_key}: {e}")
        if request.async_mode:
            raise HTTPException(status_code=500, detail=str(e))
        # Use normalized ticket_key in error response
        normalized_key = normalize_ticket_key(request.ticket_key) or request.ticket_key
        return TicketResponse(
            ticket_key=normalized_key,
            summary="",
            assignee_name=None,
            parent_name=None,
            generated_description=None,
            success=False,
            error=str(e),
            skipped_reason=None,
            updated_in_jira=False,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model
        )


@router.post("/generate/batch",
          response_model=BatchResponse,
          tags=["Generation"],
          summary="Start batch processing of tickets",
          description="Process multiple tickets using a JQL query. Preview mode by default. Set update_jira=true to apply changes.")
async def start_batch_processing(
    request: JQLRequest, 
    current_user: str = Depends(get_current_user)
):
    """Start batch processing of tickets based on JQL query"""
    generator = get_generator()
    
    try:
        if not generator:
            raise HTTPException(status_code=503, detail="Service not initialized")
        
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        
        # For batch jobs, we'll check duplicates per ticket as they're processed
        # Initialize job status (ticket_keys will be populated by worker)
        jobs[job_id] = JobStatus(
            job_id=job_id,
            job_type="batch",
            status="started",
            progress={"message": f"Batch processing started in {'UPDATE' if request.update_jira else 'PREVIEW'} mode"},
            started_at=datetime.now(),
            total_tickets=None,
            processed_tickets=0,
            successful_tickets=0,
            failed_tickets=0,
            ticket_keys=[]  # Will be populated by worker
        )
        
        # Log LLM model/provider overrides if provided
        if request.llm_model or request.llm_provider:
            logger.info(f"Using custom LLM settings - provider: {request.llm_provider or 'default'}, model: {request.llm_model or 'default'}")
        
        # Get Redis pool and enqueue job
        redis_pool = await get_redis_pool()
        await redis_pool.enqueue_job(
            'process_batch_tickets_worker',
            job_id=job_id,
            jql=request.jql,
            max_results=request.max_results,
            update_jira=request.update_jira,
            llm_model=request.llm_model,
            llm_provider=request.llm_provider,
            _job_id=job_id  # Use job_id as Arq job ID for tracking
        )
        
        logger.info(f"Enqueued batch job {job_id} for JQL: {request.jql}")
        
        mode_message = "UPDATE mode - JIRA will be modified" if request.update_jira else "PREVIEW mode - no JIRA changes"
        
        return BatchResponse(
            job_id=job_id,
            status="started",
            message=f"Batch processing started in {mode_message}",
            status_url=f"/jobs/{job_id}",
            jql=request.jql,
            max_results=request.max_results,
            update_jira=request.update_jira,
            safety_note="JIRA will only be updated if update_jira is explicitly set to true"
        )
        
    except Exception as e:
        logger.error(f"Error starting batch processing: {e}")
        raise HTTPException(status_code=500, detail=str(e))



