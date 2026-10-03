"""FastAPI backend.

    uvicorn support.api:app --reload --port 8000

Endpoints are deliberately thin -- they expose the store and the agent and do no
business logic of their own. All reasoning lives in the agent; all policy lives
in support/rules/decision.py.
"""

import secrets
import uuid
from dataclasses import asdict
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from support.agent.graph import continue_state, get_graph, initial_state
from support.agent.llm import MODEL_NAME, MissingAPIKey, cache_stats, clear_cache
from support.agent.prompts import build_chat_opening, build_user_message
from support.agent.tools import set_dry_run
from support.data.auth import verify_password
from support.data.db import TODAY, backend, connect, one, rows
from support.data.sample_requests import generate

STORE_NAME = "Durva Shopping"

app = FastAPI(title=f"{STORE_NAME} support")

# The Vite dev server runs on a different port, so the browser needs permission
# to call this one.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- sessions --------------------------------------------------------------
#
# Kept in memory on purpose. Restarting the server signs everyone out and clears
# every conversation, and nothing a customer typed is written to disk. A real
# deployment would use Redis or signed cookies.

LOGINS: dict[str, str] = {}          # token      -> customer_id
CONVERSATIONS: dict[str, dict] = {}  # session_id -> agent state

# Decisions that settle a case. The customer can still write afterwards.
RESOLVING = {"APPROVE", "DENY", "ESCALATE"}

PHOTO_ATTACHED = "[The customer has attached a photograph of the damage.]"


def _blackbox_enabled() -> bool:
    return os.getenv("BLACKBOX_ENABLED", "true").lower() == "true"


def _run_agent_with_blackbox(state, metadata: dict, expected_decision: str = ""):
    if not _blackbox_enabled():
        final_state = get_graph().invoke(state)
        return final_state, None

    from support.blackbox_integration.instrumented_graph import run_with_blackbox

    return run_with_blackbox(
        state,
        expected_decision=expected_decision or None,
        metadata=metadata,
    )


def current_customer(authorization: str = Header(default="")) -> dict:
    """Resolve the signed-in customer from the Authorization header."""
    token = authorization.removeprefix("Bearer ").strip()
    customer_id = LOGINS.get(token)
    if not customer_id:
        raise HTTPException(401, "Please sign in again.")

    with connect() as conn:
        customer = one(
            conn,
            "SELECT customer_id, name, email FROM customers WHERE customer_id = %s",
            (customer_id,),
        )
    if customer is None:
        raise HTTPException(401, "That account no longer exists.")
    return customer


# --- health ----------------------------------------------------------------


@app.get("/api/health")
def health():
    try:
        with connect() as conn:
            customers = one(conn, "SELECT COUNT(*) AS n FROM customers")["n"]
        database = True
    except Exception:  # noqa: BLE001 - health reports problems, never raises
        customers, database = 0, False

    return {
        "ok": True,
        "store": STORE_NAME,
        "model": MODEL_NAME,
        "today": TODAY.isoformat(),
        "database": database,
        "backend": backend(),
        "customers": customers,
        "cache": cache_stats(),
    }


# --- sign in ---------------------------------------------------------------


class Credentials(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(credentials: Credentials):
    """Sign in. There is no sign-up -- accounts come from the seeded store."""
    with connect() as conn:
        customer = one(
            conn,
            "SELECT customer_id, name, email, password_hash FROM customers "
            "WHERE LOWER(email) = LOWER(%s)",
            (credentials.email.strip(),),
        )

    # The same message for a wrong email and a wrong password, so the response
    # does not reveal which addresses have accounts.
    if customer is None or not verify_password(
        credentials.password, customer["password_hash"]
    ):
        raise HTTPException(401, "That email and password do not match.")

    token = secrets.token_urlsafe(32)
    LOGINS[token] = customer["customer_id"]
    return {
        "token": token,
        "customer": {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "email": customer["email"],
        },
    }


@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    LOGINS.pop(authorization.removeprefix("Bearer ").strip(), None)
    return {"ok": True}


@app.get("/api/me")
def me(customer: dict = Depends(current_customer)):
    return customer


# --- orders ----------------------------------------------------------------


@app.get("/api/orders")
def my_orders(customer: dict = Depends(current_customer)):
    """Every order belonging to the signed-in customer, newest first."""
    with connect() as conn:
        orders = rows(
            conn,
            "SELECT o.order_id, o.item, o.size, o.price, o.purchase_date, "
            "       o.shipped, o.final_sale, o.status, p.method "
            "FROM orders o LEFT JOIN payments p ON p.order_id = o.order_id "
            "WHERE o.customer_id = %s "
            "ORDER BY o.purchase_date DESC",
            (customer["customer_id"],),
        )

    for order in orders:
        order["shipped"] = bool(order["shipped"])
        order["final_sale"] = bool(order["final_sale"])
    return orders


@app.get("/api/orders/{order_id}")
def order_detail(order_id: str, customer: dict = Depends(current_customer)):
    with connect() as conn:
        order = one(
            conn,
            "SELECT * FROM orders WHERE order_id = %s AND customer_id = %s",
            (order_id, customer["customer_id"]),
        )
    # The same response whether it does not exist or belongs to someone else.
    if order is None:
        raise HTTPException(404, "Order not found.")
    order["shipped"] = bool(order["shipped"])
    order["final_sale"] = bool(order["final_sale"])
    return order


# --- customer chat ---------------------------------------------------------


class ChatMessage(BaseModel):
    session_id: str = ""   # blank starts a new conversation
    order_id: str = ""     # which order the conversation is about
    message: str = ""
    photo_attached: bool = False


@app.post("/api/chat")
def chat(payload: ChatMessage, customer: dict = Depends(current_customer)):
    """One turn of a support conversation about one order."""
    # A customer conversation never writes to the store. Approvals are
    # simulated so the demo data survives being demonstrated.
    set_dry_run(True)

    text = payload.message.strip()
    if payload.photo_attached:
        # The agent cannot see images, so an attachment arrives as a stated
        # fact in the transcript rather than as an image.
        text = f"{text}\n\n{PHOTO_ATTACHED}" if text else PHOTO_ATTACHED
    if not text:
        raise HTTPException(400, "Message is empty.")

    session_id = payload.session_id
    previous = CONVERSATIONS.get(session_id)

    if previous is None:
        # Starting a conversation. Confirming the order belongs to this customer
        # also hands the agent the order details, so it never has to guess which
        # order is meant -- the customer opened the chat from that order.
        order = order_detail(payload.order_id, customer) if payload.order_id else None
        state = initial_state(
            build_chat_opening(
                customer_id=customer["customer_id"],
                name=customer["name"],
                message=text,
                order=order,
            )
        )
        session_id = uuid.uuid4().hex
    else:
        if previous.get("_customer_id") != customer["customer_id"]:
            raise HTTPException(403, "That conversation belongs to someone else.")
        state = continue_state(previous, text)

    metadata = {
        "source": "customer_chat",
        "customer_id": customer["customer_id"],
        "order_id": payload.order_id,
        "conversation_session_id": session_id,
        "request_type": "customer_chat",
        "photo_attached": payload.photo_attached,
        "dry_run": True,
    }

    try:
        state, blackbox_run_id = _run_agent_with_blackbox(state, metadata)
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc

    state["_customer_id"] = customer["customer_id"]
    CONVERSATIONS[session_id] = state

    decision = state.get("decision", "")
    reply = state.get("reply", "")
    if not reply:
        # The agent ran out of turns without closing properly. Say something
        # human rather than showing the customer an empty bubble.
        reply = ("I'm sorry, I'm having trouble with that right now. "
                 "Could you try saying it a different way?")

    return {
        "session_id": session_id,
        "blackbox_run_id": blackbox_run_id,
        "reply": reply,
        # The customer UI ignores these; /debug uses them.
        "decision": decision,
        "resolved": decision in RESOLVING,
        "tool_log": state.get("tool_log", []),
    }


@app.delete("/api/chat/{session_id}")
def end_chat(session_id: str, customer: dict = Depends(current_customer)):
    """Forget a conversation, so the customer can start a fresh one."""
    existing = CONVERSATIONS.get(session_id)
    if existing and existing.get("_customer_id") == customer["customer_id"]:
        CONVERSATIONS.pop(session_id, None)
    return {"ended": True}


# --- engineering views (the /debug page) -----------------------------------


class RunRequest(BaseModel):
    customer_id: str
    message: str
    request_type: str = "refund"
    requested_size: str = ""
    photo_provided: bool = False
    order_id: str = ""
    expected_decision: str = ""
    dry_run: bool = True


class _Req:
    """Adapts the API payload to what build_user_message expects."""

    def __init__(self, payload: RunRequest):
        self.customer_id = payload.customer_id
        self.message = payload.message
        self.request_type = payload.request_type
        self.requested_size = payload.requested_size
        self.photo_provided = payload.photo_provided
        self.order_id = payload.order_id
        self.expected_decision = payload.expected_decision


@app.get("/api/samples")
def samples(n: int = 40):
    """Generated test requests, each with the decision policy requires."""
    return [asdict(s) for s in generate(n)]


@app.get("/api/customers")
def customers():
    with connect() as conn:
        return rows(
            conn,
            "SELECT customer_id, name, email FROM customers ORDER BY customer_id",
        )


@app.post("/api/run")
def run(payload: RunRequest):
    """Run one request through the agent and return the whole trace."""
    set_dry_run(payload.dry_run)
    
    try:
        state, run_id = _run_agent_with_blackbox(
            initial_state(build_user_message(_Req(payload))),
            metadata={
                "source": "debug_run",
                "customer_id": payload.customer_id,
                "order_id": payload.order_id,
                "request_type": payload.request_type,
                "photo_attached": payload.photo_provided,
                "dry_run": payload.dry_run,
            },
            expected_decision=payload.expected_decision,
        )
    except MissingAPIKey as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"{type(exc).__name__}: {exc}") from exc

    decision = state.get("decision", "")
    expected = payload.expected_decision
    return {
        "decision": decision,
        "reply": state.get("reply", ""),
        "steps": state.get("steps", 0),
        "tool_log": state.get("tool_log", []),
        "dry_run": payload.dry_run,
        "expected_decision": expected or None,
        "correct": (decision == expected) if expected else None,
        "blackbox_run_id": run_id,
    }


@app.delete("/api/cache")
def delete_cache():
    clear_cache()
    return {"cleared": True}


# --- Black Box Integration -------------------------------------------------
# Import and include Black Box routes if available
try:
    from support.blackbox_integration.api_routes import router as blackbox_router
    app.include_router(blackbox_router)
except ImportError as exc:
    raise RuntimeError(
        "Black Box dependencies are missing. Install customer_support_agent/requirements.txt."
    ) from exc
