import sys
from pathlib import Path
from datetime import datetime

SDK_PATH = Path(__file__).resolve().parents[3] / "blackbox" / "sdk"
sys.path.insert(0, str(SDK_PATH))

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from blackbox import BlackBoxContext, trace
from blackbox.events.collector import EventCollector, set_global_collector
from blackbox.events.schema import ComponentType, Run, RunOutcome, RunStatus
from blackbox.storage.sqlite import SQLiteStorage
from support.api import CONVERSATIONS, LOGINS, app
from support.blackbox_integration.streaming import broker


def test_blackbox_routes_are_registered():
    paths = app.openapi()["paths"]

    assert "/api/blackbox/health" in paths
    assert "/api/blackbox/runs/{run_id}/trace" in paths
    assert "/api/blackbox/runs/{run_id}/stream" in paths
    assert "/api/blackbox/stream/latest" in paths
    assert "/api/blackbox/runs/{run_id}/replay" in paths
    assert "/api/blackbox/runs/{run_id}/counterfactual" in paths


def test_trace_persists_tool_component_type(tmp_path):
    storage = SQLiteStorage(str(tmp_path / "trace.db"))
    set_global_collector(EventCollector(storage=storage))
    run = Run(
        run_id="run_test",
        task_input={"message": "test"},
        status=RunStatus.RUNNING,
        outcome=RunOutcome.UNKNOWN,
        started_at=datetime.utcnow(),
    )
    storage.store_run(run)

    @trace(type="tool", name="test_tool")
    def test_tool(value):
        return {"value": value}

    with BlackBoxContext(run_id=run.run_id):
        test_tool("ok")

    events = storage.get_events_for_run(run.run_id)
    storage.close()

    assert len(events) == 1
    assert events[0].component_type == ComponentType.TOOL


def _tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _reset_blackbox(monkeypatch, tmp_path):
    from support.blackbox_integration import instrumented_graph

    db_path = tmp_path / "chat_blackbox.db"
    monkeypatch.setenv("BLACKBOX_ENABLED", "true")
    monkeypatch.setenv("BLACKBOX_DB_PATH", str(db_path))
    monkeypatch.setattr(instrumented_graph, "BLACKBOX_ENABLED", True)
    monkeypatch.setattr(instrumented_graph, "BLACKBOX_DB_PATH", str(db_path))
    monkeypatch.setattr(instrumented_graph, "_storage", None)
    monkeypatch.setattr(instrumented_graph, "_collector", None)
    monkeypatch.setattr(instrumented_graph, "_checkpoint_manager", None)
    monkeypatch.setattr(instrumented_graph, "_adapter", None)
    monkeypatch.setattr(instrumented_graph, "_INSTRUMENTED_GRAPH", None)
    monkeypatch.setattr(instrumented_graph, "_stream_callback_registered", False)
    return instrumented_graph


def test_customer_chat_creates_blackbox_run(monkeypatch, tmp_path):
    instrumented_graph = _reset_blackbox(monkeypatch, tmp_path)
    from support.agent import graph as graph_module

    script = [
        _tool_call("get_order", {"order_id": "ORD-0002"}, "a"),
        _tool_call(
            "send_reply",
            {"message": "I can help with that.", "decision": "APPROVE"},
            "b",
        ),
    ]

    class ScriptedModel:
        def invoke(self, _messages):
            return script.pop(0)

    model = ScriptedModel()
    monkeypatch.setattr(graph_module, "get_llm", lambda tools=None: model)
    monkeypatch.setattr(graph_module, "invoke_with_retry", lambda m, msgs: m.invoke(msgs))
    monkeypatch.setattr(graph_module, "cache_get", lambda key: None)
    monkeypatch.setattr(graph_module, "cache_put", lambda key, value: None)

    LOGINS.clear()
    CONVERSATIONS.clear()
    client = TestClient(app)
    login = client.post(
        "/api/login",
        json={"email": "soham.gorekar@example.com", "password": "User@123"},
    )
    assert login.status_code == 200
    token = login.json()["token"]

    response = client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "session_id": "",
            "order_id": "ORD-0002",
            "message": "The t-shirt arrived damaged.",
            "photo_attached": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["blackbox_run_id"].startswith("run_")
    assert body["reply"] == "I can help with that."

    storage = instrumented_graph.get_storage()
    run = storage.get_run(body["blackbox_run_id"])
    events = storage.get_events_for_run(body["blackbox_run_id"])
    checkpoints = storage.get_checkpoints_for_run(body["blackbox_run_id"])

    assert run.status == RunStatus.COMPLETED
    assert run.metadata["source"] == "customer_chat"
    assert run.metadata["customer_id"] == "CUST-0001"
    assert run.metadata["order_id"] == "ORD-0002"
    assert run.metadata["conversation_session_id"] == body["session_id"]
    assert run.metadata["photo_attached"] is True
    assert run.metadata["dry_run"] is True
    assert run.metadata["final_decision"] == "APPROVE"
    assert run.event_count == len(events)
    assert {event.component_type for event in events} >= {
        ComponentType.LLM,
        ComponentType.TOOL,
        ComponentType.FUNCTION,
    }
    assert checkpoints

    stream = client.get(f"/api/blackbox/runs/{body['blackbox_run_id']}/stream")
    assert stream.status_code == 200
    assert "event: run_started" in stream.text
    assert "event: event_completed" in stream.text
    assert "event: checkpoint_created" in stream.text
    assert "event: run_completed" in stream.text


def test_stream_subscribers_are_cleaned_up():
    q = broker.subscribe("run_cleanup")
    assert broker.subscriber_count("run_cleanup") == 1
    broker.unsubscribe(q, "run_cleanup")
    assert broker.subscriber_count("run_cleanup") == 0
