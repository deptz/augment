"""
Analytics Service
Calculates analytics and metrics for draft PR jobs
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)


class AnalyticsService:
    """
    Service for calculating analytics and metrics for draft PR jobs.
    """
    
    def __init__(self, job_status_retriever):
        """
        Initialize analytics service.
        
        Args:
            job_status_retriever: Function to retrieve job statuses (from Redis/memory)
        """
        self.job_status_retriever = job_status_retriever
    
    async def get_stats(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get overall statistics for draft PR jobs.
        
        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
            status: Optional status filter
            
        Returns:
            Statistics dictionary
        """
        # Get all draft PR jobs
        jobs = await self._get_filtered_jobs(start_date, end_date, status)
        
        if not jobs:
            return {
                "total_jobs": 0,
                "successful_jobs": 0,
                "failed_jobs": 0,
                "success_rate": 0.0,
                "avg_duration_seconds": 0.0,
                "avg_planning_duration": None,
                "avg_applying_duration": None,
                "avg_verifying_duration": None,
                "common_failure_reasons": [],
                "jobs_by_stage": {}
            }
        
        # Calculate basic stats
        total_jobs = len(jobs)
        successful_jobs = sum(1 for j in jobs if j.get("status") == "completed")
        failed_jobs = sum(1 for j in jobs if j.get("status") == "failed")
        success_rate = (successful_jobs / total_jobs * 100) if total_jobs > 0 else 0.0
        
        # Calculate duration stats
        durations = []
        planning_durations = []
        applying_durations = []
        verifying_durations = []
        
        for job in jobs:
            if job.get("started_at") and job.get("completed_at"):
                duration = (job["completed_at"] - job["started_at"]).total_seconds()
                durations.append(duration)
            
            # Extract stage durations from progress/artifacts if available
            # This would require additional tracking in the pipeline
        
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        
        # Count jobs by stage
        jobs_by_stage = Counter(j.get("stage", "UNKNOWN") for j in jobs)
        
        # Common failure reasons
        failure_reasons = []
        for job in jobs:
            if job.get("status") == "failed" and job.get("error"):
                failure_reasons.append(job["error"])
        
        failure_counter = Counter(failure_reasons)
        common_failures = [
            {"reason": reason, "count": count}
            for reason, count in failure_counter.most_common(10)
        ]
        
        return {
            "total_jobs": total_jobs,
            "successful_jobs": successful_jobs,
            "failed_jobs": failed_jobs,
            "success_rate": round(success_rate, 2),
            "avg_duration_seconds": round(avg_duration, 2),
            "avg_planning_duration": None,  # Would need stage timing tracking
            "avg_applying_duration": None,  # Would need stage timing tracking
            "avg_verifying_duration": None,  # Would need stage timing tracking
            "common_failure_reasons": common_failures,
            "jobs_by_stage": dict(jobs_by_stage)
        }
    
    async def get_job_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get job-level analytics.
        
        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
            status: Optional status filter
            
        Returns:
            List of job analytics
        """
        jobs = await self._get_filtered_jobs(start_date, end_date, status)
        
        analytics = []
        for job in jobs:
            duration = None
            if job.get("started_at") and job.get("completed_at"):
                duration = (job["completed_at"] - job["started_at"]).total_seconds()
            
            analytics.append({
                "job_id": job.get("job_id"),
                "story_key": job.get("ticket_key"),
                "status": job.get("status"),
                "stage": job.get("stage"),
                "duration_seconds": duration,
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "error": job.get("error")
            })
        
        return analytics
    
    async def _get_filtered_jobs(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        status: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        Get filtered list of draft PR jobs.
        
        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
            status: Optional status filter
            
        Returns:
            List of job dictionaries
        """
        # This would query Redis or in-memory job store
        # For now, return empty list - implementation depends on job storage
        # In production, this would query Redis for all draft_pr jobs
        return []
