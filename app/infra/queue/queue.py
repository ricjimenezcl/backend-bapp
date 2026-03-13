# app/infra/queue/queue.py
"""
Job Queue Manager - Enqueue, process, and manage background jobs using Redis
Supports priority queues, retries, and job status tracking
"""

import logging
from typing import List, Optional, Dict, Any
from app.infra.redis.client import redis_client
from app.infra.queue.job import Job, JobStatus, JobType, JobBuilder

logger = logging.getLogger(__name__)


class JobQueue:
    """
    Job queue using Redis sorted sets for priority management.
    Each job type has its own queue.
    """
    
    QUEUE_KEY_TEMPLATE = "queue:{job_type}"
    JOB_KEY_TEMPLATE = "job:{job_id}"
    JOB_STATUS_KEY = "job:status:{job_id}"
    QUEUE_STATS_KEY = "queue:stats"
    
    @staticmethod
    def _get_queue_key(job_type: JobType) -> str:
        """Get Redis key for job type queue"""
        return JobQueue.QUEUE_KEY_TEMPLATE.format(job_type=job_type.value)
    
    @staticmethod
    def _get_job_key(job_id: str) -> str:
        """Get Redis key for job data"""
        return JobQueue.JOB_KEY_TEMPLATE.format(job_id=job_id)
    
    @staticmethod
    def _get_status_key(job_id: str) -> str:
        """Get Redis key for job status"""
        return JobQueue.JOB_STATUS_KEY.format(job_id=job_id)
    
    async def enqueue(self, job: Job) -> bool:
        """
        Add job to queue
        
        Args:
            job: Job instance
            
        Returns:
            True if enqueued successfully
        """
        try:
            queue_key = self._get_queue_key(job.job_type)
            job_key = self._get_job_key(job.job_id)
            
            # Store job data
            await redis_client.set(job_key, job.to_json(), ex=86400)  # 24h TTL
            
            # Add to priority queue (use negative priority for higher = more urgent)
            score = -job.priority * 1000000 + job.created_at.timestamp()
            await redis_client.zadd(queue_key, {job.job_id: score})
            
            # Update stats
            await self._update_stats(job.job_type, "enqueued")
            
            logger.info(f"📝 Job enqueued: {job.job_id} ({job.job_type.value})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Enqueue failed: {str(e)}")
            return False
    
    async def dequeue(self, job_type: JobType) -> Optional[Job]:
        """
        Get next job from queue
        
        Args:
            job_type: Job type to dequeue from
            
        Returns:
            Next Job or None if queue is empty
        """
        try:
            queue_key = self._get_queue_key(job_type)
            
            # Get highest priority job (smallest score)
            job_ids = await redis_client.zrange(queue_key, 0, 0)
            
            if not job_ids:
                return None
            
            job_id = job_ids[0]
            job_key = self._get_job_key(job_id)
            
            # Get job data
            job_json = await redis_client.get(job_key)
            if not job_json:
                # Remove orphaned queue entry
                await redis_client.zadd(queue_key, {job_id: 0})
                return None
            
            job = Job.from_json(job_json)
            
            # Mark as processing
            job.mark_processing()
            await redis_client.set(job_key, job.to_json(), ex=86400)
            
            # Remove from queue
            await redis_client.zadd(queue_key, {job_id: 0})  # Move to processed
            
            logger.info(f"🎯 Job dequeued: {job.job_id}")
            return job
            
        except Exception as e:
            logger.error(f"❌ Dequeue failed: {str(e)}")
            return None
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID"""
        try:
            job_key = self._get_job_key(job_id)
            job_json = await redis_client.get(job_key)
            
            if not job_json:
                return None
            
            return Job.from_json(job_json)
            
        except Exception as e:
            logger.error(f"❌ Get job failed: {str(e)}")
            return None
    
    async def update_job(self, job: Job) -> bool:
        """Update job status"""
        try:
            job_key = self._get_job_key(job.job_id)
            await redis_client.set(job_key, job.to_json(), ex=86400)
            
            # Update stats based on status
            if job.status == JobStatus.COMPLETED:
                await self._update_stats(job.job_type, "completed")
            elif job.status == JobStatus.FAILED:
                await self._update_stats(job.job_type, "failed")
            
            logger.info(f"✏️ Job updated: {job.job_id} -> {job.status.value}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Update job failed: {str(e)}")
            return False
    
    async def requeue(self, job: Job) -> bool:
        """Requeue failed job for retry"""
        try:
            if not job.can_retry():
                logger.warning(f"⚠️ Job {job.job_id} cannot retry (max retries exceeded)")
                return False
            
            job.mark_retry()
            return await self.enqueue(job)
            
        except Exception as e:
            logger.error(f"❌ Requeue failed: {str(e)}")
            return False
    
    async def remove_job(self, job_id: str) -> bool:
        """Remove job from queue"""
        try:
            job = await self.get_job(job_id)
            if job:
                queue_key = self._get_queue_key(job.job_type)
                await redis_client.zadd(queue_key, {job_id: 0})
            
            job_key = self._get_job_key(job_id)
            await redis_client.delete(job_key)
            
            logger.info(f"🗑️ Job removed: {job_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Remove job failed: {str(e)}")
            return False
    
    async def get_queue_size(self, job_type: JobType) -> int:
        """Get number of jobs in queue"""
        try:
            queue_key = self._get_queue_key(job_type)
            return await redis_client.zcard(queue_key)
        except Exception as e:
            logger.error(f"❌ Get queue size failed: {str(e)}")
            return 0
    
    async def get_queue_jobs(self, job_type: JobType, limit: int = 10) -> List[Job]:
        """Get pending jobs from queue"""
        try:
            queue_key = self._get_queue_key(job_type)
            job_ids = await redis_client.zrange(queue_key, 0, limit - 1)
            
            jobs = []
            for job_id in job_ids:
                job = await self.get_job(job_id)
                if job:
                    jobs.append(job)
            
            return jobs
            
        except Exception as e:
            logger.error(f"❌ Get queue jobs failed: {str(e)}")
            return []
    
    async def _update_stats(self, job_type: JobType, action: str) -> None:
        """Update queue statistics"""
        try:
            stats_key = f"{self.QUEUE_STATS_KEY}:{job_type.value}"
            await redis_client.hset(stats_key, {action: 1})
        except Exception as e:
            logger.error(f"❌ Update stats failed: {str(e)}")
    
    async def get_stats(self, job_type: JobType) -> Dict[str, int]:
        """Get queue statistics"""
        try:
            stats_key = f"{self.QUEUE_STATS_KEY}:{job_type.value}"
            return await redis_client.hgetall(stats_key)
        except Exception as e:
            logger.error(f"❌ Get stats failed: {str(e)}")
            return {}
    
    async def clear_queue(self, job_type: JobType) -> bool:
        """Clear all jobs from queue (use with caution)"""
        try:
            queue_key = self._get_queue_key(job_type)
            job_ids = await redis_client.zrange(queue_key, 0, -1)
            
            for job_id in job_ids:
                await self.remove_job(job_id)
            
            logger.warning(f"⚠️ Queue cleared: {job_type.value}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Clear queue failed: {str(e)}")
            return False


# Singleton instance
job_queue = JobQueue()
