# Copilot instructions

## Project

`foundry-chargeback-kit` correlates an authenticated consumer request at Azure
API Management with the model and tool spans a Microsoft Foundry hosted agent
emits, so token usage can be attributed for showback and chargeback.

Key identifiers and their owners:

| Value | Owner | Purpose |
|---|---|---|
| `consumerId` / `costCentre` | APIM | Trusted chargeback dimension from authenticated identity |
| `x-request-id` | APIM | Stable 32-hex business request identifier |
| `traceparent` | OpenTelemetry | W3C trace ID plus parent-span relationship |
| `operation_Id` | Application Insights | Joins root invocation to child spans |
| `gen_ai.usage.*` | Agent Framework | Measured token usage on model-call spans |

## Rules

- Never treat a caller-supplied cost-centre header as authoritative identity.
  Chargeback dimensions must be derived from the authenticated principal at APIM.
- Do not unconditionally overwrite an inbound `traceparent`; that breaks the
  caller's trace.
- Never commit secrets. Use `.env` (gitignored) locally and managed identity in
  Azure. No connection strings, keys, or subscription IDs in source or docs.
- Prefer `DefaultAzureCredential` over key-based authentication.

## Conventions

- Python >= 3.10, formatted and linted with `ruff` (line length 100).
- Library code lives under `src/foundry_chargeback_kit/`.
- Use British English in documentation.
