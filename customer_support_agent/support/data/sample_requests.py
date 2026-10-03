"""Build realistic customer messages against the seeded store.

Each generated request carries the decision the policy oracle says is correct,
so the same objects drive both the UI's example picker and the accuracy eval.

Run with:  python -m support.data.sample_requests --n 20
"""

import argparse
import random
from dataclasses import asdict, dataclass
from datetime import date

from support.data.db import TODAY, connect, rows
from support.rules.decision import (
    CANCELLATION,
    CHANGED_MIND,
    DAMAGED,
    DEFECTIVE,
    EXCHANGE,
    REFUND,
    WRONG_SIZE,
    Order,
    Request,
    correct_decision,
)

SEED = 7

# Several phrasings per reason, so the agent is not keying off one fixed
# sentence. The {item} placeholder is filled from the order.
TEMPLATES = {
    (REFUND, DAMAGED): [
        "My {item} turned up damaged, there's a big tear on it. I'd like a refund please.",
        "The {item} I ordered arrived broken. Can I get my money back?",
        "Order {order_id} came in damaged packaging and the {item} is crushed. Refund please.",
    ],
    (REFUND, DEFECTIVE): [
        "The {item} I bought has stopped working properly. It's faulty. I want a refund.",
        "My {item} is defective, it broke on its own after normal use. Can I get a refund?",
        "Something is wrong with the {item} from order {order_id}, it's just not working. Refund?",
    ],
    (REFUND, CHANGED_MIND): [
        "I've changed my mind about the {item}. Can I return it for a refund?",
        "I don't really want the {item} anymore. I'd like to return it.",
        "Please refund order {order_id}, the {item} isn't what I expected.",
    ],
    (EXCHANGE, WRONG_SIZE): [
        "The {item} I got is the wrong size. Could I exchange it for a {size}?",
        "I ordered the wrong size {item}. Can you swap it for size {size}?",
        "Order {order_id}: the {item} doesn't fit. I'd like to exchange it for a {size}.",
    ],
    (CANCELLATION, CHANGED_MIND): [
        "I'd like to cancel order {order_id} please, I ordered it by mistake.",
        "Can you cancel my order for the {item}? I don't need it anymore.",
        "Please cancel order {order_id} before it goes out.",
    ],
}

# How often each kind of request appears. Weighted toward refunds because that
# is what a real support queue looks like.
MIX = [
    ((REFUND, DAMAGED), 0.26),
    ((REFUND, DEFECTIVE), 0.20),
    ((REFUND, CHANGED_MIND), 0.24),
    ((EXCHANGE, WRONG_SIZE), 0.18),
    ((CANCELLATION, CHANGED_MIND), 0.12),
]


@dataclass
class SampleRequest:
    """One customer message plus everything needed to grade the answer."""

    request_id: int
    customer_id: str
    order_id: str
    message: str
    request_type: str
    reason: str
    photo_provided: bool
    requested_size: str
    expected_decision: str


def _days_since(purchase_date: str) -> int:
    y, m, d = (int(p) for p in purchase_date.split("-"))
    return (TODAY - date(y, m, d)).days


def _pick_weighted(rng: random.Random) -> tuple[str, str]:
    roll = rng.random()
    cumulative = 0.0
    for key, weight in MIX:
        cumulative += weight
        if roll <= cumulative:
            return key
    return MIX[-1][0]


def generate(n: int = 50, seed: int = SEED) -> list[SampleRequest]:
    """Generate `n` customer requests against the seeded store.

    Reads the catalogue once up front rather than querying inside the loop:
    against a hosted database, a query per generated request would make this
    take seconds instead of milliseconds.
    """
    rng = random.Random(seed)

    with connect() as conn:
        orders = rows(conn, "SELECT * FROM orders")
        stock = rows(conn, "SELECT item, size, quantity FROM stock")

    sizes_by_item: dict[str, list[str]] = {}
    in_stock: dict[tuple[str, str], bool] = {}
    for row in stock:
        sizes_by_item.setdefault(row["item"], []).append(row["size"])
        in_stock[(row["item"], row["size"])] = row["quantity"] > 0

    # Cancellations only make sense on orders that could still be cancelled or
    # were only just shipped, so keep those separate from the general pool.
    unshipped = [o for o in orders if not o["shipped"]]

    out: list[SampleRequest] = []
    attempts = 0
    while len(out) < n and attempts < n * 50:
        attempts += 1
        request_type, reason = _pick_weighted(rng)

        # Cancellations: bias toward unshipped orders so both APPROVE and DENY
        # outcomes appear, rather than every cancellation being denied.
        if request_type == CANCELLATION and unshipped and rng.random() < 0.5:
            order_row = rng.choice(unshipped)
        else:
            order_row = rng.choice(orders)

        sizes = sizes_by_item.get(order_row["item"], [])
        # An exchange needs a different size to swap into; one-size items can't
        # be exchanged, so skip those rather than generate a nonsense request.
        if request_type == EXCHANGE:
            alternatives = [s for s in sizes if s != order_row["size"] and s != "ONE"]
            if not alternatives:
                continue
            requested_size = rng.choice(alternatives)
        else:
            requested_size = ""

        # Only damage claims care about photos, and customers supply one up
        # front about half the time.
        photo_provided = reason == DAMAGED and rng.random() < 0.5

        order = Order(
            order_id=order_row["order_id"],
            price=order_row["price"],
            days_since_purchase=_days_since(order_row["purchase_date"]),
            shipped=bool(order_row["shipped"]),
            final_sale=bool(order_row["final_sale"]),
            item=order_row["item"],
            size=order_row["size"] or "",
        )
        request = Request(
            request_type=request_type,
            reason=reason,
            photo_provided=photo_provided,
            requested_size=requested_size,
            requested_size_in_stock=in_stock.get(
                (order_row["item"], requested_size), False
            ),
        )

        template = rng.choice(TEMPLATES[(request_type, reason)])
        message = template.format(
            item=order_row["item"],
            order_id=order_row["order_id"],
            size=requested_size or order_row["size"] or "",
        )
        if photo_provided:
            message += " I've attached a photo of the damage."

        out.append(
            SampleRequest(
                request_id=len(out) + 1,
                customer_id=order_row["customer_id"],
                order_id=order_row["order_id"],
                message=message,
                request_type=request_type,
                reason=reason,
                photo_provided=photo_provided,
                requested_size=requested_size,
                expected_decision=correct_decision(order, request),
            )
        )

    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preview generated customer requests")
    parser.add_argument("--n", type=int, default=20)
    args = parser.parse_args()

    requests = generate(args.n)
    for r in requests:
        print(f"[{r.request_id:>3}] {r.expected_decision:<14} {r.order_id}  {r.message}")

    counts: dict[str, int] = {}
    for r in requests:
        counts[r.expected_decision] = counts.get(r.expected_decision, 0) + 1
    print("\nExpected decision mix:")
    for decision, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {decision:<14} {count:>3}  ({count / len(requests):.0%})")
