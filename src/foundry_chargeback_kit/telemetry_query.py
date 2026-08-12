"""Read chargeback spans from Application Insights with the signed-in Azure identity."""
import time
from dataclasses import dataclass

import requests
from azure.identity import DefaultAzureCredential

from .config import Settings

_QUERY_SCOPE = "https://api.applicationinsights.io/.default"
_USAGE_FIELDS = ("inputTokens", "outputTokens", "cachedTokens", "reasoningTokens")


@dataclass(frozen=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    model_spans: int = 0
    models: tuple[str, ...] = ()

    @property
    def measured(self) -> bool:
        return self.model_spans > 0


def kusto_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class TelemetryClient:
    def __init__(self, settings: Settings, credential: object | None = None) -> None:
        settings.require("app_insights_app_id")
        self._settings = settings
        self._credential = credential or DefaultAzureCredential()
        self._url = (
            f"https://api.applicationinsights.io/v1/apps/"
            f"{settings.app_insights_app_id}/query"
        )

    def query(self, kql: str) -> list[dict]:
        token = self._credential.get_token(_QUERY_SCOPE).token
        response = requests.get(
            self._url,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "query": kql,
                "timespan": f"PT{self._settings.telemetry_lookback_hours}H",
            },
            timeout=60,
        )
        if not response.ok:
            hint = ""
            if response.status_code == 404:
                hint = (
                    " APPLICATIONINSIGHTS_APP_ID must be the component's Application ID"
                    " from API Access, not its Azure resource name, instrumentation key"
                    " or connection string."
                )
            raise RuntimeError(
                f"Application Insights query failed ({response.status_code}): "
                f"{response.text[:1000]}{hint}"
            )

        tables = response.json().get("tables", [])
        if not tables:
            return []
        columns = [column["name"] for column in tables[0]["columns"]]
        return [dict(zip(columns, row)) for row in tables[0]["rows"]]

    def spans_for_request(self, request_id: str) -> list[dict]:
        return _normalise(self.query(chargeback_span_query(request_id, self._settings)))

    def spans_for_response(self, response_id: str) -> list[dict]:
        return _normalise(self.query(response_span_query(response_id, self._settings)))

    def await_model_usage(self, request_id: str) -> list[dict]:
        """Poll until usage-bearing model spans arrive; ingestion is asynchronous."""
        deadline = time.monotonic() + self._settings.telemetry_timeout_seconds
        spans: list[dict] = []
        while True:
            spans = self.spans_for_request(request_id)
            if model_usage_spans(spans):
                return spans
            if time.monotonic() >= deadline:
                return spans
            time.sleep(self._settings.telemetry_poll_seconds)


def chargeback_span_query(request_id: str, settings: Settings) -> str:
    return f"""
union withsource=telemetryTable isfuzzy=true requests, dependencies
| where timestamp > ago({settings.telemetry_lookback_hours}h)
| extend requestId = coalesce(
    tostring(customDimensions["chargeback.request.id"]),
    tostring(customDimensions["request.id"]))
| where requestId == {kusto_string(request_id)}
{_PROJECTION}
"""


def response_span_query(response_id: str, settings: Settings) -> str:
    """Diagnostic path: find the trace by Foundry response ID when the request ID is absent."""
    return f"""
let matchedOperations = union isfuzzy=true requests, dependencies
| where timestamp > ago({settings.telemetry_lookback_hours}h)
| where tostring(customDimensions["azure.ai.agentserver.response_id"]) == {kusto_string(response_id)}
| distinct operation_Id;
union withsource=telemetryTable isfuzzy=true requests, dependencies
| where timestamp > ago({settings.telemetry_lookback_hours}h)
| where operation_Id in (matchedOperations)
| extend requestId = coalesce(
    tostring(customDimensions["chargeback.request.id"]),
    tostring(customDimensions["request.id"]))
{_PROJECTION}
"""


_PROJECTION = """
| extend inputTokens = tolong(customDimensions["gen_ai.usage.input_tokens"]),
         outputTokens = tolong(customDimensions["gen_ai.usage.output_tokens"]),
         cachedTokens = tolong(customDimensions["gen_ai.usage.cache_read.input_tokens"]),
         reasoningTokens = tolong(customDimensions["gen_ai.usage.reasoning.output_tokens"]),
         operationName = tostring(customDimensions["gen_ai.operation.name"]),
         requestModel = tostring(customDimensions["gen_ai.request.model"]),
         responseModel = tostring(customDimensions["gen_ai.response.model"]),
         agentResponseId = tostring(customDimensions["azure.ai.agentserver.response_id"])
| project timestamp, telemetryTable, name, operation_Id, id, operation_ParentId,
          success, resultCode, duration, requestId, agentResponseId, operationName,
          inputTokens, outputTokens, cachedTokens, reasoningTokens,
          requestModel, responseModel
| order by timestamp asc
"""


def _normalise(rows: list[dict]) -> list[dict]:
    for row in rows:
        for field in _USAGE_FIELDS:
            try:
                row[field] = int(row.get(field) or 0)
            except (TypeError, ValueError):
                row[field] = 0
    return rows


def model_usage_spans(spans: list[dict]) -> list[dict]:
    """Deduplicated chat spans only.

    The invoke_agent span repeats the usage attributes of its child chat span,
    so counting anything else would double charge.
    """
    seen: set[str] = set()
    selected = []
    for span in spans:
        if span.get("operationName") != "chat":
            continue
        if span["inputTokens"] <= 0 and span["outputTokens"] <= 0:
            continue
        span_id = str(span.get("id"))
        if span_id in seen:
            continue
        seen.add(span_id)
        selected.append(span)
    return selected


def aggregate_usage(spans: list[dict]) -> UsageTotals:
    usage = model_usage_spans(spans)
    if not usage:
        return UsageTotals()
    models = sorted({
        str(span.get("responseModel") or span.get("requestModel") or "")
        for span in usage
    } - {""})
    return UsageTotals(
        input_tokens=sum(span["inputTokens"] for span in usage),
        output_tokens=sum(span["outputTokens"] for span in usage),
        cached_tokens=sum(span["cachedTokens"] for span in usage),
        reasoning_tokens=sum(span["reasoningTokens"] for span in usage),
        model_spans=len(usage),
        models=tuple(models),
    )


def trace_ids(spans: list[dict]) -> set[str]:
    return {str(span.get("operation_Id")) for span in spans if span.get("operation_Id")}
