# foundry-chargeback-kit

End-to-end consumer cost tracing for Microsoft Foundry hosted agents fronted by
Azure API Management (APIM).

Correlates a consumer request at the gateway with every model and tool span the
hosted agent produces, so token usage can be attributed to an authenticated
consumer or cost centre.

## Status

Scaffold. Content to be added.

## Correlation model

```text
authenticated consumer -> requestId -> traceId -> model spans -> token usage
```

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Licence

MIT. See [LICENSE](LICENSE).
