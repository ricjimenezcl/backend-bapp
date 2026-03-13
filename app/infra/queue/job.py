# app/infra/queue/job.py
"""
Job Queue System - Using Redis for background task management
Supports retries, timeouts, and status tracking
"""

from enum import Enum
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import json
import uuid
import logging

logger = logging.getLogger(__name__)


class JobStatus(str, Enum):
    """Job execution status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Job types for background processing"""
    # Notifications
    SEND_EMAIL = "send_email"
    SEND_SMS = "send_sms"
    SEND_PUSH_NOTIFICATION = "send_push_notification"
    
    # Chat
    PROCESS_MESSAGE = "process_message"
    NOTIFY_NEW_MESSAGE = "notify_new_message"
    
    # Bookings
    SEND_BOOKING_REMINDER = "send_booking_reminder"
    PROCESS_BOOKING_COMPLETION = "process_booking_completion"
    
    # Reviews
    SEND_REVIEW_REQUEST = "send_review_request"
    
    # General
    CLEANUP = "cleanup"
    HEALTH_CHECK = "health_check"


@dataclass
class Job:
    """Represents a background job"""
    job_id: str
    job_type: JobType
    payload: Dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    priority: int = 5  # 1-10, higher = more urgent
    retries: int = 0
    max_retries: int = 3
    timeout_seconds: int = 300
    created_at: datetime = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    correlation_id: Optional[str] = None  # For tracing
    
    def __post_init__(self):
        if self.job_id is None:
            self.job_id = str(uuid.uuid4())
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary"""
        data = asdict(self)
        data['job_type'] = self.job_type.value
        data['status'] = self.status.value
        data['created_at'] = self.created_at.isoformat() if self.created_at else None
        data['started_at'] = self.started_at.isoformat() if self.started_at else None
        data['completed_at'] = self.completed_at.isoformat() if self.completed_at else None
        return data
    
    def to_json(self) -> str:
        """Convert job to JSON"""
        return json.dumps(self.to_dict())
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Job':
        """Create job from dictionary"""
        data['job_type'] = JobType(data['job_type'])
        data['status'] = JobStatus(data['status'])
        
        # Parse datetimes
        for date_field in ['created_at', 'started_at', 'completed_at']:
            if data.get(date_field):
                data[date_field] = datetime.fromisoformat(data[date_field])
        
        return Job(**data)
    
    @staticmethod
    def from_json(json_str: str) -> 'Job':
        """Create job from JSON"""
        return Job.from_dict(json.loads(json_str))
    
    def mark_processing(self) -> None:
        """Mark job as processing"""
        self.status = JobStatus.PROCESSING
        self.started_at = datetime.utcnow()
    
    def mark_completed(self) -> None:
        """Mark job as completed"""
        self.status = JobStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.error_message = None
    
    def mark_failed(self, error: str) -> None:
        """Mark job as failed"""
        self.status = JobStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error_message = error
    
    def mark_retry(self) -> None:
        """Mark job for retry"""
        self.status = JobStatus.RETRY
        self.retries += 1
        self.started_at = None
    
    def can_retry(self) -> bool:
        """Check if job can be retried"""
        return self.retries < self.max_retries and self.status == JobStatus.FAILED
    
    def is_expired(self) -> bool:
        """Check if job has timed out"""
        if not self.started_at:
            return False
        elapsed = (datetime.utcnow() - self.started_at).total_seconds()
        return elapsed > self.timeout_seconds


@dataclass
class JobBuilder:
    """Builder pattern for creating jobs"""
    job_type: JobType
    payload: Dict[str, Any]
    job_id: str = None
    priority: int = 5
    max_retries: int = 3
    timeout_seconds: int = 300
    correlation_id: str = None
    
    def build(self) -> Job:
        """Build job instance"""
        return Job(
            job_id=self.job_id or str(uuid.uuid4()),
            job_type=self.job_type,
            payload=self.payload,
            priority=self.priority,
            max_retries=self.max_retries,
            timeout_seconds=self.timeout_seconds,
            correlation_id=self.correlation_id,
        )
    
    def with_priority(self, priority: int) -> 'JobBuilder':
        """Set job priority"""
        self.priority = max(1, min(10, priority))
        return self
    
    def with_retries(self, max_retries: int) -> 'JobBuilder':
        """Set max retries"""
        self.max_retries = max(0, max_retries)
        return self
    
    def with_timeout(self, timeout_seconds: int) -> 'JobBuilder':
        """Set job timeout"""
        self.timeout_seconds = max(30, timeout_seconds)
        return self
    
    def with_correlation_id(self, correlation_id: str) -> 'JobBuilder':
        """Set correlation ID for tracing"""
        self.correlation_id = correlation_id
        return self
