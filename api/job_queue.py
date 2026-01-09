"""
Job Queue Management
Redis connection pool management for ARQ background jobs
"""
from arq import create_pool, ArqRedis
from arq.connections import RedisSettings
from typing import Optional
import os
import logging

logger = logging.getLogger(__name__)

# Global Redis connection pool
redis_pool: Optional[ArqRedis] = None


async def get_redis_pool() -> ArqRedis:
    """Get or create Redis connection pool"""
    global redis_pool
    if redis_pool is None:
        from .dependencies import get_config
        
        config = get_config()
        # Access redis config from _config dict since Config class may not have redis property
        redis_config = config._config.get('redis', {}) if hasattr(config, '_config') else {}
        
        redis_settings = RedisSettings(
            host=redis_config.get('host', os.getenv('REDIS_HOST', 'localhost')),
            port=int(redis_config.get('port', os.getenv('REDIS_PORT', 6379))),
            password=redis_config.get('password') or os.getenv('REDIS_PASSWORD') or None,
            database=int(redis_config.get('database', os.getenv('REDIS_DB', 0)))
        )
        
        redis_pool = await create_pool(redis_settings)
        logger.info(f"Redis connection pool initialized: {redis_settings.host}:{redis_settings.port}")
    
    return redis_pool


async def initialize_redis():
    """Initialize Redis connection pool on startup"""
    try:
        await get_redis_pool()
        logger.info("Redis connection pool initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Redis connection pool: {e}")
        raise


async def close_redis():
    """Close Redis connection pool on shutdown"""
    global redis_pool
    if redis_pool:
        await redis_pool.close()
        redis_pool = None
        logger.info("Redis connection pool closed")


# Job cancellation constants and functions
CANCEL_KEY_PREFIX = "job:cancel:"
CANCEL_TTL = 86400  # 24 hours - cancellation flags expire after this time


async def request_job_cancellation(job_id: str) -> bool:
    """
    Set cancellation flag in Redis for a job.
    This flag can be checked by workers running in separate processes.
    
    Args:
        job_id: The ID of the job to cancel
        
    Returns:
        True if the cancellation flag was set successfully
    """
    try:
        pool = await get_redis_pool()
        key = f"{CANCEL_KEY_PREFIX}{job_id}"
        await pool.set(key, "1", ex=CANCEL_TTL)
        logger.info(f"Cancellation flag set for job {job_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to set cancellation flag for job {job_id}: {e}")
        return False


async def is_job_cancelled(job_id: str) -> bool:
    """
    Check if cancellation was requested for a job.
    Workers should call this periodically to check if they should stop.
    
    Args:
        job_id: The ID of the job to check
        
    Returns:
        True if the job should be cancelled
    """
    try:
        pool = await get_redis_pool()
        key = f"{CANCEL_KEY_PREFIX}{job_id}"
        return await pool.exists(key) > 0
    except Exception as e:
        logger.warning(f"Failed to check cancellation flag for job {job_id}: {e}")
        return False


async def clear_cancellation_flag(job_id: str):
    """
    Clean up cancellation flag after job completes or is cancelled.
    
    Args:
        job_id: The ID of the job to clean up
    """
    try:
        pool = await get_redis_pool()
        key = f"{CANCEL_KEY_PREFIX}{job_id}"
        await pool.delete(key)
        logger.debug(f"Cancellation flag cleared for job {job_id}")
    except Exception as e:
        logger.warning(f"Failed to clear cancellation flag for job {job_id}: {e}")

