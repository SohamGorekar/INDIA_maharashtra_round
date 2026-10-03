"""Fill the store with the demo accounts and their orders.

Four real accounts, each with a spread of orders chosen to exercise every branch
of the store's policy -- something cancellable, something past its return window,
something final-sale, something expensive enough to need a manager, and so on.
That way any account you sign into has an interesting conversation available.

Everything is deterministic: the same orders, prices and dates every run.

    python -m support.data.seed            # fill Supabase (uses DATABASE_URL)
    python -m support.data.seed --local    # fill the local SQLite file instead

Creates the tables from schema.sql first, dropping any that exist.
"""

import argparse
import os
import random
from datetime import timedelta

from support.data.auth import hash_password
from support.data.db import TODAY, backend, connect, create_schema, one

SEED = 42

# Every demo account uses this password.
DEMO_PASSWORD = "User@123"

CUSTOMERS = [
    ("CUST-0001", "Soham Chetan Gorekar", "soham.gorekar@example.com"),
    ("CUST-0002", "Durva Amol Waykole", "durva.waykole@example.com"),
    ("CUST-0003", "Zeel Yashpalsinh Girase", "zeel.girase@example.com"),
    ("CUST-0004", "Aditya Nirajkumar Singh", "aditya.singh@example.com"),
]

# The catalogue. Sizes of "ONE" mean the item has no size variants, so it cannot
# be exchanged for a different size.
CATALOG = {
    "cotton t-shirt": (["S", "M", "L", "XL"], 899),
    "running shoes": (["6", "7", "8", "9", "10"], 4499),
    "denim jacket": (["S", "M", "L", "XL"], 3299),
    "silk saree": (["ONE"], 7999),
    "wireless earbuds": (["ONE"], 6499),
    "leather wallet": (["ONE"], 1299),
    "yoga pants": (["S", "M", "L"], 1599),
    "winter coat": (["S", "M", "L", "XL"], 8999),
    "cricket bat": (["ONE"], 5499),
    "backpack": (["ONE"], 2199),
    "cotton kurta": (["S", "M", "L", "XL"], 1899),
    "bluetooth speaker": (["ONE"], 3799),
}

# Stock. A few sizes are deliberately unavailable so exchange requests can
# genuinely be refused.
OUT_OF_STOCK = {
    ("cotton t-shirt", "S"),
    ("running shoes", "10"),
    ("denim jacket", "XL"),
    ("yoga pants", "L"),
    ("cotton kurta", "S"),
}

# The order template each account gets. Ages are chosen to sit either side of
# every policy boundary (30 / 45 / 365 days), so each account can demonstrate
# the full range of outcomes.
#
#   (item, size, days ago, shipped, final sale, what it demonstrates)
ORDER_PLAN = [
    ("wireless earbuds", "ONE", 2, False, False, "not shipped yet - cancellable"),
    ("cotton t-shirt", "M", 8, True, False, "inside the 30-day return window"),
    ("winter coat", "L", 14, True, False, "over Rs.5000 - a refund needs a manager"),
    ("running shoes", "9", 22, True, False, "exchangeable, replacement in stock"),
    ("yoga pants", "M", 26, True, False, "exchange to L would be out of stock"),
    ("leather wallet", "ONE", 38, True, False, "past returns, still inside damage window"),
    ("silk saree", "ONE", 41, True, True, "final sale - but damage still covered"),
    ("backpack", "ONE", 52, True, False, "past the damage window, warranty only"),
    ("bluetooth speaker", "ONE", 120, True, False, "defect claim, inside warranty"),
    ("cricket bat", "ONE", 400, True, False, "past everything - nothing applies"),
    ("denim jacket", "M", 19, True, True, "final sale, recent"),
    ("cotton kurta", "L", 31, True, False, "one day past the return window"),
]

PAYMENT_METHODS = ["upi", "credit_card", "debit_card", "netbanking"]


def _build_rows():
    """Generate every row deterministically."""
    rng = random.Random(SEED)
    password_hash = hash_password(DEMO_PASSWORD, salt="demosalt0123456789abcdef")

    customers = [(cid, name, email, password_hash) for cid, name, email in CUSTOMERS]

    stock = []
    for item, (sizes, _) in CATALOG.items():
        for size in sizes:
            quantity = 0 if (item, size) in OUT_OF_STOCK else rng.randint(3, 40)
            stock.append((item, size, quantity))

    orders, payments = [], []
    counter = 0
    for customer_index, (cid, _, _) in enumerate(CUSTOMERS):
        for item, size, days, shipped, final_sale, _note in ORDER_PLAN:
            counter += 1
            oid = f"ORD-{counter:04d}"

            # Nudge prices per customer so the accounts are not identical, while
            # keeping each order on the same side of the Rs.5000 threshold.
            base = CATALOG[item][1]
            price = round(base * (1 + 0.04 * customer_index), 2)

            purchase_date = (TODAY - timedelta(days=days)).isoformat()
            orders.append((oid, cid, item, size, price, purchase_date,
                           shipped, final_sale, "active"))
            payments.append((f"PAY-{counter:04d}", oid, price,
                             rng.choice(PAYMENT_METHODS), purchase_date, False))

    return customers, stock, orders, payments


def seed_database() -> dict:
    """Create the tables and fill them. Returns a summary."""
    # Recreating is always safe: the data is generated, never collected, so
    # there is nothing to preserve and nothing to migrate.
    create_schema()

    customers, stock, orders, payments = _build_rows()

    with connect() as conn:
        conn.executemany(
            "INSERT INTO customers (customer_id, name, email, password_hash) "
            "VALUES (%s,%s,%s,%s)",
            customers,
        )
        conn.executemany(
            "INSERT INTO stock (item, size, quantity) VALUES (%s,%s,%s)", stock
        )
        conn.executemany(
            "INSERT INTO orders (order_id, customer_id, item, size, price, "
            "purchase_date, shipped, final_sale, status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            orders,
        )
        conn.executemany(
            "INSERT INTO payments (payment_id, order_id, amount, method, "
            "paid_on, refunded) VALUES (%s,%s,%s,%s,%s,%s)",
            payments,
        )

        counts = {
            t: one(conn, f"SELECT COUNT(*) AS n FROM {t}")["n"]
            for t in ("customers", "orders", "payments", "stock")
        }

    return {
        "backend": backend(),
        **counts,
        "orders_each": len(ORDER_PLAN),
        "out_of_stock": len(OUT_OF_STOCK),
        "today": TODAY.isoformat(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fill the store with demo data")
    parser.add_argument("--local", action="store_true",
                        help="use the local SQLite file instead of Postgres")
    args = parser.parse_args()

    if args.local:
        # db.py checks this each time it connects, so setting it here is enough.
        os.environ["LOCAL_SQLITE"] = "1"

    info = seed_database()
    print("Store filled\n")
    for key, value in info.items():
        print(f"  {key:<14} {value}")

    print(f"\nSign in with any of these, password {DEMO_PASSWORD!r}:")
    for _, name, email in CUSTOMERS:
        print(f"  {email:<30} {name}")
