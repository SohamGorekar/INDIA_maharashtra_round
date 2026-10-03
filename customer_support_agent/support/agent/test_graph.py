"""Tests for the agent's control flow, using a scripted fake model.

These never call Gemini. They exist to prove the graph itself is correct -- that
tool calls are dispatched, results fed back, the run ends when send_reply fires,
and a confused model cannot loop forever. Whether the agent makes *good*
decisions is a separate question, answered by support/agent/eval.py.
"""

import pytest
from langchain_core.messages import AIMessage

from support.agent import graph as graph_module
from support.agent.graph import MAX_STEPS, build_graph, initial_state


class ScriptedModel:
    """Returns a prepared sequence of AIMessages, one per call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        # Ran out of script: reply in prose, which ends the run.
        return AIMessage(content="(nothing further)")


@pytest.fixture
def scripted(monkeypatch):
    """Install a scripted model and disable the response cache."""

    def install(script):
        model = ScriptedModel(script)
        monkeypatch.setattr(graph_module, "get_llm", lambda tools=None: model)
        monkeypatch.setattr(graph_module, "invoke_with_retry",
                            lambda m, msgs: m.invoke(msgs))
        # Cache off: scripted runs must not be served a real cached response,
        # and must not poison the cache for real ones.
        monkeypatch.setattr(graph_module, "cache_get", lambda key: None)
        monkeypatch.setattr(graph_module, "cache_put", lambda key, value: None)
        return model

    return install


def tool_call(name, args, call_id="1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


# --- happy path ------------------------------------------------------------


def test_full_approve_flow(scripted):
    scripted([
        tool_call("get_order", {"order_id": "ORD-0045"}, "a"),
        tool_call("check_policy", {"topic": "returns"}, "b"),
        tool_call("take_action",
                  {"action_type": "refund", "order_id": "ORD-0045", "amount": 1022.74}, "c"),
        tool_call("verify_action", {"order_id": "ORD-0045"}, "d"),
        tool_call("send_reply", {"message": "Refund issued.", "decision": "APPROVE"}, "e"),
    ])

    state = build_graph().invoke(initial_state("refund please"))

    assert state["decision"] == "APPROVE"
    assert state["reply"] == "Refund issued."
    assert [e["tool"] for e in state["tool_log"]] == [
        "get_order", "check_policy", "take_action", "verify_action", "send_reply",
    ]


def test_tool_results_are_recorded(scripted):
    scripted([
        tool_call("get_order", {"order_id": "ORD-0045"}, "a"),
        tool_call("send_reply", {"message": "Denied.", "decision": "DENY"}, "b"),
    ])

    state = build_graph().invoke(initial_state("hello"))

    # The real tool ran against the real database, so the trace carries actual
    # order facts rather than a placeholder.
    order = state["tool_log"][0]["result"]
    assert order["found"] is True
    assert order["order_id"] == "ORD-0045"
    assert "days_since_purchase" in order
    assert state["facts"]["get_order"] == order


def test_run_stops_as_soon_as_reply_is_sent(scripted):
    model = scripted([
        tool_call("send_reply", {"message": "Done.", "decision": "DENY"}, "a"),
        # Should never be reached -- the run ends at send_reply.
        tool_call("take_action", {"action_type": "refund", "order_id": "ORD-0045"}, "b"),
    ])

    state = build_graph().invoke(initial_state("hello"))

    assert state["decision"] == "DENY"
    assert len(state["tool_log"]) == 1
    assert model.calls == 1


# --- error handling --------------------------------------------------------


def test_unknown_tool_is_reported_not_fatal(scripted):
    scripted([
        tool_call("teleport_customer", {"to": "mars"}, "a"),
        tool_call("send_reply", {"message": "Sorry.", "decision": "DENY"}, "b"),
    ])

    state = build_graph().invoke(initial_state("hello"))

    assert "Unknown tool" in state["tool_log"][0]["result"]["error"]
    # The agent still got to finish.
    assert state["decision"] == "DENY"


def test_bad_tool_arguments_come_back_as_an_error(scripted):
    scripted([
        # get_order takes order_id, not order_number.
        tool_call("get_order", {"order_number": "ORD-0045"}, "a"),
        tool_call("send_reply", {"message": "Sorry.", "decision": "DENY"}, "b"),
    ])

    state = build_graph().invoke(initial_state("hello"))

    assert "error" in state["tool_log"][0]["result"]
    assert state["decision"] == "DENY"


def test_invalid_decision_does_not_end_the_run(scripted):
    """send_reply with a bad decision is rejected, so the agent must retry."""
    scripted([
        tool_call("send_reply", {"message": "ok", "decision": "MAYBE"}, "a"),
        tool_call("send_reply", {"message": "ok", "decision": "ESCALATE"}, "b"),
    ])

    state = build_graph().invoke(initial_state("hello"))

    assert state["tool_log"][0]["result"]["sent"] is False
    assert state["decision"] == "ESCALATE"


def test_prose_reply_without_send_reply_ends_with_no_decision(scripted):
    scripted([AIMessage(content="I think you should contact the manufacturer.")])

    state = build_graph().invoke(initial_state("hello"))

    # No decision: the eval counts this as a failure, which is correct -- the
    # agent was told to always close with send_reply.
    assert state["decision"] == ""
    assert state["tool_log"] == []


# --- safety ----------------------------------------------------------------


def test_step_cap_stops_an_infinite_loop(scripted):
    # A model that calls the same tool forever and never replies.
    scripted([tool_call("get_order", {"order_id": "ORD-0045"}, str(i))
              for i in range(100)])

    state = build_graph().invoke(initial_state("hello"))

    assert state["decision"] == ""
    assert state["steps"] <= MAX_STEPS


def test_parallel_tool_calls_in_one_turn_all_run(scripted):
    """Gemini can request several tools at once; all of them must execute."""
    scripted([
        AIMessage(content="", tool_calls=[
            {"name": "verify_customer", "args": {"customer_id": "CUST-0010"}, "id": "a"},
            {"name": "get_order", "args": {"order_id": "ORD-0045"}, "id": "b"},
        ]),
        tool_call("send_reply", {"message": "ok", "decision": "APPROVE"}, "c"),
    ])

    state = build_graph().invoke(initial_state("hello"))

    assert [e["tool"] for e in state["tool_log"][:2]] == ["verify_customer", "get_order"]
    assert state["decision"] == "APPROVE"


def test_dry_run_leaves_the_store_untouched(scripted):
    from support.agent.tools import set_dry_run
    from support.data.db import connect, one

    set_dry_run(True)
    scripted([
        tool_call("take_action",
                  {"action_type": "refund", "order_id": "ORD-0002", "amount": 100.0}, "a"),
        tool_call("send_reply", {"message": "ok", "decision": "APPROVE"}, "b"),
    ])

    build_graph().invoke(initial_state("hello"))

    with connect() as conn:
        status = one(conn, "SELECT status FROM orders WHERE order_id = %s",
                     ("ORD-0002",))["status"]
    assert status == "active"


# --- nudging ---------------------------------------------------------------


def test_prose_reply_gets_nudged_then_succeeds(scripted):
    """A model that forgets send_reply should be reminded, not abandoned."""
    scripted([
        AIMessage(content="I have reviewed this and recommend a refund."),
        tool_call("send_reply", {"message": "Refund approved.", "decision": "APPROVE"}, "a"),
    ])

    state = build_graph().invoke(initial_state("hello"))

    assert state["nudges"] == 1
    assert state["decision"] == "APPROVE"


def test_nudging_gives_up_eventually(scripted):
    """A model that keeps ignoring the instruction must not loop forever."""
    from support.agent.graph import MAX_NUDGES

    scripted([AIMessage(content="Just prose, no tool call.") for _ in range(20)])

    state = build_graph().invoke(initial_state("hello"))

    assert state["decision"] == ""
    assert state["nudges"] == MAX_NUDGES
