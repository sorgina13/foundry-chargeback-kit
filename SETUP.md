# Setup

The order below matters: telemetry must be provable before any figure is priced.

## 1. Prepare and test the agent

```bash
cd agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m unittest -v test_telemetry.py
```

`test_telemetry.py` exercises `ChargebackSpanProcessor` without making an Azure
call: baggage becomes both chargeback attributes, and missing baggage does not
create misleading ones.

For local execution set `FOUNDRY_PROJECT_ENDPOINT` and
`AZURE_AI_MODEL_DEPLOYMENT_NAME`. Set `APPLICATIONINSIGHTS_CONNECTION_STRING`
only when local spans should leave the machine.

## 2. Connect Foundry to Application Insights

Create or select an Application Insights resource and connect it to the Foundry
project that hosts the agent. Foundry then injects
`APPLICATIONINSIGHTS_CONNECTION_STRING` into the container, and
`configure_observability()` configures the Azure Monitor OpenTelemetry exporter.
The connection is never hard-coded.

Invoke the agent once and confirm Application Insights contains:

- the hosted invocation span;
- orchestrator and specialist model spans;
- tool spans;
- nonzero `gen_ai.usage.input_tokens` or `gen_ai.usage.output_tokens` on model
  calls that consumed tokens.

Do not proceed if token attributes are absent. Fix telemetry at the model-call
producer rather than treating missing values as zero-cost usage.

## 3. Deploy the instrumented agent

Set the `ai-project` endpoint in [agent/azure.yaml](agent/azure.yaml) first, then:

```bash
cd agent
azd auth login
azd ext install microsoft.foundry
azd up
```

The entry point must remain `main.py`. It passes
`configure_chargeback_observability` to `ResponsesHostServer`; without that
callback the chargeback attributes are never registered, even though generic
hosted-agent telemetry still works.

`azure.yaml` also sets `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false`,
which keeps trace IDs, model identity, status, latency and token usage while
excluding prompt and response content.

## 4. Configure APIM correlation

1. Attach an Application Insights logger to APIM and enable diagnostics for the
   hosted-agent API. Use W3C correlation.
2. Preserve a valid incoming `traceparent`. Let APIM instrumentation create one
   when none exists — do not unconditionally overwrite it.
3. Authenticate the caller with `validate-jwt` and derive `consumerId` and
   `costCentre` from validated claims or a server-side lookup keyed by the
   subject or client ID. For service principals, `azp` or `appid` is usually
   more meaningful than a user claim.
4. Forward and echo a validated `x-request-id` from `outbound` **and**
   `on-error`, so failed requests stay correlatable.

Apply the fragment in [apim/policy-chargeback.xml](apim/policy-chargeback.xml).
To merge it into an existing policy without losing rules such as
`llm-token-limit`:

```bash
cd apim
python apply_policy.py --source exported-policy.xml --backend-id <your-backend-id>
```

The script aborts if the anchor is ambiguous, if the additions are already
present, or if any preserved element count drops. Review the generated policy
before deploying it; do not treat generated or captured copies as independent
sources of truth.

APIM and Foundry may share one Application Insights resource for simple joins.
If they use separate resources, query both and join on request ID or trace ID.

## 5. Emit an unsampled gateway ledger

For every accepted request, persist a small event to a durable, unsampled sink
such as Event Hubs (`log-to-eventhub`):

```json
{
  "timestamp": "2026-08-07T00:00:00Z",
  "requestId": "…",
  "consumerId": "validated-subject-or-client",
  "costCentre": "CC-1000",
  "apiId": "hosted-agent-api",
  "agentId": "ChargebackAgent",
  "httpStatus": 200,
  "durationMs": 10000
}
```

Application Insights traces are useful operationally but can be sampled, delayed
or retained for less time than finance requires. Never log authorization headers,
subscription keys, prompts or completions in the ledger.

## 6. Run the acceptance test

```bash
cp .env.example .env      # fill in APIM and telemetry values
pip install -e .
az login
python -m foundry_chargeback_kit.cli e2e --json
```

`APPLICATIONINSIGHTS_APP_ID` must be the component's Application ID from
Application Insights **API Access** — not the resource name, instrumentation key
or connection string. The signed-in identity needs permission to query that
resource. No API key is stored anywhere in this repository.

The test passes only when:

- APIM echoes the request ID;
- Application Insights returns spans with the same `chargeback.request.id`;
- all selected spans share one `operation_Id`;
- at least one deduplicated `chat` span reports measured usage.

## 7. Aggregate and reconcile

Discovery query, since table placement varies with exporter configuration:

```kusto
union isfuzzy=true requests, dependencies, customEvents
| where timestamp > ago(1h)
| extend requestId = coalesce(
             tostring(customDimensions["chargeback.request.id"]),
             tostring(customDimensions["request.id"])),
         inputTokens = tolong(customDimensions["gen_ai.usage.input_tokens"]),
         outputTokens = tolong(customDimensions["gen_ai.usage.output_tokens"]),
         model = tostring(customDimensions["gen_ai.request.model"])
| where isnotempty(requestId) or inputTokens > 0 or outputTokens > 0
| project timestamp, itemType, name, operation_Id, requestId,
          inputTokens, outputTokens, model
| order by timestamp asc
```

For production aggregation, resolve `requestId -> operation_Id` from the root
span, then sum usage across every model span sharing that `operation_Id`. Join
the result to the gateway ledger on `requestId`, never on timestamps.

Reconcile the estimate against Azure Cost Management by billing period,
resource, deployment, meter and region. Expect timing and aggregation
differences.

## Validation procedure

1. Send one request with a unique `x-request-id` through APIM.
2. Confirm the response echoes exactly that ID.
3. Confirm the ledger event contains the authenticated consumer mapping.
4. Find the root span by `customDimensions["request.id"]`.
5. Record its `operation_Id`.
6. List all spans with that `operation_Id`.
7. Confirm orchestrator and delegated model calls appear as children.
8. Confirm model spans contain nonzero `gen_ai.usage.*` values.
9. Confirm parallel specialist calls remain in the same trace.
10. Sum model usage and join it to the ledger on `requestId`.
11. Exercise a failed request and confirm correlation survives `on-error`.
12. Compare daily aggregates with Foundry monitoring and Cost Management,
    allowing for ingestion delay.

## Production safeguards

- Never trust a caller-provided cost centre or consumer ID.
- Never store subscription keys, bearer tokens, prompts or completions in the
  ledger.
- Keep billing events durable, unsampled and idempotent by `requestId` plus
  event type.
- Record retries as attempts so token costs are not silently collapsed.
- Retain failed and cancelled model calls when the provider reports billable use.
- Deduplicate model spans before summing, and keep cached and reasoning tokens
  as separate usage classes.
- Version rates by provider, model deployment, region, meter and effective date.
- Monitor unmatched ledger rows, traces without ledger rows, duplicate request
  IDs, missing token attributes and reconciliation variance.
- Treat telemetry as usage evidence and Cost Management as billed-cost truth.
