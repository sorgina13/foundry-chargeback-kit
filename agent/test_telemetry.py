import unittest

from opentelemetry import baggage, context

from telemetry import ChargebackSpanProcessor


class RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, str] = {}

    def set_attribute(self, name: str, value: str) -> None:
        self.attributes[name] = value


class ChargebackSpanProcessorTests(unittest.TestCase):
    def test_promotes_chargeback_baggage_to_span_attributes(self) -> None:
        active_context = context.Context()
        active_context = baggage.set_baggage("x_request_id", "req-123", context=active_context)
        span = RecordingSpan()

        ChargebackSpanProcessor().on_start(span, active_context)

        self.assertEqual(span.attributes["request.id"], "req-123")
        self.assertEqual(span.attributes["chargeback.request.id"], "req-123")

    def test_ignores_missing_baggage(self) -> None:
        span = RecordingSpan()

        ChargebackSpanProcessor().on_start(span, context.Context())

        self.assertEqual(span.attributes, {})

    def test_truncates_oversized_baggage(self) -> None:
        active_context = baggage.set_baggage("x_request_id", "a" * 500, context=context.Context())
        span = RecordingSpan()

        ChargebackSpanProcessor().on_start(span, active_context)

        self.assertEqual(len(span.attributes["chargeback.request.id"]), 256)


if __name__ == "__main__":
    unittest.main()
