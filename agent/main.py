import asyncio
import os

from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from agents import build_agents
from telemetry import configure_chargeback_observability


async def main() -> None:
    load_dotenv()

    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    )

    agents = build_agents(client)
    # Passing the callback is what registers ChargebackSpanProcessor on the hosted server.
    server = ResponsesHostServer(
        agents.orchestrator,
        configure_observability=configure_chargeback_observability,
    )
    await server.run_async()


if __name__ == "__main__":
    asyncio.run(main())
