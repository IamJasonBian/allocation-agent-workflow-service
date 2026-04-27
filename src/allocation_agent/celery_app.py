from celery import Celery
from kombu import Queue

from .config import settings

app = Celery(
    "allocation_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "allocation_agent.tasks.select",
        "allocation_agent.tasks.apply",
        "allocation_agent.tasks.feedback",
    ],
)

app.conf.update(
    task_queues=(
        Queue("select"),
        Queue("apply"),
        Queue("feedback"),
    ),
    task_routes={
        "allocation_agent.tasks.select.*": {"queue": "select"},
        "allocation_agent.tasks.apply.*": {"queue": "apply"},
        "allocation_agent.tasks.feedback.*": {"queue": "feedback"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_send_task_events=True,
    task_send_sent_event=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "reclaim-expired-leases": {
            "task": "allocation_agent.tasks.select.reclaim_leases",
            "schedule": 300.0,   # every 5 min
            "options": {"queue": "select"},
        },
    },
)
