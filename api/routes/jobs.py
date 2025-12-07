"""
Jobs Routes
Endpoints for job tracking and status
"""
from fastapi import APIRouter, HTTPException, Query, Depends
from datetime import datetime, timezone
from typing import Optional
import logging

from ..models.generation import JobStatus
from ..dependencies import jobs, get_job_by_ticket_key
from ..auth import get_current_user
from ..job_queue import get_redis_pool

router = APIRouter()
logger = logging.getLogger(__name__)


def _normalize_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize datetime to UTC-aware for comparison.
    Converts timezone-naive datetimes to UTC-aware.
    Leaves timezone-aware datetimes unchanged.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Timezone-naive: assume UTC and make it aware
        return dt.replace(tzinfo=timezone.utc)
    # Already timezone-aware: convert to UTC if needed
    return dt.astimezone(timezone.utc)


async def _reconstruct_job_from_redis(job_id: str) -> Optional[JobStatus]:
    """Reconstruct a job from Redis if it exists there but not in memory"""
    try:
        redis_pool = await get_redis_pool()
        
        # Try to get job using Job class (for running jobs) or all_job_results (for completed jobs)
        # First, try to create a Job object to check if it exists
        from arq.jobs import Job
        try:
            arq_job = Job(job_id, redis_pool)
            # Check if job exists by trying to get its info
            job_info = await arq_job.info()
            if job_info:
                # Extract job info from ARQ job
                kwargs = job_info.get('kwargs', {}) or {}
            job_type = kwargs.get('job_type', 'single')
            # Check for story_coverage first (has story_key but not ticket_key in kwargs)
            if 'story_key' in kwargs and 'ticket_key' not in kwargs:
                job_type = 'story_coverage'
            elif 'ticket_key' in kwargs:
                job_type = 'single'
            elif 'jql' in kwargs:
                job_type = 'batch'
            elif 'epic_key' in kwargs and 'story_keys' not in kwargs and 'prd_url' in kwargs:
                job_type = 'prd_story_sync'
            elif 'epic_key' in kwargs and 'story_keys' not in kwargs:
                job_type = 'story_generation'
            elif 'story_keys' in kwargs:
                job_type = 'task_generation'
            elif 'test_type' in kwargs:
                job_type = 'test_generation'
            
            # Determine status by trying to get the result
            # If we can get result immediately, job is completed/failed
            # If we can't, job is still running (started/processing)
            arq_results = None
            error = None
            status = "started"  # Default
            
            try:
                # Try to get result with very short timeout (don't wait)
                arq_results = await arq_job.result(timeout=0.01)
                # If we got a result, job is done - check if it's success or failure
                # Check job info to see if it was successful
                try:
                    job_info = await arq_job.info()
                    if job_info and job_info.get('success') is False:
                        status = "failed"
                        error = str(arq_results) if arq_results else "Job failed"
                    else:
                        status = "completed"
                except:
                    # Can't get info, assume completed if we got a result
                    status = "completed"
            except Exception as e:
                # Result not available - job is still running
                # Try to get job info to determine if it's processing or just queued
                try:
                    job_info = await arq_job.info()
                    if job_info:
                        arq_status = job_info.get('status', '')
                        if arq_status == 'in_progress':
                            status = "processing"
                        elif arq_status in ['queued', 'deferred']:
                            status = "started"
                        else:
                            # Check if job failed but result not available yet
                            if job_info.get('success') is False:
                                status = "failed"
                                error = "Job failed"
                            else:
                                status = "started"  # Default to started
                except:
                    # Can't get info, assume started
                    status = "started"
            
            # Get timestamps from job info
            enqueue_time = None
            start_time = None
            finish_time = None
            try:
                job_info = await arq_job.info()
                if job_info:
                    enqueue_time = job_info.get('enqueue_time')
                    start_time = job_info.get('start_time')
                    finish_time = job_info.get('finish_time')
            except:
                # Fallback to direct attributes if available
                enqueue_time = getattr(arq_job, 'enqueue_time', None)
                start_time = getattr(arq_job, 'start_time', None)
                finish_time = getattr(arq_job, 'finish_time', None)
            
            # Determine progress message
            if status == "started":
                progress_msg = "Queued for processing"
            elif status == "processing":
                progress_msg = "Currently processing"
            elif status == "completed":
                progress_msg = "Job completed (reconstructed from Redis)"
            elif status == "failed":
                progress_msg = "Job failed (reconstructed from Redis)"
            else:
                progress_msg = "Job status unknown"
            
            # Extract ticket keys
            ticket_key = kwargs.get('ticket_key') or kwargs.get('story_key') or kwargs.get('epic_key')
            ticket_keys = kwargs.get('story_keys') or (kwargs.get('ticket_keys') if 'ticket_keys' in kwargs else None)
            
            # Reconstruct JobStatus
            reconstructed_job = JobStatus(
                job_id=job_id,
                job_type=job_type,
                status=status,
                progress={"message": progress_msg},
                results=arq_results,
                started_at=start_time if start_time else enqueue_time,
                completed_at=finish_time if status in ["completed", "failed", "cancelled"] else None,
                processed_tickets=1 if job_type in ['single', 'story_coverage'] else (len(ticket_keys) if ticket_keys else 0),
                successful_tickets=1 if status == "completed" and job_type in ['single', 'story_coverage'] else 0,
                failed_tickets=1 if status == "failed" and job_type in ['single', 'story_coverage'] else 0,
                error=error,
                ticket_key=ticket_key,
                ticket_keys=ticket_keys
            )
            
            # Store in memory for future requests
            jobs[job_id] = reconstructed_job
            logger.info(f"Job {job_id} reconstructed from Redis with status {status}, type={job_type}")
            return reconstructed_job
        except Exception as job_error:
            # Job might not exist or info() failed, try all_job_results instead
            logger.debug(f"Could not get job {job_id} info: {job_error}")
        
        # If Job.info() didn't find it, try checking all_job_results() for completed jobs
        # (This is a fallback for very old completed jobs)
        all_results = await redis_pool.all_job_results()
        for job_result in all_results:
            if job_result.job_id == job_id:
                # Extract job info from ARQ result
                kwargs = job_result.kwargs or {}
                job_type = kwargs.get('job_type', 'single')
                # Check for story_coverage first (has story_key but not ticket_key in kwargs)
                if 'story_key' in kwargs and 'ticket_key' not in kwargs:
                    job_type = 'story_coverage'
                elif 'ticket_key' in kwargs:
                    job_type = 'single'
                elif 'jql' in kwargs:
                    job_type = 'batch'
                elif 'epic_key' in kwargs and 'story_keys' not in kwargs and 'prd_url' in kwargs:
                    job_type = 'prd_story_sync'
                elif 'epic_key' in kwargs and 'story_keys' not in kwargs:
                    job_type = 'story_generation'
                elif 'story_keys' in kwargs:
                    job_type = 'task_generation'
                elif 'test_type' in kwargs:
                    job_type = 'test_generation'
                
                # Determine status
                if job_result.success:
                    status = "completed"
                else:
                    status = "failed"
                
                # Extract results from ARQ result
                arq_results = job_result.result if hasattr(job_result, 'result') and job_result.result is not None else None
                
                logger.info(f"Reconstructing job {job_id} from Redis results: status={status}, has_results={arq_results is not None}")
                
                # Reconstruct JobStatus
                reconstructed_job = JobStatus(
                    job_id=job_id,
                    job_type=job_type,
                    status=status,
                    progress={"message": "Job completed (reconstructed from Redis)"},
                    results=arq_results,
                    started_at=job_result.start_time if job_result.start_time else job_result.enqueue_time,
                    completed_at=job_result.finish_time,
                    processed_tickets=1 if job_type in ['single', 'story_coverage'] else 0,
                    successful_tickets=1 if job_result.success else 0,
                    failed_tickets=0 if job_result.success else 1,
                    error=str(job_result.result) if not job_result.success and job_result.result else None,
                    ticket_key=kwargs.get('ticket_key') or kwargs.get('story_key') or kwargs.get('epic_key'),
                    ticket_keys=kwargs.get('story_keys')
                )
                
                # Store in memory for future requests
                jobs[job_id] = reconstructed_job
                logger.info(f"Job {job_id} reconstructed from Redis results with status {status}")
                return reconstructed_job
                
    except Exception as e:
        logger.warning(f"Error reconstructing job {job_id} from Redis: {e}", exc_info=True)
    return None


@router.get("/jobs/{job_id}",
         response_model=JobStatus,
         tags=["Jobs"],
         summary="Get job status and results",
         description="Get the status and results of a background job. Works with batch, single, story_coverage, story_generation, task_generation, test_generation, and prd_story_sync jobs.")
async def get_job_status(job_id: str, current_user: str = Depends(get_current_user)):
    """Get the status of a batch processing job"""
    # Check in-memory first
    if job_id in jobs:
        job = jobs[job_id]
        # If job is in started/processing status, always check Redis for actual status
        # (worker may have completed it in separate process)
        if job.status in ["started", "processing"]:
            redis_job = await _reconstruct_job_from_redis(job_id)
            if redis_job:
                # Redis has the actual status - use it
                return redis_job
        # If job is completed but has no results, check Redis (worker may have stored results there)
        if job.status == "completed" and (job.results is None or job.results == {}):
            redis_job = await _reconstruct_job_from_redis(job_id)
            if redis_job and redis_job.results is not None:
                # Redis has the results - use it and update in-memory
                jobs[job_id] = redis_job
                return redis_job
        # Job is completed/failed/cancelled in memory, return it
        return job
    
    # If not in memory, try to reconstruct from Redis
    reconstructed = await _reconstruct_job_from_redis(job_id)
    if reconstructed:
        return reconstructed
    
    raise HTTPException(status_code=404, detail="Job not found")


@router.get("/jobs",
         tags=["Jobs"],
         summary="List all jobs",
         description="List all background jobs with their status. Filter by status or job_type.")
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by job status (started, processing, completed, failed, cancelled)"),
    job_type: Optional[str] = Query(None, description="Filter by job type (batch, single, story_coverage, story_generation, task_generation, test_generation, prd_story_sync)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of jobs to return"),
    current_user: str = Depends(get_current_user)
):
    """List all background processing jobs"""
    job_list = list(jobs.values())
    
    # Also check Redis for jobs that aren't in memory
    # Check if we have few jobs in memory (likely after restart) or if filtering for specific statuses
    # Always check Redis for active jobs (started/processing) to ensure we show all current jobs
    should_check_redis = (
        len(job_list) < 10 or 
        status in ["completed", "failed", "started", "processing"] or
        status is None  # No filter means show all jobs, so check Redis
    )
    
    if should_check_redis:
        try:
            redis_pool = await get_redis_pool()
            all_results = await redis_pool.all_job_results()
            # Get job IDs we already have
            existing_job_ids = {job.job_id for job in job_list}
            # Reconstruct missing jobs from Redis (limit to recent 50 to avoid performance issues)
            for job_result in list(all_results)[:50]:
                if job_result.job_id not in existing_job_ids:
                    reconstructed = await _reconstruct_job_from_redis(job_result.job_id)
                    if reconstructed:
                        job_list.append(reconstructed)
        except Exception as e:
            logger.debug(f"Error loading jobs from Redis: {e}")
    
    # Filter by status if provided
    if status:
        job_list = [job for job in job_list if job.status == status]
    
    # Filter by job_type if provided
    if job_type:
        job_list = [job for job in job_list if job.job_type == job_type]
    
    # Sort by start time (most recent first)
    # Normalize datetimes to UTC-aware for comparison
    job_list.sort(key=lambda x: _normalize_datetime(x.started_at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    
    # Apply limit
    job_list = job_list[:limit]
    
    return {
        "jobs": job_list,
        "total": len(job_list),
        "filtered_by_status": status,
        "filtered_by_job_type": job_type
    }


@router.get("/jobs/ticket/{ticket_key}",
         response_model=JobStatus,
         tags=["Jobs"],
         summary="Get job status by ticket key",
         description="Get job status for a ticket. Returns the active job if processing, otherwise the latest completed job.")
async def get_job_status_by_ticket(ticket_key: str, current_user: str = Depends(get_current_user)):
    """Get job status for a specific ticket key"""
    job_data = get_job_by_ticket_key(ticket_key)
    
    if not job_data:
        raise HTTPException(
            status_code=404,
            detail=f"No job found for ticket key: {ticket_key}"
        )
    
    return job_data


@router.delete("/jobs/{job_id}",
         tags=["Jobs"],
         summary="Cancel a running job",
         description="Cancel a running or queued job. Only jobs with status 'started' or 'processing' can be cancelled.")
async def cancel_job(job_id: str, current_user: str = Depends(get_current_user)):
    """Cancel a running job"""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    if job.status not in ["started", "processing"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel job with status: {job.status}")
    
    try:
        # Try to abort the ARQ job
        redis_pool = await get_redis_pool()
        from arq.jobs import Job
        arq_job = Job(job_id, redis_pool)
        try:
            job_info = await arq_job.info()
            if job_info:
                await arq_job.abort()
                logger.info(f"Aborted ARQ job {job_id}")
        except Exception as abort_error:
            logger.warning(f"Could not abort ARQ job {job_id}: {abort_error}")
        
        # Update job status
        job.status = "cancelled"
        job.completed_at = datetime.now()
        job.progress = {"message": "Job was cancelled by user"}
        
        # Unregister ticket keys when job is cancelled
        from ..dependencies import unregister_ticket_job
        if job.ticket_key:
            unregister_ticket_job(job.ticket_key)
        if job.ticket_keys:
            for ticket_key in job.ticket_keys:
                unregister_ticket_job(ticket_key)
        
        return {"message": f"Job {job_id} cancelled successfully", "status": "cancelled"}
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        # Still mark as cancelled in memory even if ARQ abort fails
        job.status = "cancelled"
        job.completed_at = datetime.now()
        job.progress = {"message": f"Job cancellation requested but may still be processing: {str(e)}"}
        return {"message": f"Job {job_id} cancellation requested", "status": "cancelled", "warning": str(e)}

