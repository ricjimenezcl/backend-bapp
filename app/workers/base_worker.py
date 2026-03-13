# app/workers/base_worker.py
"""
Base Worker - Abstract worker for processing background jobs
Implements retry logic, error handling, and job tracking
"""

import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from app.infra.queue.job import Job, JobStatus, JobType, JobBuilder
from app.infra.queue.queue import job_queue

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """Abstract base class for background workers"""
    
    def __init__(self, job_types: list = None):
        self.job_types = job_types or []
        self.is_running = False
    
    @abstractmethod
    async def handle_job(self, job: Job) -> bool:
        """
        Process a single job
        
        Args:
            job: Job to process
            
        Returns:
            True if successful, False if failed
        """
        pass
    
    async def start(self) -> None:
        """Start worker - process jobs indefinitely"""
        self.is_running = True
        logger.info(f"🚀 {self.__class__.__name__} started")
        
        try:
            while self.is_running:
                await self._process_jobs()
                await asyncio.sleep(1)  # Check for new jobs every second
        except KeyboardInterrupt:
            logger.info(f"⏹️ {self.__class__.__name__} interrupted")
        except Exception as e:
            logger.error(f"❌ {self.__class__.__name__} error: {str(e)}")
            raise
        finally:
            await self.cleanup()
    
    async def stop(self) -> None:
        """Stop worker"""
        self.is_running = False
        logger.info(f"⏹️ {self.__class__.__name__} stopped")
    
    async def _process_jobs(self) -> None:
        """Process pending jobs for all job types"""
        for job_type in self.job_types:
            try:
                job = await job_queue.dequeue(job_type)
                
                if job:
                    success = await self._execute_job(job)
                    
                    if success:
                        job.mark_completed()
                    else:
                        job.mark_failed("Execution failed")
                        if job.can_retry():
                            await job_queue.requeue(job)
                    
                    await job_queue.update_job(job)
            
            except Exception as e:
                logger.error(f"Error processing {job_type.value}: {str(e)}")
    
    async def _execute_job(self, job: Job) -> bool:
        """Execute job with timeout handling"""
        try:
            # Check if job has expired
            if job.is_expired():
                logger.warning(f"⏱️ Job {job.job_id} expired")
                return False
            
            # Execute handler with timeout
            try:
                result = await asyncio.wait_for(
                    self.handle_job(job),
                    timeout=job.timeout_seconds
                )
                return result
            
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Job {job.job_id} timeout")
                return False
        
        except Exception as e:
            logger.error(f"Error executing job {job.job_id}: {str(e)}")
            return False
    
    async def cleanup(self) -> None:
        """Cleanup resources (override in subclasses)"""
        pass
    
    @staticmethod
    async def enqueue_job(job_type: JobType, payload: Dict[str, Any],
                         priority: int = 5, max_retries: int = 3,
                         timeout_seconds: int = 300) -> Optional[str]:
        """
        Helper to enqueue a job
        
        Returns:
            Job ID if successful, None otherwise
        """
        try:
            job = JobBuilder(
                job_type=job_type,
                payload=payload
            ).with_priority(priority).with_retries(max_retries).with_timeout(timeout_seconds).build()
            
            success = await job_queue.enqueue(job)
            return job.job_id if success else None
        
        except Exception as e:
            logger.error(f"Error enqueueing job: {str(e)}")
            return None
