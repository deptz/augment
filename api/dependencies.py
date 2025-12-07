"""
Shared Dependencies
Global clients and configuration shared across all routes
"""
from typing import Optional
from src.config import Config
from src.jira_client import JiraClient
from src.bitbucket_client import BitbucketClient
from src.confluence_client import ConfluenceClient
from src.llm_client import LLMClient
from src.generator import DescriptionGenerator
import logging

logger = logging.getLogger(__name__)

# Global variables for clients (initialized on startup)
jira_client: Optional[JiraClient] = None
bitbucket_client: Optional[BitbucketClient] = None
confluence_client: Optional[ConfluenceClient] = None
llm_client: Optional[LLMClient] = None
generator: Optional[DescriptionGenerator] = None
config: Optional[Config] = None

# In-memory storage for job tracking
jobs: dict = {}

# Ticket-to-job mapping for active jobs (ticket_key -> job_id)
# Only tracks jobs with status "started" or "processing"
ticket_jobs: dict[str, str] = {}

# Authentication configuration (will be loaded from config)
auth_config: dict = {
    "enabled": False,
    "username": "",
    "password_hash": ""
}

# Redis pool (initialized on startup)
redis_pool = None


def get_jira_client() -> JiraClient:
    """Get JIRA client instance"""
    if jira_client is None:
        raise RuntimeError("JIRA client not initialized - ensure startup event completed")
    return jira_client


def get_bitbucket_client() -> Optional[BitbucketClient]:
    """Get Bitbucket client instance"""
    return bitbucket_client


def get_confluence_client() -> Optional[ConfluenceClient]:
    """Get Confluence client instance"""
    return confluence_client


def get_llm_client() -> LLMClient:
    """Get LLM client instance"""
    if llm_client is None:
        raise RuntimeError("LLM client not initialized - ensure startup event completed")
    return llm_client


def get_generator() -> DescriptionGenerator:
    """Get DescriptionGenerator instance"""
    if generator is None:
        raise RuntimeError("Generator not initialized - ensure startup event completed")
    return generator


def get_config() -> Config:
    """Get Config instance"""
    if config is None:
        raise RuntimeError("Config not initialized - ensure startup event completed")
    return config


def get_active_job_for_ticket(ticket_key: str) -> Optional[str]:
    """
    Get active job ID for a ticket key if one exists.
    Returns job_id if ticket is actively being processed (started or processing status).
    Automatically cleans up stale jobs that have been stuck in "started" status for too long.
    """
    if ticket_key not in ticket_jobs:
        return None
    
    job_id = ticket_jobs[ticket_key]
    if job_id in jobs:
        job = jobs[job_id]
        if job.status == "processing":
            return job_id
        elif job.status == "started":
            # Check if job has been stuck in "started" for too long (5 minutes)
            from datetime import datetime, timedelta
            if job.started_at:
                elapsed = datetime.now() - job.started_at
                if elapsed > timedelta(minutes=5):
                    # Job stuck in "started" for too long - likely worker isn't processing it
                    logger.warning(f"Job {job_id} stuck in 'started' status for {elapsed.total_seconds():.0f}s - cleaning up")
                    job.status = "failed"
                    job.completed_at = datetime.now()
                    job.error = "Job stuck in started status - worker may not be running"
                    job.progress = {"message": "Job timed out waiting for worker"}
                    del ticket_jobs[ticket_key]
                    return None
            return job_id
        else:
            # Job is no longer active (completed, failed, cancelled), clean up mapping
            del ticket_jobs[ticket_key]
            return None
    
    # Job not found, clean up mapping
    if ticket_key in ticket_jobs:
        del ticket_jobs[ticket_key]
    return None


def register_ticket_job(ticket_key: str, job_id: str):
    """
    Register a ticket key to job ID mapping for active job tracking.
    Should be called when creating a new job for a ticket.
    """
    ticket_jobs[ticket_key] = job_id
    logger.debug(f"Registered ticket {ticket_key} -> job {job_id}")


def unregister_ticket_job(ticket_key: str):
    """
    Unregister a ticket key from active job tracking.
    Should be called when job completes, fails, or is cancelled.
    """
    if ticket_key in ticket_jobs:
        del ticket_jobs[ticket_key]
        logger.debug(f"Unregistered ticket {ticket_key}")


def get_job_by_ticket_key(ticket_key: str) -> Optional[dict]:
    """
    Get current job status for a ticket key.
    Returns active job if exists, otherwise latest completed/failed job.
    Returns None if no job found.
    """
    # First check for active job
    active_job_id = get_active_job_for_ticket(ticket_key)
    if active_job_id:
        job = jobs[active_job_id]
        return job.dict()
    
    # Search all jobs for latest job with this ticket_key
    matching_jobs = []
    for job_id, job in jobs.items():
        if job.ticket_key == ticket_key or (job.ticket_keys and ticket_key in job.ticket_keys):
            matching_jobs.append(job)
    
    if not matching_jobs:
        return None
    
    # Return most recent job (by started_at)
    latest_job = max(matching_jobs, key=lambda j: j.started_at)
    return latest_job.dict()


def initialize_services():
    """Initialize all clients and services"""
    global jira_client, bitbucket_client, confluence_client, llm_client, generator, config
    
    try:
        config = Config()
        
        # Load authentication configuration
        global auth_config
        auth_config.update({
            "enabled": config.auth.get('enabled', False),
            "username": config.auth.get('username', ''),
            "password_hash": config.auth.get('password_hash', '')
        })
        
        if auth_config["enabled"]:
            logger.info("Authentication is ENABLED")
            if not auth_config["username"] or not auth_config["password_hash"]:
                logger.warning("Authentication enabled but credentials not properly configured")
        else:
            logger.info("Authentication is DISABLED")
        
        # Validate config before initializing clients
        if not config.validate():
            raise ValueError("Configuration validation failed")
        
        jira_client = JiraClient(
            server_url=config.jira['server_url'],
            username=config.jira['username'],
            api_token=config.jira['api_token'],
            prd_custom_field=config.jira.get('prd_custom_field', 'customfield_10000'),
            rfc_custom_field=config.jira.get('rfc_custom_field'),
            test_case_custom_field=config.jira.get('test_case_custom_field'),
            mandays_custom_field=config.jira.get('mandays_custom_field')
        )
        
        bitbucket_client = BitbucketClient(
            workspace=config.bitbucket.get('workspace', ''),
            email=config.bitbucket.get('email', ''),
            api_token=config.bitbucket.get('api_token', ''),
            jira_server_url=config.jira['server_url'],
            jira_credentials={
                'username': config.jira['username'],
                'api_token': config.jira['api_token']
            }
        )
        
        confluence_client = ConfluenceClient(
            server_url=config.confluence.get('server_url', ''),
            username=config.confluence.get('username', ''),
            api_token=config.confluence.get('api_token', '')
        )
        
        llm_client = LLMClient(config.get_llm_config())
        
        generator = DescriptionGenerator(
            jira_client=jira_client,
            bitbucket_client=bitbucket_client,
            confluence_client=confluence_client,
            llm_client=llm_client,
            prompt_template=config.prompts.get('description_template'),
            include_code_analysis=True,
            story_description_max_length=config.processing.get('story_description_max_length', 300),
            story_description_summary_threshold=config.processing.get('story_description_summary_threshold', 500)
        )
        
        logger.info("All services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise

