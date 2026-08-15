"""A small, bounded tool-calling agent loop.

Deliberately minimal and framework-free: the interesting engineering in this project is
the boundary between the agent and the deterministic core, not the loop mechanics.

Two properties matter more than features:

1. **Hard bounds.** Every run is capped on tool calls AND wall-clock. An agent that can
   loop indefinitely is a cost incident waiting to happen, and "bounded" is the honest
   claim -- not "autonomous".
2. **A pluggable brain.** `AgentBrain` is the only place a model is consulted. Tests
   drive the loop with a scripted brain, which means the loop's control flow, bounds and
   trajectory recording are verifiable without an API key. The quality of the *decisions*
   is not verifiable that way, and this module makes no claim about it.
"""
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol

from app.agents.trajectory import Trajectory

logger = logging.getLogger("app.agents.agent_loop")


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    reasoning: Optional[str] = None


@dataclass
class Finish:
    """The agent has decided to stop, successfully or not."""
    success: bool
    summary: str
    reasoning: Optional[str] = None


class AgentBrain(Protocol):
    """Decides the next action given the goal and everything observed so far."""

    def decide(self, goal: str, tool_specs: List[Dict[str, Any]],
               history: List[Dict[str, Any]]) -> Any:  # ToolCall | Finish
        ...


class NoBrainAvailable(Exception):
    """Raised when no LLM is configured, so no agent can run.

    Deliberately an exception rather than a silent rule-based fallback: substituting
    hardcoded heuristics and continuing would make an unmeasurable claim look like a
    working agent. Callers catch this and record `outcome="unavailable"`.
    """


class LLMBrain:
    """Real brain, backed by whatever LLM the app is configured with."""

    def __init__(self, model_hint: str = "default"):
        from app.core.config import settings
        provider = settings.LLM_PROVIDER
        if provider is None:
            raise NoBrainAvailable("no XAI_API_KEY or OPENAI_API_KEY configured")
        self.provider = provider
        self.model_hint = model_hint

    def decide(self, goal: str, tool_specs, history):
        from app.core.llm import get_openai_client, get_model_name

        system = (
            "You are a data-acquisition agent for a trip planner. Your ONLY job is to "
            "find enough real points of interest for a trip. You do not schedule "
            "anything, you do not decide budgets, and you do not evaluate itineraries -- "
            "deterministic code owns all of that.\n\n"
            "Call tools to investigate. After each observation, decide whether to try "
            "something different (a wider radius, a relaxed notability filter, a "
            "different resolution of an ambiguous place name) or to stop.\n\n"
            "If you cannot find enough real places, STOP and say so. Reporting honestly "
            "that a destination has little data is a correct outcome. Never claim to "
            "have found places you did not observe.\n\n"
            "Respond with JSON only: either "
            '{"action":"tool","name":"<tool>","arguments":{...},"reasoning":"<why>"} or '
            '{"action":"finish","success":<bool>,"summary":"<what you concluded>","reasoning":"<why>"}'
        )
        payload = {"goal": goal, "tools": tool_specs, "history": history}
        client = get_openai_client()
        response = client.chat.completions.create(
            model=get_model_name(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, default=str)},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        if data.get("action") == "tool":
            return ToolCall(
                name=data["name"],
                arguments=data.get("arguments") or {},
                reasoning=data.get("reasoning"),
            )
        return Finish(
            success=bool(data.get("success")),
            summary=data.get("summary", ""),
            reasoning=data.get("reasoning"),
        )


def run_agent(
    *,
    agent_name: str,
    goal: str,
    brain: AgentBrain,
    tool_specs: List[Dict[str, Any]],
    tool_impls: Dict[str, Callable[..., Any]],
    max_tool_calls: int = 6,
    wall_clock_budget_s: float = 90.0,
    observation_summarizer: Optional[Callable[[str, Any], Any]] = None,
) -> Trajectory:
    """Run the loop until the agent finishes or hits a bound. Never raises."""
    trajectory = Trajectory(agent=agent_name, goal=goal, tool_call_budget=max_tool_calls)
    history: List[Dict[str, Any]] = []
    started = time.perf_counter()

    while True:
        elapsed = time.perf_counter() - started
        if trajectory.tool_calls_used >= max_tool_calls:
            trajectory.outcome = "budget_exhausted"
            trajectory.summary = f"Stopped after {max_tool_calls} tool calls without resolving the goal."
            trajectory.record("outcome", "budget_exhausted", reasoning=trajectory.summary)
            break
        if elapsed > wall_clock_budget_s:
            trajectory.outcome = "timeout"
            trajectory.summary = f"Stopped after {elapsed:.1f}s (budget {wall_clock_budget_s}s)."
            trajectory.record("outcome", "timeout", reasoning=trajectory.summary)
            break

        try:
            action = brain.decide(goal, tool_specs, history)
        except Exception as e:
            trajectory.outcome = "error"
            trajectory.summary = f"Brain failed: {e}"
            trajectory.record("outcome", "brain_error", error=str(e))
            break

        if isinstance(action, Finish):
            trajectory.outcome = "succeeded" if action.success else "gave_up"
            trajectory.summary = action.summary
            trajectory.record("decision", "finish", reasoning=action.reasoning,
                              observation={"success": action.success, "summary": action.summary})
            break

        impl = tool_impls.get(action.name)
        if impl is None:
            # Recorded as an observation rather than an error so the agent can correct
            # itself; a hallucinated tool name should cost a turn, not the whole run.
            history.append({"tool": action.name, "error": "unknown tool"})
            trajectory.record("tool_call", action.name, arguments=action.arguments,
                              error="unknown tool", reasoning=action.reasoning)
            continue

        call_started = time.perf_counter()
        try:
            observation = impl(**action.arguments)
            error = None
        except Exception as e:
            observation, error = None, f"{type(e).__name__}: {e}"
        duration_ms = (time.perf_counter() - call_started) * 1000

        # The full observation goes in the trajectory (for inspection); a summarised
        # form goes to the brain, so a 120-POI payload does not swamp its context.
        visible = observation
        if observation_summarizer and error is None:
            visible = observation_summarizer(action.name, observation)

        trajectory.record("tool_call", action.name, arguments=action.arguments,
                          observation=observation, reasoning=action.reasoning,
                          duration_ms=round(duration_ms, 1), error=error)
        history.append({"tool": action.name, "arguments": action.arguments,
                        "observation": visible, "error": error})

    trajectory.wall_clock_ms = round((time.perf_counter() - started) * 1000, 1)
    return trajectory
