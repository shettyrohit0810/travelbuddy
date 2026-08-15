"""Loop mechanics, bounds and trajectory recording.

A scripted brain stands in for the LLM. That verifies control flow, bounds and
recording without an API key -- it does NOT verify decision quality, which is
unmeasurable here and is not claimed anywhere.
"""
import pytest

from app.agents.agent_loop import (
    Finish, ToolCall, run_agent, LLMBrain, NoBrainAvailable,
)


class ScriptedBrain:
    """Replays a fixed sequence of actions, recording what history it was shown."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.seen_history = []

    def decide(self, goal, tool_specs, history):
        self.seen_history.append(list(history))
        return self.actions.pop(0) if self.actions else Finish(False, "out of script")


def _tools(calls):
    def counter(**kwargs):
        calls.append(kwargs)
        return {"count": len(calls)}
    return {"probe": counter}


SPECS = [{"name": "probe", "description": "test tool", "parameters": {}}]


def test_agent_stops_when_it_decides_it_is_done():
    brain = ScriptedBrain([ToolCall("probe", {}), Finish(True, "found enough")])
    calls = []
    t = run_agent(agent_name="test", goal="g", brain=brain, tool_specs=SPECS,
                  tool_impls=_tools(calls), max_tool_calls=5)
    assert t.outcome == "succeeded"
    assert t.tool_calls_used == 1
    assert t.summary == "found enough"


def test_giving_up_is_a_first_class_outcome_not_an_error():
    """Honestly reporting 'not enough data' must be distinguishable from crashing."""
    brain = ScriptedBrain([Finish(False, "this town has almost no mapped POIs")])
    t = run_agent(agent_name="test", goal="g", brain=brain, tool_specs=SPECS,
                  tool_impls=_tools([]), max_tool_calls=5)
    assert t.outcome == "gave_up"
    assert "no mapped POIs" in t.summary


def test_tool_call_budget_is_enforced():
    brain = ScriptedBrain([ToolCall("probe", {}) for _ in range(50)])
    calls = []
    t = run_agent(agent_name="test", goal="g", brain=brain, tool_specs=SPECS,
                  tool_impls=_tools(calls), max_tool_calls=3)
    assert t.outcome == "budget_exhausted"
    assert t.tool_calls_used == 3
    assert len(calls) == 3


def test_wall_clock_budget_is_enforced_independently_of_call_count():
    import time

    class SlowBrain:
        def decide(self, goal, specs, history):
            time.sleep(0.05)
            return ToolCall("probe", {})

    def slow_tool(**kwargs):
        time.sleep(0.05)
        return {}

    t = run_agent(agent_name="test", goal="g", brain=SlowBrain(), tool_specs=SPECS,
                  tool_impls={"probe": slow_tool}, max_tool_calls=1000,
                  wall_clock_budget_s=0.2)
    assert t.outcome == "timeout"
    assert t.tool_calls_used < 1000


def test_tool_errors_are_recorded_without_killing_the_run():
    def boom(**kwargs):
        raise RuntimeError("provider exploded")

    brain = ScriptedBrain([ToolCall("probe", {}), Finish(False, "gave up after error")])
    t = run_agent(agent_name="test", goal="g", brain=brain, tool_specs=SPECS,
                  tool_impls={"probe": boom}, max_tool_calls=5)
    assert t.outcome == "gave_up"
    assert any(s.error and "provider exploded" in s.error for s in t.steps)


def test_unknown_tool_costs_a_turn_but_does_not_abort():
    brain = ScriptedBrain([ToolCall("nonexistent", {}), Finish(True, "recovered")])
    t = run_agent(agent_name="test", goal="g", brain=brain, tool_specs=SPECS,
                  tool_impls=_tools([]), max_tool_calls=5)
    assert t.outcome == "succeeded"
    assert any(s.error == "unknown tool" for s in t.steps)


def test_brain_failure_is_contained():
    class BrokenBrain:
        def decide(self, *a, **k):
            raise ValueError("model unavailable")

    t = run_agent(agent_name="test", goal="g", brain=BrokenBrain(), tool_specs=SPECS,
                  tool_impls=_tools([]), max_tool_calls=5)
    assert t.outcome == "error"
    assert "model unavailable" in t.summary


def test_trajectory_records_arguments_observations_and_reasoning():
    """The trace view and the eval both read this; if it is lossy they are both blind."""
    brain = ScriptedBrain([
        ToolCall("probe", {"radius_m": 20000}, reasoning="widening the search"),
        Finish(True, "done", reasoning="enough now"),
    ])
    t = run_agent(agent_name="test", goal="find POIs", brain=brain, tool_specs=SPECS,
                  tool_impls=_tools([]), max_tool_calls=5)
    call = next(s for s in t.steps if s.kind == "tool_call")
    assert call.arguments == {"radius_m": 20000}
    assert call.reasoning == "widening the search"
    assert call.observation is not None
    assert call.duration_ms is not None
    assert t.wall_clock_ms is not None


def test_brain_sees_prior_observations():
    brain = ScriptedBrain([ToolCall("probe", {}), ToolCall("probe", {}), Finish(True, "ok")])
    run_agent(agent_name="test", goal="g", brain=brain, tool_specs=SPECS,
              tool_impls=_tools([]), max_tool_calls=5)
    # Third decision must have seen both prior observations.
    assert len(brain.seen_history[2]) == 2


def test_llm_brain_refuses_to_construct_without_a_key(monkeypatch):
    """No silent rule-based substitute: absence of a model must be visible."""
    from app.core import config
    monkeypatch.setattr(config.settings, "OPENAI_API_KEY", None, raising=False)
    monkeypatch.setattr(config.settings, "XAI_API_KEY", None, raising=False)
    with pytest.raises(NoBrainAvailable):
        LLMBrain()


def test_llm_brain_constructs_for_each_supported_provider(monkeypatch):
    from app.core import config
    for attr, value, expected in [
        ("XAI_API_KEY", "xai-test", "xai"),
        ("OPENAI_API_KEY", "gsk_test", "groq"),
        ("OPENAI_API_KEY", "sk-test", "openai"),
    ]:
        monkeypatch.setattr(config.settings, "XAI_API_KEY", None, raising=False)
        monkeypatch.setattr(config.settings, "OPENAI_API_KEY", None, raising=False)
        monkeypatch.setattr(config.settings, attr, value, raising=False)
        assert LLMBrain().provider == expected
