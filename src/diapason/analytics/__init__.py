"""External anonymous usage analytics.

Sends anonymized events to PostHog so the Diapason team can measure
setup success, retention, feature usage, and churn — without ever
collecting chat content, prompts, file paths, emails, IPs, or hardware
identifiers.

Distinct from :mod:`diapason.telemetry`, which stores local FLOPs and
energy metrics in a SQLite DB and never leaves the machine.

Disable: set ``[analytics] enabled = false`` in ``~/.diapason/config.toml``.
"""

from diapason.analytics.aggregator import SessionAggregator
from diapason.analytics.bridge import EventBridge
from diapason.analytics.client import AnalyticsClient
from diapason.analytics.identity import (
    get_or_create_anon_id,
    is_analytics_enabled,
    reset_anon_id,
)
from diapason.analytics.redaction import hash_id, redact

__all__ = [
    "AnalyticsClient",
    "EventBridge",
    "SessionAggregator",
    "get_or_create_anon_id",
    "is_analytics_enabled",
    "reset_anon_id",
    "redact",
    "hash_id",
]
