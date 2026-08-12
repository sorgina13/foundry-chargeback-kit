"""Invoke the hosted agent through APIM with chargeback correlation headers."""
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import Settings
from .correlation import traceparent_for


@dataclass(frozen=True)
class GatewayResult:
    status: int
    latency_ms: int
    request_id: str
    cost_centre: str
    echoed_request_id: str | None
    response_id: str | None
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def correlation_echoed(self) -> bool:
        return self.echoed_request_id == self.request_id


def call_agent(
    settings: Settings,
    prompt: str,
    request_id: str,
    cost_centre: str | None = None,
    timeout: int = 120,
) -> GatewayResult:
    settings.require("apim_base", "agent_id", "agent_route")
    cost_centre = cost_centre or settings.cost_centre

    headers = {
        "Content-Type": "application/json",
        "x-request-id": request_id,
        "x-cost-centre": cost_centre,
        "traceparent": traceparent_for(request_id),
    }
    if settings.apim_subscription_key:
        # This API declares subscriptionKeyParameterNames.header = "api-key",
        # not the APIM default of Ocp-Apim-Subscription-Key.
        headers["api-key"] = settings.apim_subscription_key

    body = {
        "input": prompt,
        "metadata": {"requestId": request_id, "costCentre": cost_centre},
    }

    started = time.perf_counter()
    response = requests.post(
        settings.responses_url(), headers=headers, json=body, timeout=timeout
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    try:
        payload = response.json()
    except ValueError:
        payload = {"_raw": response.text[:2000]}

    response_headers = {key.lower(): value for key, value in response.headers.items()}
    response_id = None
    if isinstance(payload, dict):
        response_id = payload.get("response_id") or payload.get("id")

    return GatewayResult(
        status=response.status_code,
        latency_ms=latency_ms,
        request_id=request_id,
        cost_centre=cost_centre,
        echoed_request_id=response_headers.get("x-request-id"),
        response_id=response_id,
        body=payload,
    )
