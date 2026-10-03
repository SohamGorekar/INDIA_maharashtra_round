"""The agent as a LangGraph state machine.

Shape of the graph:

    START -> agent -> (tool calls?) -> tools -> agent -> ...
                   \\-> END                    \\-> END once send_reply is called

State is a plain dict of JSON-friendly values. That is a deliberate constraint:
it keeps every intermediate state snapshottable, which matters for debugging now
and for instrumenting the agent later.
"""

import json
from typing import Annotated, TypedDict

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from support.agent.llm import (
    cache_get,
    cache_key,
    cache_put,
    get_llm,
    invoke_with_retry,
)
from support.agent.prompts import SYSTEM_PROMPT
from support.agent.tools import ALL_TOOLS, TOOLS_BY_NAME, TOOLS_SIGNATURE

# Hard ceiling on agent turns. Without it, a confused model can loop on the same
# tool until the API quota is gone.
MAX_STEPS = 15

# How many times to remind a model that forgot to call send_reply.
MAX_NUDGES = 2


class AgentState(TypedDict):
    """Everything the agent carries between steps."""

    messages: Annotated[list, add_messages]
    # Facts the agent has gathered, keyed by tool name. Useful for the UI and
    # for understanding what the agent actually knew when it decided.
    facts: dict
    # Set once send_reply runs. Its presence is what ends the run.
    decision: str
    reply: str
    steps: int
    # How many times we have reminded the model to call send_reply.
    nudges: int
    # Running log of tool calls, for the UI timeline.
    tool_log: list


def _call_model(state: AgentState) -> dict:
    """The agent node: ask Gemini what to do next."""
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]

    # Cache on the exact conversation so far. Identical history -> identical
    # next move, so a repeated run costs no quota.
    key = cache_key(messages_to_dict(messages), TOOLS_SIGNATURE)
    cached = cache_get(key)
    if cached is not None:
        response = messages_from_dict(json.loads(cached))[0]
    else:
        model = get_llm(ALL_TOOLS)
        response = invoke_with_retry(model, messages)
        cache_put(key, json.dumps(messages_to_dict([response])))

    return {"messages": [response], "steps": state.get("steps", 0) + 1}


def _call_tools(state: AgentState) -> dict:
    """The tool node: run whatever the model asked for."""
    last = state["messages"][-1]
    outputs, log = [], []
    facts = dict(state.get("facts", {}))
    decision = state.get("decision", "")
    reply = state.get("reply", "")

    for call in last.tool_calls:
        name, args = call["name"], call["args"]
        tool = TOOLS_BY_NAME.get(name)

        if tool is None:
            result = {"error": f"Unknown tool '{name}'."}
        else:
            try:
                result = tool.invoke(args)
            except Exception as exc:  # noqa: BLE001 - surface errors to the model
                # Hand the failure back as a tool result rather than crashing, so
                # the agent gets a chance to correct a bad argument.
                result = {"error": f"{type(exc).__name__}: {exc}"}

        facts[name] = result
        log.append({"tool": name, "args": args, "result": result})
        outputs.append(
            ToolMessage(content=json.dumps(result, default=str),
                        tool_call_id=call["id"], name=name)
        )

        # send_reply is the terminal tool: capture its decision and stop.
        if name == "send_reply" and isinstance(result, dict) and result.get("sent"):
            decision = result["decision"]
            reply = result["message"]

    return {
        "messages": outputs,
        "facts": facts,
        "tool_log": state.get("tool_log", []) + log,
        "decision": decision,
        "reply": reply,
    }


def _nudge(state: AgentState) -> dict:
    """Remind the model to close the conversation properly.

    Smaller models often do all the right research and then answer in prose
    instead of calling send_reply, which leaves the run with no decision. One
    reminder recovers almost all of those, so it is worth the extra call.
    """
    return {
        "messages": [HumanMessage(content=(
            "You have not finished. Call the send_reply tool now with your "
            "message to the customer and a decision of exactly APPROVE, DENY, "
            "REQUEST_PHOTO, or ESCALATE. Do not reply in plain text."
        ))],
        "nudges": state.get("nudges", 0) + 1,
    }


def _route_from_agent(state: AgentState) -> str:
    """After the model speaks: run tools, nudge it, or stop."""
    if state.get("steps", 0) >= MAX_STEPS:
        return END

    last = state["messages"][-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tools"

    # Replied in prose without calling send_reply. Remind it once or twice
    # before giving up; past that it is ignoring instructions and more tries
    # just burn quota.
    if state.get("nudges", 0) < MAX_NUDGES:
        return "nudge"
    return END


def _route_from_tools(state: AgentState) -> str:
    """After tools run: stop if the conversation was closed, else keep going."""
    if state.get("decision"):
        return END
    if state.get("steps", 0) >= MAX_STEPS:
        return END
    return "agent"


def build_graph():
    """Assemble and compile the agent graph."""
    graph = StateGraph(AgentState)
    graph.add_node("agent", _call_model)
    graph.add_node("tools", _call_tools)
    graph.add_node("nudge", _nudge)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", _route_from_agent,
        {"tools": "tools", "nudge": "nudge", END: END},
    )
    graph.add_conditional_edges("tools", _route_from_tools, {"agent": "agent", END: END})
    graph.add_edge("nudge", "agent")

    return graph.compile()


def initial_state(user_message: str) -> AgentState:
    return {
        "messages": [HumanMessage(content=user_message)],
        "facts": {},
        "decision": "",
        "reply": "",
        "steps": 0,
        "nudges": 0,
        "tool_log": [],
    }


def continue_state(previous: AgentState, user_message: str) -> AgentState:
    """Carry a finished conversation forward with the customer's next message.

    A real support conversation does not end when the agent replies once -- the
    customer sends the photo that was asked for, or disputes the outcome, and the
    agent has to pick up where it left off.

    The message history and gathered facts carry over, so the agent still knows
    the order. The per-turn counters reset: `decision` must be cleared or the
    graph would end immediately, and `steps` must restart or a long conversation
    would eventually exhaust the ceiling meant to catch a single runaway turn.
    """
    return {
        "messages": list(previous["messages"]) + [HumanMessage(content=user_message)],
        "facts": dict(previous.get("facts", {})),
        "tool_log": list(previous.get("tool_log", [])),
        "decision": "",
        "reply": "",
        "steps": 0,
        "nudges": 0,
    }


# Compiled once and reused; building the graph is cheap but not free.
_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
