"""
Instrumented version of the agent graph with Black Box tracing.

This module wraps the original LangGraph nodes with Black Box instrumentation
to capture execution traces, create checkpoints, and enable replay/counterfactual
execution.
"""
import sys
from pathlib import Path
import os

# Add Black Box SDK to path
SDK_PATH = Path(__file__).resolve().parents[3] / "blackbox" / "sdk"
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

from typing import Dict, Any
import uuid
from datetime import datetime

from blackbox import trace, BlackBoxContext
from blackbox.storage.sqlite import SQLiteStorage
from blackbox.events.collector import EventCollector, set_global_collector, get_global_collector
from blackbox.checkpoint.manager import CheckpointManager
from blackbox.instrumentation.context import get_current_run_id, get_current_context
from blackbox.events.schema import RunOutcome, RunStatus
from support.blackbox_integration.streaming import broker

from support.agent.graph import (
    _call_model as original_call_model,
    _call_tools as original_call_tools,
    _nudge as original_nudge,
    _route_from_agent,
    _route_from_tools,
    build_graph as original_build_graph,
    AgentState,
    START,
    END,
)
from support.blackbox_integration.adapter import LangGraphAdapter

# Global configuration
BLACKBOX_ENABLED = os.getenv("BLACKBOX_ENABLED", "true").lower() == "true"
BLACKBOX_DB_PATH = os.getenv(
    "BLACKBOX_DB_PATH",
    str(Path(__file__).resolve().parents[2] / "customer_support_blackbox.db"),
)

# Global Black Box infrastructure
_storage = None
_collector = None
_checkpoint_manager = None
_adapter = None
_stream_callback_registered = False
_initialization_error = None


def _publish_collector_message(message):
    event = message.get("event")
    payload = {}
    if event is not None:
        payload["event"] = event
    broker.publish(message["type"], message["run_id"], **payload)


def _redact_sensitive(data):
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            lowered = str(key).lower()
            if any(secret in lowered for secret in ("password", "token", "api_key", "authorization")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive(value)
        return redacted
    if isinstance(data, list):
        return [_redact_sensitive(item) for item in data]
    return data


def initialize_blackbox():
    """Initialize Black Box SDK components."""
    global _storage, _collector, _checkpoint_manager, _adapter
    global _stream_callback_registered, _initialization_error
    
    if not BLACKBOX_ENABLED:
        return
    
    if _storage is None:
        try:
            _storage = SQLiteStorage(BLACKBOX_DB_PATH)
            _collector = EventCollector(storage=_storage)
            _collector.set_redactor(_redact_sensitive)
            if not _stream_callback_registered:
                _collector.register_callback(_publish_collector_message)
                _stream_callback_registered = True
            set_global_collector(_collector)
            _checkpoint_manager = CheckpointManager(storage=_storage)
            _adapter = LangGraphAdapter()
            _initialization_error = None
        except Exception as exc:
            _initialization_error = exc
            raise RuntimeError(f"Black Box initialization failed: {exc}") from exc


def get_initialization_error():
    return _initialization_error


def get_storage():
    """Get the Black Box storage instance."""
    initialize_blackbox()
    return _storage


def get_checkpoint_manager():
    """Get the checkpoint manager instance."""
    initialize_blackbox()
    return _checkpoint_manager


def get_adapter():
    """Get the LangGraph adapter instance."""
    initialize_blackbox()
    return _adapter


# Instrumented versions of graph nodes


@trace(type="llm", name="gemini_agent_call")
def _call_model_instrumented(state: AgentState) -> dict:
    """
    Instrumented version of _call_model.
    Captures LLM invocation with full context.
    """
    # Create checkpoint before LLM call
    if BLACKBOX_ENABLED and _checkpoint_manager:
        run_id = get_current_run_id()
        if run_id:
            adapter = get_adapter()
            serialized_state = adapter.serialize_state(state)
            
            try:
                checkpoint = _checkpoint_manager.create_checkpoint(
                    run_id=run_id,
                    event_id=f"before_llm_{state.get('steps', 0)}",
                    sequence_number=state.get('steps', 0),
                    state=serialized_state
                )
                broker.publish(
                    "checkpoint_created",
                    run_id,
                    checkpoint=checkpoint,
                )
            except Exception as e:
                print(f"Warning: Failed to create checkpoint: {e}")
    
    # Call original function
    result = original_call_model(state)
    
    return result


@trace(type="function", name="tools_execution")
def _call_tools_instrumented(state: AgentState) -> dict:
    """
    Instrumented version of _call_tools.
    Each tool call is traced separately within this function.
    """
    last = state["messages"][-1]
    outputs, log = [], []
    facts = dict(state.get("facts", {}))
    decision = state.get("decision", "")
    reply = state.get("reply", "")

    # Import tools module to access tools
    from support.agent.tools import TOOLS_BY_NAME
    import json
    from langchain_core.messages import ToolMessage

    for call in last.tool_calls:
        name, args = call["name"], call["args"]
        tool = TOOLS_BY_NAME.get(name)

        if tool is None:
            result = {"error": f"Unknown tool '{name}'."}
        else:
            # Trace individual tool call
            if BLACKBOX_ENABLED:
                tool_traced = trace(type="tool", name=name)(tool.invoke)
                try:
                    result = tool_traced(args)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
            else:
                try:
                    result = tool.invoke(args)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}

        facts[name] = result
        log.append({"tool": name, "args": args, "result": result})
        outputs.append(
            ToolMessage(content=json.dumps(result, default=str),
                        tool_call_id=call["id"], name=name)
        )

        # send_reply is terminal
        if name == "send_reply" and isinstance(result, dict) and result.get("sent"):
            decision = result["decision"]
            reply = result["message"]
    
    # Create checkpoint after tools
    if BLACKBOX_ENABLED and _checkpoint_manager and outputs:
        run_id = get_current_run_id()
        if run_id:
            adapter = get_adapter()
            # Update state with new facts
            updated_state = dict(state)
            updated_state["messages"] = list(state.get("messages", [])) + outputs
            updated_state["facts"] = facts
            updated_state["tool_log"] = state.get("tool_log", []) + log
            if decision:
                updated_state["decision"] = decision
                updated_state["reply"] = reply
            
            serialized_state = adapter.serialize_state(updated_state)
            
            try:
                checkpoint = _checkpoint_manager.create_checkpoint(
                    run_id=run_id,
                    event_id=f"after_tools_{state.get('steps', 0)}",
                    sequence_number=state.get('steps', 0) + 1,
                    state=serialized_state
                )
                broker.publish(
                    "checkpoint_created",
                    run_id,
                    checkpoint=checkpoint,
                )
            except Exception as e:
                print(f"Warning: Failed to create checkpoint: {e}")

    return {
        "messages": outputs,
        "facts": facts,
        "tool_log": state.get("tool_log", []) + log,
        "decision": decision,
        "reply": reply,
    }


@trace(type="llm", name="gemini_nudge_call")
def _nudge_instrumented(state: AgentState) -> dict:
    """Instrumented version of _nudge."""
    return original_nudge(state)


def build_instrumented_graph():
    """Build the LangGraph graph with Black Box instrumentation."""
    from langgraph.graph import StateGraph
    
    graph = StateGraph(AgentState)
    
    # Use instrumented versions if Black Box is enabled
    if BLACKBOX_ENABLED:
        graph.add_node("agent", _call_model_instrumented)
        graph.add_node("tools", _call_tools_instrumented)
        graph.add_node("nudge", _nudge_instrumented)
    else:
        # Use original nodes
        graph.add_node("agent", original_call_model)
        graph.add_node("tools", original_call_tools)
        graph.add_node("nudge", original_nudge)

    # Routing remains the same
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", _route_from_agent,
        {"tools": "tools", "nudge": "nudge", END: END},
    )
    graph.add_conditional_edges("tools", _route_from_tools, {"agent": "agent", END: END})
    graph.add_edge("nudge", "agent")

    return graph.compile()


# Compiled graph instance
_INSTRUMENTED_GRAPH = None


def get_instrumented_graph():
    """Get the compiled instrumented graph."""
    global _INSTRUMENTED_GRAPH
    if _INSTRUMENTED_GRAPH is None:
        initialize_blackbox()
        _INSTRUMENTED_GRAPH = build_instrumented_graph()
    return _INSTRUMENTED_GRAPH


def run_with_blackbox(
    state: AgentState,
    expected_decision: str = None,
    metadata: Dict[str, Any] = None,
    run_id: str = None,
) -> tuple:
    """
    Run the agent with Black Box tracing.
    
    Args:
        state: Initial agent state
        expected_decision: Expected decision for evaluation
        metadata: Additional metadata to attach to the run
        
    Returns:
        Tuple of (final_state, run_id)
    """
    if not BLACKBOX_ENABLED:
        # Run without tracing
        graph = get_instrumented_graph()
        final_state = graph.invoke(state)
        return final_state, None
    
    # Initialize Black Box
    initialize_blackbox()
    adapter = get_adapter()
    storage = get_storage()
    
    # Create Black Box run context
    run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
    
    # Extract task input from state
    task_input = {}
    if state.get("messages"):
        first_msg = state["messages"][0]
        message = str(first_msg.content) if hasattr(first_msg, "content") else str(first_msg)
        task_input = {
            "message_preview": message[:240],
            "message_length": len(message),
            "type": "customer_support_request"
        }
    
    # Create run record
    from blackbox.events.schema import Run
    run = Run(
        run_id=run_id,
        task_input=task_input,
        status=RunStatus.RUNNING,
        outcome=RunOutcome.UNKNOWN,
        started_at=datetime.utcnow(),
        metadata=metadata or {}
    )
    
    # Store initial run
    storage.store_run(run)
    broker.publish("run_started", run_id, run=run)
    
    # Execute with context
    with BlackBoxContext(run_id=run_id):
        
        try:
            # Run the instrumented graph
            graph = get_instrumented_graph()
            final_state = graph.invoke(state)
            
            # Determine outcome
            decision = final_state.get("decision", "")
            outcome = adapter.map_decision_to_outcome(decision, expected_decision)
            
            # Update run
            finished_at = datetime.utcnow()
            storage.update_run(run_id, {
                "status": RunStatus.COMPLETED,
                "outcome": outcome,
                "finished_at": finished_at,
                "duration_ms": (finished_at - run.started_at).total_seconds() * 1000,
                "metadata": {
                    **(metadata or {}),
                    "final_decision": decision,
                },
            })
            completed_run = storage.get_run(run_id)
            broker.publish(
                "run_completed",
                run_id,
                run=completed_run,
                final_decision=decision,
            )
            
            return final_state, run_id
            
        except Exception as exc:
            # Update run with error
            finished_at = datetime.utcnow()
            storage.update_run(run_id, {
                "status": RunStatus.FAILED,
                "outcome": RunOutcome.FAILURE,
                "finished_at": finished_at,
                "duration_ms": (finished_at - run.started_at).total_seconds() * 1000,
                "metadata": {
                    **(metadata or {}),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            })
            failed_run = storage.get_run(run_id)
            broker.publish(
                "run_failed",
                run_id,
                run=failed_run,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
