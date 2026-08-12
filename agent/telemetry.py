import logging
import threading
from typing import Any

from azure.ai.agentserver.core import configure_observability
from opentelemetry import baggage, context, trace
from opentelemetry.sdk.trace import SpanProcessor


logger = logging.getLogger(__name__)

_BAGGAGE_ATTRIBUTES = {"x_request_id": ("request.id", "chargeback.request.id")}
_MAX_ATTRIBUTE_LENGTH = 256
_processor_lock = threading.Lock()
_processor_registered = False


class ChargebackSpanProcessor(SpanProcessor):
    """Promote trusted request baggage onto every exported span."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        active_context = parent_context if parent_context is not None else context.get_current()
        for baggage_key, attribute_names in _BAGGAGE_ATTRIBUTES.items():
            value = baggage.get_baggage(baggage_key, context=active_context)
            if value is None:
                continue
            safe_value = str(value)[:_MAX_ATTRIBUTE_LENGTH]
            for attribute_name in attribute_names:
                span.set_attribute(attribute_name, safe_value)

    def on_end(self, span: Any) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def configure_chargeback_observability(
    *,
    connection_string: str | None = None,
    log_level: str | None = None,
    enable_sensitive_data: bool = False,
) -> None:
    """Configure Agent Server export and register chargeback enrichment once."""
    configure_observability(
        connection_string=connection_string,
        log_level=log_level,
        enable_sensitive_data=enable_sensitive_data,
    )

    global _processor_registered
    with _processor_lock:
        if _processor_registered:
            return
        provider = trace.get_tracer_provider()
        add_span_processor = getattr(provider, "add_span_processor", None)
        if not callable(add_span_processor):
            logger.warning(
                "OpenTelemetry SDK provider is unavailable; chargeback span enrichment is disabled."
            )
            return
        add_span_processor(ChargebackSpanProcessor())
        _processor_registered = True
