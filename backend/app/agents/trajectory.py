"""Trajectory recording for the agentic layer.

Every tool call an agent makes, the observation it got back, and the decision it took
next -- captured so a run can be inspected after the fact rather than inferred from a
final answer. This is deliberately a plain, dependency-free recorder: it is read by the
API and the frontend trace view, and it must never be the reason a planning request
fails, so recording is best-effort and never raises into the caller.

It records what happened, not what should have happened. A step where the agent chose
badly is exactly as interesting as one where it chose well, so nothing here filters or
scores -- judgement belongs to whoever reads the trace.
"""
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TrajectoryStep:
    index: int
    kind: str                      # "tool_call" | "decision" | "outcome"
    name: str                      # tool name, or a short label for a decision
    arguments: Optional[Dict[str, Any]] = None
    observation: Optional[Any] = None
    reasoning: Optional[str] = None       # why the agent did this, in its own words
    duration_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class Trajectory:
    """One agent's run within a planning request."""
    agent: str
    goal: str
    steps: List[TrajectoryStep] = field(default_factory=list)
    outcome: Optional[str] = None         # "recovered" | "gave_up" | "not_needed" | "error"
    summary: Optional[str] = None
    tool_calls_used: int = 0
    tool_call_budget: Optional[int] = None
    wall_clock_ms: Optional[float] = None

    def record(
        self,
        kind: str,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
        observation: Any = None,
        reasoning: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> TrajectoryStep:
        step = TrajectoryStep(
            index=len(self.steps), kind=kind, name=name, arguments=arguments,
            observation=observation, reasoning=reasoning,
            duration_ms=duration_ms, error=error,
        )
        self.steps.append(step)
        if kind == "tool_call":
            self.tool_calls_used += 1
        return step

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def summarize(trajectories: List["Trajectory"]) -> Dict[str, Any]:
    """Aggregate view for the API and the eval harness."""
    return {
        "agents_run": len(trajectories),
        "total_tool_calls": sum(t.tool_calls_used for t in trajectories),
        "outcomes": [{"agent": t.agent, "outcome": t.outcome, "summary": t.summary} for t in trajectories],
        "trajectories": [t.to_dict() for t in trajectories],
    }
