"""Apply rates to measured usage and allocate fixed cost.

This produces showback estimates. Azure Cost Management remains the financial
source of truth; reconcile before presenting any figure as chargeback.
"""
from dataclasses import dataclass

from .telemetry_query import UsageTotals


@dataclass(frozen=True)
class Rates:
    """Per-token rates. Version these by provider, deployment, region and effective date."""

    input_per_token: float
    cached_input_per_token: float
    output_per_token: float
    currency: str = "USD"

    @classmethod
    def indicative(cls) -> "Rates":
        # Placeholder values. Replace with your contracted model price list.
        return cls(
            input_per_token=1.25 / 1_000_000,
            cached_input_per_token=0.125 / 1_000_000,
            output_per_token=10.00 / 1_000_000,
        )


def variable_cost(usage: UsageTotals, rates: Rates) -> float:
    """Price measured usage, keeping cached input on its own discounted rate."""
    if not usage.measured:
        raise ValueError("No measured usage; pricing it would fabricate a charge.")
    # gen_ai.usage.input_tokens includes cached tokens, which bill differently.
    billable_input = max(usage.input_tokens - usage.cached_tokens, 0)
    return (
        billable_input * rates.input_per_token
        + usage.cached_tokens * rates.cached_input_per_token
        + usage.output_tokens * rates.output_per_token
    )


def allocate_fixed_cost(
    requests_by_cost_centre: dict[str, int],
    fixed_cost_per_hour: float,
    period_hours: float,
) -> dict[str, float]:
    """Apportion always-on hosted compute by request share.

    Report the result as allocation, never as measured per-request usage.
    """
    total_requests = sum(requests_by_cost_centre.values())
    if total_requests == 0:
        return {centre: 0.0 for centre in requests_by_cost_centre}
    pool = fixed_cost_per_hour * period_hours
    return {
        centre: pool * count / total_requests
        for centre, count in requests_by_cost_centre.items()
    }
