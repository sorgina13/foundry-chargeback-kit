"""Prototype runner: probe correlation, or run the full end-to-end acceptance test."""
import argparse
import json
import sys

from .config import load_settings
from .correlation import mint_request_id
from .gateway import call_agent
from .showback import Rates, variable_cost
from .telemetry_query import TelemetryClient, aggregate_usage, model_usage_spans, trace_ids

DEFAULT_PROMPT = "For chargeback telemetry verification, reply with the single word telemetry-ok."


def cmd_probe(args: argparse.Namespace) -> int:
    """Channel A/B check: does APIM forward and echo the correlation key?"""
    settings = load_settings()
    request_id = args.request_id or mint_request_id()

    print(f"url        : {settings.responses_url()}")
    print(f"request id : {request_id}")

    result = call_agent(settings, args.prompt, request_id, args.cost_centre)
    print(f"status     : {result.status} ({result.latency_ms} ms)")
    print(f"echoed     : {result.echoed_request_id}")
    print(f"response id: {result.response_id}")

    if not result.ok:
        print(f"body       : {str(result.body)[:1000]}", file=sys.stderr)
        return 1
    if not result.correlation_echoed:
        print("FAIL: APIM did not echo the request ID", file=sys.stderr)
        return 1
    print("PASS: request ID forwarded and echoed")
    return 0


def cmd_e2e(args: argparse.Namespace) -> int:
    """One APIM call, then poll Application Insights until usage-bearing spans arrive."""
    settings = load_settings()
    request_id = args.request_id or mint_request_id()

    result = call_agent(settings, args.prompt, request_id, args.cost_centre)
    print(f"request id : {request_id}")
    print(f"status     : {result.status} ({result.latency_ms} ms)")

    if not result.ok:
        print(f"FAIL: APIM returned HTTP {result.status}: {str(result.body)[:1000]}", file=sys.stderr)
        return 1
    if not result.correlation_echoed:
        print(
            f"FAIL: APIM echoed x-request-id={result.echoed_request_id!r}", file=sys.stderr
        )
        return 1

    client = TelemetryClient(settings)
    print(f"polling Application Insights for up to {settings.telemetry_timeout_seconds}s ...")
    spans = client.await_model_usage(request_id)

    if not spans:
        print("FAIL: no spans carried chargeback.request.id.", file=sys.stderr)
        if result.response_id:
            diagnostic = client.spans_for_response(result.response_id)
            print(f"diagnostic spans by response id: {len(diagnostic)}", file=sys.stderr)
        return 1

    observed_traces = trace_ids(spans)
    usage = aggregate_usage(spans)

    print(f"spans      : {len(spans)} ({len(model_usage_spans(spans))} priced model spans)")
    print(f"operation_Id: {', '.join(sorted(observed_traces))}")
    print(f"models     : {', '.join(usage.models) or 'unknown'}")
    print(
        f"tokens     : input={usage.input_tokens} output={usage.output_tokens} "
        f"cached={usage.cached_tokens} reasoning={usage.reasoning_tokens}"
    )

    if len(observed_traces) != 1:
        print(
            f"FAIL: spans span {len(observed_traces)} traces; lineage is not provable.",
            file=sys.stderr,
        )
        return 1
    if not usage.measured:
        # Absent usage attributes are missing data, not zero-cost usage.
        print("FAIL: no model span reported measured token usage.", file=sys.stderr)
        return 1

    rates = Rates.indicative()
    cost = variable_cost(usage, rates)
    print(f"cost centre: {result.cost_centre}")
    print(f"variable   : {cost:.6f} {rates.currency} (indicative rates, not invoiced cost)")

    if args.json:
        print(json.dumps({
            "requestId": request_id,
            "costCentre": result.cost_centre,
            "operationId": sorted(observed_traces)[0],
            "responseId": result.response_id,
            "inputTokens": usage.input_tokens,
            "outputTokens": usage.output_tokens,
            "cachedTokens": usage.cached_tokens,
            "reasoningTokens": usage.reasoning_tokens,
            "models": list(usage.models),
            "estimatedVariableCost": round(cost, 8),
            "currency": rates.currency,
        }, indent=2))

    print("PASS: correlation, lineage and measured usage verified")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chargeback", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, handler, help_text in (
        ("probe", cmd_probe, "Verify APIM forwards and echoes x-request-id."),
        ("e2e", cmd_e2e, "Full acceptance test: call, correlate, price."),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("--prompt", default=DEFAULT_PROMPT)
        cmd.add_argument("--cost-centre", default=None)
        cmd.add_argument("--request-id", default=None, help="Lowercase 32-hex W3C trace ID.")
        cmd.set_defaults(handler=handler)

    sub.choices["e2e"].add_argument("--json", action="store_true", help="Emit a JSON ledger row.")

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
