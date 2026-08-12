"""Environment-driven configuration. No secrets are stored in source."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def env(name: str, default: str = "") -> str:
    # A .env written with CRLF leaves a trailing \r that corrupts HTTP headers.
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    apim_base: str
    apim_subscription_key: str
    agent_id: str
    agent_route: str
    api_version: str
    app_insights_app_id: str
    cost_centre: str
    telemetry_lookback_hours: int
    telemetry_timeout_seconds: int
    telemetry_poll_seconds: int

    def responses_url(self) -> str:
        return (
            f"{self.apim_base}/agents/{self.agent_id}/{self.agent_route}"
            f"/responses?api-version={self.api_version}"
        )

    def require(self, *names: str) -> None:
        missing = [name for name in names if not getattr(self, name)]
        if missing:
            raise RuntimeError(
                "Missing configuration: "
                + ", ".join(sorted(missing))
                + ". See .env.example."
            )


def load_settings(dotenv_path: Path | None = None) -> Settings:
    load_dotenv(dotenv_path=dotenv_path or _PROJECT_ROOT / ".env", override=False)
    return Settings(
        apim_base=env("APIM_BASE").rstrip("/"),
        apim_subscription_key=env("APIM_SUBSCRIPTION_KEY"),
        agent_id=env("AGENT_ID"),
        agent_route=env("AGENT_ROUTE"),
        api_version=env("FOUNDRY_API_VERSION", "v1"),
        app_insights_app_id=env("APPLICATIONINSIGHTS_APP_ID"),
        cost_centre=env("E2E_COST_CENTRE", "CC-1000"),
        telemetry_lookback_hours=int(env("TELEMETRY_LOOKBACK_HOURS", "2")),
        telemetry_timeout_seconds=int(env("TELEMETRY_INGESTION_TIMEOUT_SECONDS", "180")),
        telemetry_poll_seconds=int(env("TELEMETRY_POLL_SECONDS", "10")),
    )
