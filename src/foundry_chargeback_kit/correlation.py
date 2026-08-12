"""Request identifiers shared by the APIM ledger and Foundry telemetry.

Agent Server gives the active W3C trace ID precedence over a plain x-request-id
header, so the same lowercase 32-hex value is used for both. That keeps the
gateway ledger key, Application Insights operation_Id and
chargeback.request.id directly joinable.
"""
import re
import uuid

_TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def mint_request_id() -> str:
    """Mint a lowercase 32-hex identifier usable as both request ID and trace ID."""
    return uuid.uuid4().hex


def is_valid_request_id(request_id: str) -> bool:
    return bool(_TRACE_ID_RE.match(request_id)) and request_id != "0" * 32


def traceparent_for(request_id: str) -> str:
    """Build a W3C traceparent whose trace ID is the business request ID."""
    if not is_valid_request_id(request_id):
        raise ValueError("request_id must be a lowercase, nonzero 32-hex W3C trace ID")
    parent_id = uuid.uuid4().hex[:16]
    return f"00-{request_id}-{parent_id}-01"
