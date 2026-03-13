# app/workers/chat_worker.py
"""
Chat Worker - Processes chat messages and related notifications
Handles message processing, indexing, and notifications
"""

import logging
from typing import Optional
from app.infra.queue.job import Job, JobType
from app.workers.base_worker import BaseWorker

logger = logging.getLogger(__name__)


class ChatWorker(BaseWorker):
    """Worker for chat message processing"""
    
    def __init__(self):
        super().__init__(job_types=[
            JobType.PROCESS_MESSAGE,
            JobType.NOTIFY_NEW_MESSAGE,
        ])
    
    async def handle_job(self, job: Job) -> bool:
        """Process chat job"""
        
        try:
            if job.job_type == JobType.PROCESS_MESSAGE:
                return await self._process_message(job)
            
            elif job.job_type == JobType.NOTIFY_NEW_MESSAGE:
                return await self._notify_message(job)
            
            else:
                logger.warning(f"Unknown job type: {job.job_type}")
                return False
        
        except Exception as e:
            logger.error(f"❌ Chat worker error: {str(e)}")
            return False
    
    async def _process_message(self, job: Job) -> bool:
        """Process incoming message"""
        try:
            payload = job.payload
            message_id = payload.get("message_id")
            conversation_id = payload.get("conversation_id")
            sender_id = payload.get("sender_id")
            content = payload.get("content")
            
            logger.info(f"💬 Processing message {message_id}")
            
            # TODO: Implement message processing
            # - Validate content (no profanity, spam detection)
            # - Generate embeddings for search (if using vector DB)
            # - Update conversation last_message
            # - Mark conversation as unread for other participants
            # - Trigger notifications for other participants
            
            logger.info(f"✅ Message processed {message_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Message processing failed: {str(e)}")
            return False
    
    async def _notify_message(self, job: Job) -> bool:
        """Send notification for new message"""
        try:
            payload = job.payload
            message_id = payload.get("message_id")
            conversation_id = payload.get("conversation_id")
            sender_id = payload.get("sender_id")
            recipient_ids = payload.get("recipient_ids", [])
            
            logger.info(f"🔔 Notifying {len(recipient_ids)} recipients about message")
            
            # TODO: Send notifications to all recipients
            # for recipient_id in recipient_ids:
            #     await enqueue_notification(
            #         user_id=recipient_id,
            #         title="Nuevo mensaje",
            #         body=f"Tienes un nuevo mensaje",
            #         action_url=f"/chat/{conversation_id}"
            #     )
            
            logger.info(f"✅ Notifications sent for message {message_id}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Message notification failed: {str(e)}")
            return False


# Worker instance
chat_worker = ChatWorker()
