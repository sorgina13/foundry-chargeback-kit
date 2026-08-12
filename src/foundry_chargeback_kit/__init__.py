"""End-to-end consumer cost tracing for Microsoft Foundry hosted agents behind APIM."""

from .config import Settings, load_settings
from .correlation import mint_request_id, traceparent_for
from .gateway import call_agent
from .showback import Rates, allocate_fixed_cost, variable_cost
from .telemetry_query import (
    TelemetryClient,
    UsageTotals,
    aggregate_usage,
    model_usage_spans,
)

__all__ = [
    "Settings",
    "load_settings",
    "mint_request_id",
    "traceparent_for",
    "call_agent",
    "Rates",
    "allocate_fixed_cost",
    "variable_cost",
    "TelemetryClient",
    "UsageTotals",
    "aggregate_usage",
    "model_usage_spans",
]
