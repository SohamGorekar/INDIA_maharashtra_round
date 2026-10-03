"""Tests for the policy oracle.

These run before anything else exists, because every later accuracy number is
measured against `correct_decision`. If the oracle is wrong, the agent's score is
meaningless.
"""

import pytest

from support.rules.decision import (
    APPROVE,
    CANCELLATION,
    CHANGED_MIND,
    DAMAGED,
    DEFECTIVE,
    DENY,
    ESCALATE,
    EXCHANGE,
    REFUND,
    REQUEST_PHOTO,
    WRONG_SIZE,
    Order,
    Request,
    correct_decision,
)


def order(**kw):
    """An ordinary order: recent, cheap, unshipped, not final sale."""
    base = dict(
        order_id="ORD-1",
        price=1000.0,
        days_since_purchase=5,
        shipped=False,
        final_sale=False,
        item="t-shirt",
        size="M",
    )
    base.update(kw)
    return Order(**base)


def request(**kw):
    base = dict(request_type=REFUND, reason=CHANGED_MIND)
    base.update(kw)
    return Request(**base)


# --- Branch 1: cancellation ------------------------------------------------


def test_cancel_before_ship_approved():
    assert correct_decision(order(shipped=False), request(request_type=CANCELLATION)) == APPROVE


def test_cancel_after_ship_denied():
    assert correct_decision(order(shipped=True), request(request_type=CANCELLATION)) == DENY


def test_cancel_ignores_price_and_age():
    # Cancellation depends on shipping status alone -- an expensive, old,
    # final-sale order still cancels cleanly if it has not shipped.
    o = order(price=99999.0, days_since_purchase=300, final_sale=True, shipped=False)
    assert correct_decision(o, request(request_type=CANCELLATION)) == APPROVE


# --- Branch 2: damaged -----------------------------------------------------


def test_damaged_with_photo_approved():
    r = request(reason=DAMAGED, photo_provided=True)
    assert correct_decision(order(days_since_purchase=10), r) == APPROVE


def test_damaged_without_photo_requests_photo():
    r = request(reason=DAMAGED, photo_provided=False)
    assert correct_decision(order(days_since_purchase=10), r) == REQUEST_PHOTO


def test_damaged_past_45_days_denied():
    r = request(reason=DAMAGED, photo_provided=True)
    assert correct_decision(order(days_since_purchase=46), r) == DENY


def test_damaged_at_45_days_still_eligible():
    # Boundary: the window is "within 45 days", so day 45 is still inside it.
    r = request(reason=DAMAGED, photo_provided=True)
    assert correct_decision(order(days_since_purchase=45), r) == APPROVE


def test_damaged_expired_denied_even_without_photo():
    # Out-of-window beats the photo gate: do not ask for evidence we cannot use.
    r = request(reason=DAMAGED, photo_provided=False)
    assert correct_decision(order(days_since_purchase=60), r) == DENY


# --- Interacting case: damaged + high value --------------------------------


def test_damaged_expensive_with_photo_escalates():
    r = request(reason=DAMAGED, photo_provided=True)
    assert correct_decision(order(price=7000.0), r) == ESCALATE


def test_damaged_expensive_without_photo_asks_for_photo_first():
    # The photo gate sits above escalation: we collect evidence before
    # involving a manager.
    r = request(reason=DAMAGED, photo_provided=False)
    assert correct_decision(order(price=7000.0), r) == REQUEST_PHOTO


# --- Branch 3: defective / warranty ----------------------------------------


def test_defective_within_warranty_approved():
    r = request(reason=DEFECTIVE)
    assert correct_decision(order(days_since_purchase=200), r) == APPROVE


def test_defective_needs_no_photo():
    # Same order and age as the damaged case that returns REQUEST_PHOTO.
    r = request(reason=DEFECTIVE, photo_provided=False)
    assert correct_decision(order(days_since_purchase=10), r) == APPROVE


def test_defective_past_warranty_denied():
    r = request(reason=DEFECTIVE)
    assert correct_decision(order(days_since_purchase=366), r) == DENY


def test_defective_at_365_days_still_covered():
    r = request(reason=DEFECTIVE)
    assert correct_decision(order(days_since_purchase=365), r) == APPROVE


def test_defective_expensive_escalates():
    r = request(reason=DEFECTIVE)
    assert correct_decision(order(price=5001.0), r) == ESCALATE


# --- Interacting case: final sale + defect ---------------------------------


def test_final_sale_defective_still_approved():
    # The headline interaction: final-sale status never overrides a real defect.
    o = order(final_sale=True, days_since_purchase=100)
    assert correct_decision(o, request(reason=DEFECTIVE)) == APPROVE


def test_final_sale_damaged_still_covered():
    o = order(final_sale=True)
    r = request(reason=DAMAGED, photo_provided=True)
    assert correct_decision(o, r) == APPROVE


def test_final_sale_changed_mind_denied():
    # ...but a preference return on a final-sale item is denied.
    assert correct_decision(order(final_sale=True), request(reason=CHANGED_MIND)) == DENY


# --- Branch 4: preference returns ------------------------------------------


def test_changed_mind_within_window_approved():
    assert correct_decision(order(days_since_purchase=10), request()) == APPROVE


def test_changed_mind_past_30_days_denied():
    assert correct_decision(order(days_since_purchase=31), request()) == DENY


def test_changed_mind_at_30_days_approved():
    assert correct_decision(order(days_since_purchase=30), request()) == APPROVE


def test_expensive_refund_escalates():
    assert correct_decision(order(price=5001.0), request()) == ESCALATE


def test_refund_exactly_at_threshold_approved():
    # The rule is "above Rs. 5000", so 5000 itself does not escalate.
    assert correct_decision(order(price=5000.0), request()) == APPROVE


# --- Interacting case: exchange + stock ------------------------------------


def test_exchange_in_stock_approved():
    r = request(request_type=EXCHANGE, reason=WRONG_SIZE, requested_size_in_stock=True)
    assert correct_decision(order(), r) == APPROVE


def test_exchange_out_of_stock_denied():
    r = request(request_type=EXCHANGE, reason=WRONG_SIZE, requested_size_in_stock=False)
    assert correct_decision(order(), r) == DENY


def test_expensive_exchange_does_not_escalate():
    # Escalation guards money leaving the business. An even exchange does not,
    # so a costly exchange is approved where a costly refund would escalate.
    r = request(request_type=EXCHANGE, reason=WRONG_SIZE, requested_size_in_stock=True)
    assert correct_decision(order(price=9000.0), r) == APPROVE


def test_exchange_out_of_window_denied():
    r = request(request_type=EXCHANGE, reason=WRONG_SIZE, requested_size_in_stock=True)
    assert correct_decision(order(days_since_purchase=45), r) == DENY


# --- Sanity ----------------------------------------------------------------


@pytest.mark.parametrize("reason", [DAMAGED, DEFECTIVE, WRONG_SIZE, CHANGED_MIND])
@pytest.mark.parametrize("rtype", [REFUND, EXCHANGE, CANCELLATION])
def test_always_returns_a_valid_decision(reason, rtype):
    from support.rules.decision import DECISIONS

    r = request(request_type=rtype, reason=reason)
    assert correct_decision(order(), r) in DECISIONS
