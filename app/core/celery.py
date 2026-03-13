"""
Celery Configuration for Async Job Processing

This module configures Celery to work with Redis as message broker.
Used for async face verification, email sending, and other background tasks.
"""

import os
from celery import Celery
from kombu import Exchange, Queue
import logging

logger = logging.getLogger(__name__)

# ============================================================
# CELERY CONFIGURATION
# ============================================================

# Get Redis configuration from environment or use defaults
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# Build Redis URL
if REDIS_PASSWORD:
    REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
else:
    REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# Initialize Celery app
celery_app = Celery(
    "bappsearch",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

# ============================================================
# CELERY CONFIGURATION DICT
# ============================================================

celery_app.conf.update(
    # Broker settings
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    
    # Task settings
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    result_persistent=True,
    
    # Worker settings
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    task_acks_late=True,
    worker_disable_rate_limits=False,
    
    # Task routing - ensure tasks go to right queues
    task_routes={
        'app.workers.face_verification_worker.process_face_verification': {'queue': 'face_verification'},
        'app.workers.*.send_email_task': {'queue': 'emails'},
    },
    
    # Celery queues definition
    task_queues=(
        Queue(
            'default',
            Exchange('default', type='direct'),
            routing_key='default',
        ),
        Queue(
            'face_verification',
            Exchange('face_verification', type='direct'),
            routing_key='face_verification.#',
            queue_arguments={
                'x-max-priority': 10,
            }
        ),
        Queue(
            'emails',
            Exchange('emails', type='direct'),
            routing_key='emails.#',
        ),
    ),
    
    # Task execution limits
    task_soft_time_limit=600,  # 10 minutes soft limit
    task_time_limit=1800,      # 30 minutes hard limit
    
    # Retry settings
    task_max_retries=3,
    task_default_retry_delay=60,
)

# ============================================================
# LOGGING FOR CELERY
# ============================================================

# Configure Celery logging
celery_log = logging.getLogger('celery')
celery_log.setLevel(logging.INFO)

def on_celery_ready():
    """Called when Celery worker is ready"""
    logger.info("[CELERY] Celery worker started successfully")
    logger.info(f"[CELERY] Broker: {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
    logger.info(f"[CELERY] Task serializer: json")

celery_app.on_after_finalize.connect(on_celery_ready)

# ============================================================
# TASK SIGNALS
# ============================================================

from celery.signals import task_prerun, task_postrun, task_failure

@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, **kwargs):
    """Log when task starts"""
    logger.info(f"[CELERY] Task '{task.name}' (id: {task_id}) started")

@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, result=None, **kwargs):
    """Log when task completes"""
    logger.info(f"[CELERY] Task '{task.name}' (id: {task_id}) completed successfully")

@task_failure.connect
def task_failure_handler(sender=None, task_id=None, exception=None, **kwargs):
    """Log when task fails"""
    logger.error(f"[CELERY] Task failed (id: {task_id}): {str(exception)}")

# ============================================================
# HEALTH CHECK
# ============================================================

async def check_celery_health():
    """
    Check if Celery/Redis is available
    
    Returns:
        dict: {"status": "healthy" | "unhealthy", "details": str}
    """
    try:
        # Try to get Redis info
        inspect_result = celery_app.control.inspect().active()
        if inspect_result is not None:
            return {
                "status": "healthy",
                "details": "Celery/Redis connection active"
            }
        else:
            return {
                "status": "unavailable",
                "details": "No active Celery workers"
            }
    except Exception as e:
        logger.warning(f"[CELERY] Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "details": str(e)
        }
