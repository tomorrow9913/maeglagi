"""Shared process logging and Sentry setup for HTTP and job workers."""

import sentry_sdk

from app.core.config import Settings
from app.core.logging import configure_logging


def configure_observability(settings: Settings, *, web: bool = False) -> None:
    configure_logging(settings.log_level)
    dsn = settings.sentry_dsn.get_secret_value()
    if not dsn:
        return
    integrations = []
    if web:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        integrations = [FastApiIntegration(), StarletteIntegration()]
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.app_env,
        release=settings.app_version,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        integrations=integrations,
        send_default_pii=False,
    )
