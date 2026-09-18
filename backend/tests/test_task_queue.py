from app.core.celery import celery_app
from app.modules.ingestion.infrastructure.tasks import process_source


def test_celery_uses_late_ack_and_single_prefetch_for_durable_long_jobs() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_ingestion_task_has_bounded_retries() -> None:
    assert process_source.max_retries == 3
    assert process_source.name == "ingestion.process_source"
