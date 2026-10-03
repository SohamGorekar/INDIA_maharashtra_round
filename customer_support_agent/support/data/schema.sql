-- The store schema, for Supabase Postgres.
--
-- Applied by `python -m support.data.seed`, which drops and recreates
-- everything. The data is generated deterministically, so there is nothing
-- precious to migrate -- reseeding is always safe and always gives the same
-- result.

DROP TABLE IF EXISTS actions   CASCADE;
DROP TABLE IF EXISTS payments  CASCADE;
DROP TABLE IF EXISTS orders    CASCADE;
DROP TABLE IF EXISTS stock     CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    customer_id   TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    -- PBKDF2 hash as "salt$hash", never the password itself.
    password_hash TEXT NOT NULL
);

CREATE TABLE orders (
    order_id      TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(customer_id),
    item          TEXT NOT NULL,
    size          TEXT,
    price         DOUBLE PRECISION NOT NULL,
    -- Stored as ISO text (yyyy-mm-dd) rather than a date type: every age
    -- comparison is against the fixed TODAY constant in Python, so a real date
    -- type would only invite accidental use of the server's clock.
    purchase_date TEXT NOT NULL,
    shipped       BOOLEAN NOT NULL,
    final_sale    BOOLEAN NOT NULL,
    status        TEXT NOT NULL   -- active | refunded | exchanged | cancelled
);

CREATE TABLE stock (
    item     TEXT NOT NULL,
    size     TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (item, size)
);

CREATE TABLE payments (
    payment_id TEXT PRIMARY KEY,
    order_id   TEXT NOT NULL REFERENCES orders(order_id),
    amount     DOUBLE PRECISION NOT NULL,
    method     TEXT NOT NULL,
    paid_on    TEXT NOT NULL,
    refunded   BOOLEAN NOT NULL DEFAULT FALSE
);

-- Written by the take_action tool, read back by verify_action.
CREATE TABLE actions (
    action_id   SERIAL PRIMARY KEY,
    order_id    TEXT NOT NULL REFERENCES orders(order_id),
    action_type TEXT NOT NULL,   -- refund | exchange | cancellation
    amount      DOUBLE PRECISION,
    details     TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_payments_order  ON payments(order_id);
CREATE INDEX idx_actions_order   ON actions(order_id);
