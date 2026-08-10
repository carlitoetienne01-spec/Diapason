"""External-framework subprocess backends (Hermes Agent, OpenClaw)."""

from diapason.evals.backends.external.hermes_agent import HermesBackend
from diapason.evals.backends.external.openclaw import OpenClawBackend

__all__ = ["HermesBackend", "OpenClawBackend"]
