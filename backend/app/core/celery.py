from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "maeglagi",
    broker=settings.celery_broker_url.get_secret_value(),
    include=["app.modules.ingestion.infrastructure.tasks"],
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    timezone="UTC",
)
