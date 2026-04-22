"""Celery worker entry: `celery -A allocation_agent.worker worker -Q select,apply,feedback`."""

from .celery_app import app

__all__ = ["app"]
