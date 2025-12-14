#!/usr/bin/env python3
"""
ARQ Worker Process
Standalone worker process for processing background jobs
Run this separately from the API server: python run_worker.py
"""
import asyncio
import os
import sys
from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import Worker
from api.workers import (
    WorkerSettings,
    process_batch_tickets_worker,
    process_single_ticket_worker,
    process_story_generation_worker,
    process_task_generation_worker,
    process_test_generation_worker,
    process_story_coverage_worker,
    process_prd_story_sync_worker,
    process_bulk_story_update_worker,
    process_bulk_task_creation_worker,
    process_epic_creation_worker,
    process_story_creation_worker,
    process_task_creation_worker,
    process_sprint_planning_worker,
    process_timeline_planning_worker
)
from src.config import Config
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    """Start ARQ worker"""
    try:
        # Load configuration
        config = Config()
        # Access redis config from _config dict since Config class may not have redis property
        redis_config = config._config.get('redis', {}) if hasattr(config, '_config') else {}
        
        # Set Redis settings for worker
        WorkerSettings.redis_settings = RedisSettings(
            host=redis_config.get('host', os.getenv('REDIS_HOST', 'localhost')),
            port=int(redis_config.get('port', os.getenv('REDIS_PORT', 6379))),
            password=redis_config.get('password') or os.getenv('REDIS_PASSWORD') or None,
            database=int(redis_config.get('database', os.getenv('REDIS_DB', 0)))
        )
        
        logger.info(f"Starting ARQ worker with Redis: {WorkerSettings.redis_settings.host}:{WorkerSettings.redis_settings.port}")
        
        # Create worker with all worker functions
        worker = Worker(
            functions=[
                process_batch_tickets_worker,
                process_single_ticket_worker,
                process_story_generation_worker,
                process_task_generation_worker,
                process_test_generation_worker,
                process_story_coverage_worker,
                process_prd_story_sync_worker,
                process_bulk_story_update_worker,
                process_bulk_task_creation_worker,
                process_epic_creation_worker,
                process_story_creation_worker,
                process_task_creation_worker,
                process_sprint_planning_worker,
                process_timeline_planning_worker
            ],
            redis_settings=WorkerSettings.redis_settings,
            max_jobs=WorkerSettings.max_jobs,
            job_timeout=WorkerSettings.job_timeout,
            keep_result=3600  # Keep results for 1 hour
        )
        
        logger.info("ARQ worker started. Waiting for jobs...")
        await worker.async_run()
        
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())

