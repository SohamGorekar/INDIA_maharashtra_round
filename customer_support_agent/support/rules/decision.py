"""The store's policy, expressed as a pure function.

This is the ANSWER KEY. The agent never calls it -- it exists so we can measure
whether the agent reached the right conclusion on its own. Keeping it pure (no
database, no I/O, no randomness) means a given order + request always yields the
same verdict, which is what makes it usable as a test oracle.

The precedence ladder below is deliberate and order-sensitive. Read it top to
bottom: the first branch that matches wins. In particular, damage and defect
claims are evaluated BEFORE the final-sale check, which is how the policy
"final-sale status never overrides a genuine defect" is enforced.
"""

from dataclasses import dataclass

# --- Decisions -------------------------------------------------------------
# Every request resolves to exactly one of these four outcomes.
APPROVE = "APPROVE"
DENY = "DENY"
REQUEST_PHOTO = "REQUEST_PHOTO"
ESCALATE = "ESCALATE"

DECISIONS = (APPROVE, DENY, REQUEST_PHOTO, ESCALATE)

# --- Policy constants ------------------------------------------------------
RETURN_WINDOW_DAYS = 30
DAMAGE_WINDOW_DAYS = 45
WARRANTY_WINDOW_DAYS = 365
ESCALATION_THRESHOLD = 5000  # rupees; refunds ABOVE this need a manager

# Request types
REFUND = "refund"
EXCHANGE = "exchange"
CANCELLATION = "cancellation"

# Reasons a customer can give
DAMAGED = "damaged"
DEFECTIVE = "defective"
WRONG_SIZE = "wrong_size"
CHANGED_MIND = "changed_mind"


@dataclass
class Order:
    """The facts about an order that the policy actually depends on."""

    order_id: str
    price: float
    days_since_purchase: int
    shipped: bool
    final_sale: bool
    item: str = ""
    size: str = ""


@dataclass
class Request:
    """What the customer is asking for."""

    request_type: str  # refund | exchange | cancellation
    reason: str  # damaged | defective | wrong_size | changed_mind
    photo_provided: bool = False
    requested_size: str = ""  # only meaningful for exchanges
    requested_size_in_stock: bool = False


def correct_decision(order: Order, request: Request) -> str:
    """Return the decision the store's policy requires for this request.

    Branches are evaluated in order; the first match wins.
    """

    # --- 1. Cancellations ---------------------------------------------------
    # Cancellation is decided purely by shipping status. Nothing else matters:
    # not the price, not the age of the order, not final-sale status.
    if request.request_type == CANCELLATION:
        return DENY if order.shipped else APPROVE

    # --- 2. Damaged goods ---------------------------------------------------
    # Checked before final-sale, so a damaged final-sale item is still covered.
    if request.reason == DAMAGED:
        if order.days_since_purchase > DAMAGE_WINDOW_DAYS:
            return DENY
        # The photo gate sits ABOVE the escalation check: we will not escalate a
        # claim to a manager until we have the evidence that supports it.
        if not request.photo_provided:
            return REQUEST_PHOTO
        if order.price > ESCALATION_THRESHOLD:
            return ESCALATE
        return APPROVE

    # --- 3. Defective items (warranty) -------------------------------------
    # Also checked before final-sale. Unlike damage, no photo is required.
    if request.reason == DEFECTIVE:
        if order.days_since_purchase > WARRANTY_WINDOW_DAYS:
            return DENY
        if order.price > ESCALATION_THRESHOLD:
            return ESCALATE
        return APPROVE

    # --- 4. Everything else (wrong size, changed mind, ...) -----------------
    # These are preference-based returns, so the ordinary restrictions apply.
    if order.final_sale:
        return DENY
    if order.days_since_purchase > RETURN_WINDOW_DAYS:
        return DENY
    if request.request_type == EXCHANGE and not request.requested_size_in_stock:
        return DENY
    # Only refunds move money, so only refunds can trip the escalation
    # threshold. An exchange of equal value does not need a manager.
    if request.request_type == REFUND and order.price > ESCALATION_THRESHOLD:
        return ESCALATE
    return APPROVE
