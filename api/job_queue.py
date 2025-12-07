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

