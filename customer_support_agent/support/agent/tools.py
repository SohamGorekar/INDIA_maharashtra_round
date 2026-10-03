"""The agent's tools.

Each tool is a thin, honest wrapper over the store database. They return plain
JSON-serializable dicts -- never custom objects -- so the whole agent state can
be snapshotted or logged without special handling.

`take_action` is the only tool that writes anything. It honours a DRY_RUN flag so
the UI can be demonstrated without mutating the store.
"""

import json
from datetime import date, datetime
from pathlib import Path

from langchain_core.tools import tool

from support.data.db import TODAY, connect

POLICY_DIR = Path(__file__).parent.parent / "data" / "policies"

# When True, take_action reports what it *would* do without touching the store.
# The Streamlit UI exposes this as a toggle.
DRY_RUN = True


def set_dry_run(value: bool) -> None:
    global DRY_RUN
    DRY_RUN = value


def _days_since(purchase_date: str) -> int:
    y, m, d = (int(p) for p in purchase_date.split("-"))
    return (TODAY - date(y, m, d)).days


# --- 1. verify_customer ----------------------------------------------------


@tool
def verify_customer(customer_id: str) -> dict:
    """Confirm a customer account exists and return their name and email.

    Use this first to establish who you are talking to.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE customer_id = %s", (customer_id,)
        ).fetchone()
        if row is None:
            return {"found": False, "customer_id": customer_id,
                    "error": "No such customer."}
        return {"found": True, **dict(row)}


# --- 2. find_order ---------------------------------------------------------


@tool
def find_order(customer_id: str, query: str = "") -> dict:
    """Find a customer's orders, optionally narrowed by an order id or item name.

    Returns a short list of matching orders. Use this when you need to work out
    which order the customer is talking about.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT order_id, item, size, price, purchase_date, status "
            "FROM orders WHERE customer_id = %s ORDER BY purchase_date DESC",
            (customer_id,),
        ).fetchall()
        orders = [dict(r) for r in rows]

        # Narrow by anything that looks like an order id or an item name.
        if query:
            needle = query.strip().lower()
            matches = [
                o for o in orders
                if needle in o["order_id"].lower() or needle in o["item"].lower()
            ]
            if matches:
                orders = matches

        return {
            "customer_id": customer_id,
            "match_count": len(orders),
            "orders": orders[:5],
        }


# --- 3. get_order ----------------------------------------------------------


@tool
def get_order(order_id: str) -> dict:
    """Get the full record for one order.

    Returns the item, size, price, purchase date, how many days ago that was,
    whether it has shipped, and whether it was a final-sale purchase. These are
    the facts the policies are written against.
    """
    with connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,)).fetchone()
        if row is None:
            return {"found": False, "order_id": order_id, "error": "No such order."}

        order = dict(row)
        return {
            "found": True,
            "order_id": order["order_id"],
            "customer_id": order["customer_id"],
            "item": order["item"],
            "size": order["size"],
            "price": order["price"],
            "purchase_date": order["purchase_date"],
            # Pre-computed so the agent never has to do date arithmetic, which
            # language models get wrong far more often than you would expect.
            "days_since_purchase": _days_since(order["purchase_date"]),
            "shipped": bool(order["shipped"]),
            "final_sale": bool(order["final_sale"]),
            "status": order["status"],
            "today": TODAY.isoformat(),
        }


# --- 4. get_payment_history ------------------------------------------------


@tool
def get_payment_history(order_id: str) -> dict:
    """Get what was actually paid for an order.

    The refundable amount comes from here, not from the order's list price.
    Check this before issuing any refund so the amount is right.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT payment_id, amount, method, paid_on, refunded "
            "FROM payments WHERE order_id = %s",
            (order_id,),
        ).fetchall()
        payments = [dict(r) for r in rows]
        for p in payments:
            p["refunded"] = bool(p["refunded"])

        return {
            "order_id": order_id,
            "payments": payments,
            "total_paid": round(sum(p["amount"] for p in payments), 2),
            "already_refunded": any(p["refunded"] for p in payments),
        }


# --- 5. check_policy -------------------------------------------------------


@tool
def check_policy(topic: str) -> dict:
    """Look up the store's written policy on a topic.

    Valid topics include: returns, damaged, final_sale, cancellation, exchange,
    escalation, warranty. You must consult the relevant policy before deciding,
    and always before taking any action.
    """
    files = sorted(POLICY_DIR.glob("*.txt"))
    needle = topic.strip().lower().replace("-", " ").replace("_", " ")

    scored = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        # The TOPIC: line lists the phrases this policy answers to. Matching
        # against it is a simple keyword lookup -- no embeddings needed for
        # seven short documents.
        lines = text.splitlines()
        topic_line = lines[0].replace("TOPIC:", "").lower()
        keywords = [k.strip() for k in topic_line.split(",")]
        # Search the body separately from the TOPIC: header -- otherwise the
        # literal word "topic" scores a point against every single policy.
        body = "\n".join(lines[1:]).lower()

        score = 0
        for keyword in keywords:
            if keyword and (keyword in needle or needle in keyword):
                score += 2
        for word in needle.split():
            if len(word) > 3 and word in body:
                score += 1

        if score:
            scored.append((score, path.stem, text))

    if not scored:
        return {
            "topic": topic,
            "found": False,
            "available_topics": [p.stem.split("_", 1)[1] for p in files],
            "error": f"No policy matched '{topic}'.",
        }

    scored.sort(key=lambda s: -s[0])
    best_score, name, text = scored[0]
    return {
        "topic": topic,
        "found": True,
        "policy_name": name,
        "policy_text": text,
        "also_relevant": [n for _, n, _ in scored[1:3]],
    }


# --- 6. check_stock --------------------------------------------------------


@tool
def check_stock(item: str, size: str) -> dict:
    """Check whether a size of an item is currently in stock.

    You must call this before approving any exchange -- an exchange into a size
    that is unavailable cannot be fulfilled.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT quantity FROM stock WHERE item = %s AND size = %s", (item, size)
        ).fetchone()
        if row is None:
            sizes = conn.execute(
                "SELECT size FROM stock WHERE item = %s", (item,)
            ).fetchall()
            return {
                "item": item,
                "size": size,
                "in_stock": False,
                "quantity": 0,
                "known_sizes": [r["size"] for r in sizes],
                "error": "That item/size combination is not in the catalogue.",
            }
        return {
            "item": item,
            "size": size,
            "quantity": row["quantity"],
            "in_stock": row["quantity"] > 0,
        }


# --- 7. take_action --------------------------------------------------------


@tool
def take_action(action_type: str, order_id: str, amount: float = 0.0,
                details: str = "") -> dict:
    """Issue a refund, exchange, or cancellation. THIS CHANGES THE STORE.

    action_type must be one of: refund, exchange, cancellation.
    Only call this once you have checked the relevant policy and are approving
    the request. Never call it for a denied, escalated, or photo-pending case.
    """
    action_type = action_type.strip().lower()
    if action_type not in {"refund", "exchange", "cancellation"}:
        return {"success": False, "error":
                f"Invalid action_type '{action_type}'. "
                "Use refund, exchange, or cancellation."}

    with connect() as conn:
        order = conn.execute(
            "SELECT * FROM orders WHERE order_id = %s", (order_id,)
        ).fetchone()
        if order is None:
            return {"success": False, "error": f"No such order: {order_id}"}
        if order["status"] != "active":
            return {"success": False, "error":
                    f"Order {order_id} is already {order['status']}."}

        if DRY_RUN:
            return {
                "success": True,
                "dry_run": True,
                "action_type": action_type,
                "order_id": order_id,
                "amount": amount,
                "note": "DRY RUN -- nothing was changed in the store.",
            }

        new_status = {"refund": "refunded", "exchange": "exchanged",
                      "cancellation": "cancelled"}[action_type]
        conn.execute("UPDATE orders SET status = %s WHERE order_id = %s",
                     (new_status, order_id))
        if action_type in ("refund", "cancellation"):
            conn.execute("UPDATE payments SET refunded = TRUE WHERE order_id = %s",
                         (order_id,))
        conn.execute(
            "INSERT INTO actions (order_id, action_type, amount, details, created_at) "
            "VALUES (%s,%s,%s,%s,%s)",
            (order_id, action_type, amount, details, datetime.now().isoformat()),
        )
        conn.commit()

        return {
            "success": True,
            "dry_run": False,
            "action_type": action_type,
            "order_id": order_id,
            "amount": amount,
            "new_status": new_status,
        }


# --- 8. verify_action ------------------------------------------------------


@tool
def verify_action(order_id: str) -> dict:
    """Read the store back to confirm an action actually applied.

    Call this after take_action to check the order's status really changed
    before you promise the customer anything.
    """
    with connect() as conn:
        order = conn.execute(
            "SELECT status FROM orders WHERE order_id = %s", (order_id,)
        ).fetchone()
        if order is None:
            return {"order_id": order_id, "error": "No such order."}

        actions = conn.execute(
            "SELECT action_type, amount, created_at FROM actions "
            "WHERE order_id = %s ORDER BY action_id DESC LIMIT 3",
            (order_id,),
        ).fetchall()
        payments = conn.execute(
            "SELECT refunded FROM payments WHERE order_id = %s", (order_id,)
        ).fetchall()

        return {
            "order_id": order_id,
            "order_status": order["status"],
            "recorded_actions": [dict(a) for a in actions],
            "payment_refunded": any(bool(p["refunded"]) for p in payments),
            "dry_run_mode": DRY_RUN,
            "note": ("Dry-run mode is on, so no action was recorded."
                     if DRY_RUN else ""),
        }


# --- 9. send_reply ---------------------------------------------------------


@tool
def send_reply(message: str, decision: str) -> dict:
    """Send the final reply to the customer and close the conversation.

    decision must be exactly one of: APPROVE, DENY, REQUEST_PHOTO, ESCALATE.
    Call this exactly once, as your last action.
    """
    valid = {"APPROVE", "DENY", "REQUEST_PHOTO", "ESCALATE"}
    normalized = decision.strip().upper()
    if normalized not in valid:
        return {"sent": False, "error":
                f"'{decision}' is not a valid decision. Use one of {sorted(valid)}."}
    return {"sent": True, "decision": normalized, "message": message}


ALL_TOOLS = [
    verify_customer,
    find_order,
    get_order,
    get_payment_history,
    check_policy,
    check_stock,
    take_action,
    verify_action,
    send_reply,
]

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

# Stable signature of the tool set, used as part of the LLM cache key so that
# changing a tool's description invalidates cached responses.
TOOLS_SIGNATURE = json.dumps(sorted(t.name for t in ALL_TOOLS))
