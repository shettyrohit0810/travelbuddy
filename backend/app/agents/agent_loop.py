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
    """Real brain, backed by whatever LLM the app is configured with.

    Uses **native tool calling**, not JSON-mode prompting. That distinction turned out
    to matter: under JSON mode the model answered in free text describing a tool call,
    and a real run produced "Geocoded Chikmagalur and searched within 5km, retrieving
    multiple POIs" after making zero calls -- complete with plausible invented
    attraction names. Native tool calling removes the text channel it fabricated into.
    """

    SYSTEM = (
        "You are a data-acquisition agent for a trip planner. Your ONLY job is to find "
        "enough real points of interest for a trip. You do not schedule anything, you "
        "do not decide budgets, and you do not evaluate itineraries -- deterministic "
        "code owns all of that.\n\n"
        "Use the tools to investigate. After each observation, decide whether to try "
        "something different (a wider radius, a relaxed notability filter, a different "
        "resolution of an ambiguous place name) or to stop.\n\n"
        "Never answer from your own knowledge of a place. If you have not called a "
        "tool, you have not found anything.\n\n"
        "Call `finish` when done. success=false for a destination that genuinely lacks "
        "data is a correct outcome, not a failure."
    )

    # `finish` is a tool rather than free text, so every turn is a structured call and
    # the model has no prose channel in which to narrate an unperformed search.
    FINISH_TOOL = {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Call only after gathering evidence with other tools. Use success=false "
                "when the destination genuinely lacks data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "summary": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["success", "summary"],
            },
        },
    }

    MAX_DECODE_ATTEMPTS = 3
    DECODE_BACKOFF_S = 0.6

    def __init__(self, model_hint: str = "default"):
        from app.core.config import settings
        provider = settings.LLM_PROVIDER
        if provider is None:
            raise NoBrainAvailable("no OPENAI_API_KEY or XAI_API_KEY configured")
        self.provider = provider
        self.model_hint = model_hint

    def _build_messages(self, goal, history):
        """Replay the run as a genuine tool-calling conversation.

        Each past step becomes an assistant tool_call plus its tool result, so prior
        observations arrive as tool output rather than as prose we summarised for it.
        """
        messages = [
            {"role": "system", "content": self.SYSTEM},
            {"role": "user", "content": goal},
        ]
        for index, entry in enumerate(history):
            call_id = f"call_{index}"
            messages.append({
                "role": "assistant",
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": entry["tool"],
                        "arguments": json.dumps(entry.get("arguments") or {}),
                    },
                }],
            })
            result = entry.get("error") or entry.get("observation")
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                # Truncated: a 120-POI payload would crowd out the goal itself.
                "content": json.dumps(result, default=str)[:4000],
            })
        return messages

    def decide(self, goal: str, tool_specs, history):
        from app.core.llm import get_client, get_model_name

        tools = [
            {"type": "function", "function": {
                "name": spec["name"], "description": spec["description"],
                "parameters": spec["parameters"]}}
            for spec in tool_specs
        ] + [self.FINISH_TOOL]

        client = get_client()
        messages = self._build_messages(goal, history)

        # Providers reject their own output intermittently -- Groq's gpt-oss models
        # returned HTTP 400 `json_validate_failed` on roughly a third of identical
        # requests, with an empty failed_generation. A provider-side flake must not kill
        # a run that has already spent tool calls.
        last_error = None
        for attempt in range(self.MAX_DECODE_ATTEMPTS):
            try:
                response = client.chat.completions.create(
                    model=get_model_name(), messages=messages,
                    tools=tools, tool_choice="auto",
                )
                break
            except Exception as exc:
                last_error = exc
                logger.warning(
                    f"LLM decode attempt {attempt + 1}/{self.MAX_DECODE_ATTEMPTS} "
                    f"failed: {str(exc)[:160]}"
                )
                time.sleep(self.DECODE_BACKOFF_S * (attempt + 1))
        else:
            raise last_error

        message = response.choices[0].message
        calls = message.tool_calls or []
        if not calls:
            # Neither a tool call nor a finish call. Treated as giving up rather than
            # guessing at an interpretation of whatever prose came back.
            return Finish(
                success=False,
                summary=(message.content or "Model returned no action.")[:400],
                reasoning="Model produced no tool call.",
            )

        call = calls[0]
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}

        if call.function.name == "finish":
            return Finish(
                success=bool(arguments.get("success")),
                summary=arguments.get("summary", ""),
                reasoning=arguments.get("reasoning"),
            )

        reasoning = arguments.pop("reasoning", None)
        return ToolCall(name=call.function.name, arguments=arguments, reasoning=reasoning)


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
            # A success claimed without a single tool call is a fabrication, not a
            # result. Observed in practice: the model reported "geocoded Chikmagalur and
            # searched within 5km, retrieving multiple POIs" after making zero calls.
            # Nothing it could have observed exists, so the claim is recorded as what it
            # is rather than taken at face value. Callers already read results out of
            # recorded observations rather than this summary, so the fabrication could
            # never reach an itinerary -- but an unchallenged "succeeded" in the trace
            # would still mislead whoever reads it later.
            if action.success and trajectory.tool_calls_used == 0:
                trajectory.outcome = "unsubstantiated"
                trajectory.summary = (
                    "Model reported success without calling any tool; claim discarded. "
                    f"Its stated reason was: {action.reasoning or action.summary}"
                )
                trajectory.record(
                    "outcome", "unsubstantiated",
                    reasoning=trajectory.summary,
                    observation={"claimed": action.summary, "tool_calls": 0},
                )
                break

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
