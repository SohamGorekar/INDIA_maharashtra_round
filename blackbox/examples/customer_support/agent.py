"""
Example customer support agent using Black Box SDK.
"""
import random
from typing import Dict, Any
from blackbox import trace, BlackBoxContext
from blackbox.storage.sqlite import SQLiteStorage
from blackbox.events.collector import set_global_collector
from blackbox.events.collector import EventCollector


# Simulated database
ORDERS_DB = {
    "ORD001": {
        "order_id": "ORD001",
        "customer": "Alice",
        "status": "delivered",
        "items": ["Widget A", "Widget B"],
        "damaged": False,
    },
    "ORD002": {
        "order_id": "ORD002",
        "customer": "Bob",
        "status": "delivered",
        "items": ["Gadget X"],
        "damaged": True,
    },
    "ORD003": {
        "order_id": "ORD003",
        "customer": "Charlie",
        "status": "shipped",
        "items": ["Tool Y"],
        "damaged": False,
    },
}

POLICIES = {
    "returns": "Items can be returned within 30 days if undamaged.",
    "damaged": "Damaged items are eligible for free replacement or full refund.",
    "final_sale": "Sale items marked 'final sale' cannot be returned.",
}


@trace(type="tool", name="get_order")
def get_order(order_id: str) -> Dict[str, Any]:
    """Retrieve order information."""
    order = ORDERS_DB.get(order_id)
    if not order:
        return {"error": "Order not found"}
    return order


@trace(type="tool", name="check_policy")
def check_policy(request_type: str, order: Dict[str, Any]) -> Dict[str, Any]:
    """Check policy eligibility."""
    if request_type == "refund":
        if order.get("damaged"):
            return {"eligible": True, "policy": POLICIES["damaged"]}
        elif order.get("status") == "delivered":
            return {"eligible": True, "policy": POLICIES["returns"]}
        else:
            return {"eligible": False, "reason": "Order not yet delivered"}
    
    return {"eligible": False, "reason": "Unknown request type"}


@trace(type="tool", name="take_action")
def take_action(action: str, order_id: str) -> Dict[str, Any]:
    """Execute the support action."""
    if action == "approve_refund":
        return {"success": True, "message": f"Refund approved for {order_id}"}
    elif action == "deny_refund":
        return {"success": True, "message": f"Refund denied for {order_id}"}
    else:
        return {"success": False, "message": "Unknown action"}


@trace(type="agent", name="supervisor")
def handle_support_request(order_id: str, request_type: str) -> Dict[str, Any]:
    """
    Main agent function to handle support requests.
    """
    # Step 1: Get order
    order = get_order(order_id)
    
    if "error" in order:
        return {"status": "error", "message": order["error"]}
    
    # Step 2: Check policy
    policy_check = check_policy(request_type, order)
    
    # Step 3: Take action based on policy
    if policy_check.get("eligible"):
        result = take_action("approve_refund", order_id)
        return {
            "status": "success",
            "decision": "APPROVED",
            "result": result,
        }
    else:
        result = take_action("deny_refund", order_id)
        return {
            "status": "success",
            "decision": "DENIED",
            "reason": policy_check.get("reason"),
            "result": result,
        }


def run_example():
    """Run example support requests."""
    # Initialize storage
    storage = SQLiteStorage("example_support.db")
    
    # Initialize collector with storage
    collector = EventCollector(storage=storage)
    set_global_collector(collector)
    
    # Example requests
    test_cases = [
        ("ORD001", "refund"),  # Should approve - delivered
        ("ORD002", "refund"),  # Should approve - damaged
        ("ORD003", "refund"),  # Should deny - not delivered yet
        ("ORD999", "refund"),  # Should error - not found
    ]
    
    print("Running customer support agent examples...\n")
    
    for order_id, request_type in test_cases:
        print(f"Processing: {order_id} - {request_type}")
        
        # Create run context
        with BlackBoxContext() as ctx:
            try:
                result = handle_support_request(order_id, request_type)
                print(f"  Result: {result}")
                print(f"  Run ID: {ctx.run_id}\n")
            except Exception as e:
                print(f"  Error: {e}\n")
    
    print(f"\nData stored in: example_support.db")
    print(f"Start API server to view traces: uvicorn blackbox.api.app:app")


if __name__ == "__main__":
    run_example()
