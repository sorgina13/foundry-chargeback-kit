import asyncio
from dataclasses import dataclass
from typing import Any, Annotated

from agent_framework import Agent, tool
from pydantic import Field


def _as_text(result: Any) -> str:
    """Normalise Agent Framework run results without coupling tools to one result shape."""
    for name in ("text", "output_text", "content"):
        value = getattr(result, name, None)
        if isinstance(value, str):
            return value
    return str(result)


@dataclass(frozen=True)
class AgentSet:
    orchestrator: Agent
    researcher: Agent
    analyst: Agent
    reviewer: Agent


def build_agents(client: Any) -> AgentSet:
    researcher = Agent(
        client=client,
        name="researcher",
        instructions=(
            "Investigate only the delegated task. Return concise findings, explicit "
            "evidence, and unresolved uncertainties. Do not invent sources."
        ),
        default_options={"store": False},
    )

    analyst = Agent(
        client=client,
        name="analyst",
        instructions=(
            "Analyse the supplied evidence. Separate observations from hypotheses, "
            "identify dependencies, and propose tests that could falsify each hypothesis."
        ),
        default_options={"store": False},
    )

    reviewer = Agent(
        client=client,
        name="reviewer",
        instructions=(
            "Critically review the supplied analysis. Flag unsupported claims, missing "
            "evidence, unsafe actions, and circular reasoning. Return precise corrections."
        ),
        default_options={"store": False},
    )

    @tool(
        approval_mode="never_require",
        description="Delegate focused evidence gathering to the research subagent.",
    )
    async def research(
        task: Annotated[str, Field(description="A narrow, self-contained research task")],
    ) -> str:
        return _as_text(await researcher.run(task))

    @tool(
        approval_mode="never_require",
        description="Delegate evidence analysis and hypothesis generation to the analysis subagent.",
    )
    async def analyse(
        evidence: Annotated[str, Field(description="Evidence and context to analyse")],
    ) -> str:
        return _as_text(await analyst.run(evidence))

    @tool(
        approval_mode="never_require",
        description="Delegate adversarial validation to the review subagent.",
    )
    async def review(
        proposal: Annotated[str, Field(description="Analysis or proposed answer to challenge")],
    ) -> str:
        return _as_text(await reviewer.run(proposal))

    @tool(
        approval_mode="never_require",
        description="Run independent research and analysis subagents concurrently.",
    )
    async def investigate_in_parallel(
        task: Annotated[str, Field(description="Task both specialists can assess independently")],
    ) -> str:
        research_result, analysis_result = await asyncio.gather(
            researcher.run(task),
            analyst.run(task),
        )
        return (
            "RESEARCH RESULT:\n" + _as_text(research_result) +
            "\n\nANALYSIS RESULT:\n" + _as_text(analysis_result)
        )

    orchestrator = Agent(
        client=client,
        name="orchestrator",
        instructions=(
            "You are an autonomous orchestrator. Solve the user's objective through a "
            "bounded reason-act-observe loop. Delegate only when a specialist adds value. "
            "Use parallel investigation only for independent work. Inspect every returned "
            "result rather than accepting it blindly. Use the reviewer for material causal, "
            "risk, or action claims. Repeat only when a clear evidence gap remains. Stop "
            "when the answer is supported or further progress requires unavailable data. "
            "Clearly distinguish facts, hypotheses, recommendations, and limitations."
        ),
        tools=[research, analyse, review, investigate_in_parallel],
        default_options={"store": False},
    )

    return AgentSet(
        orchestrator=orchestrator,
        researcher=researcher,
        analyst=analyst,
        reviewer=reviewer,
    )
