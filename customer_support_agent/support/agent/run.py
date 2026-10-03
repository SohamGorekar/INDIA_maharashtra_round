"""Run a single customer request through the agent, from the terminal.

    python -m support.agent.run --request-id 1 --verbose
    python -m support.agent.run --message "my order ORD-0045 arrived damaged" \
        --customer CUST-0012
"""

import argparse
import json
from dataclasses import dataclass

from support.agent.graph import get_graph, initial_state
from support.agent.prompts import build_user_message
from support.agent.tools import set_dry_run
from support.data.sample_requests import generate


@dataclass
class AdHocRequest:
    """A hand-typed request, shaped like a SampleRequest but ungraded."""

    customer_id: str
    message: str
    request_type: str = "refund"
    requested_size: str = ""
    photo_provided: bool = False
    order_id: str = ""
    expected_decision: str = ""


def run_request(request, dry_run: bool = True) -> dict:
    """Run one request end to end and return the final state."""
    set_dry_run(dry_run)
    graph = get_graph()
    return graph.invoke(initial_state(build_user_message(request)))


def main():
    parser = argparse.ArgumentParser(description="Run one support request")
    parser.add_argument("--request-id", type=int, help="index into the sample set (1-based)")
    parser.add_argument("--message", help="a free-form customer message")
    parser.add_argument("--customer", default="CUST-0001", help="customer id for --message")
    parser.add_argument("--photo", action="store_true", help="customer attached a photo")
    parser.add_argument("--verbose", action="store_true", help="print every tool call")
    parser.add_argument("--live", action="store_true",
                        help="actually write to the store (default is dry run)")
    args = parser.parse_args()

    if args.message:
        request = AdHocRequest(customer_id=args.customer, message=args.message,
                               photo_provided=args.photo)
    else:
        requests = generate(max(args.request_id or 1, 1))
        request = requests[(args.request_id or 1) - 1]

    print(f"Customer : {request.customer_id}")
    print(f"Message  : {request.message}")
    if request.expected_decision:
        print(f"Expected : {request.expected_decision}")
    print("-" * 70)

    state = run_request(request, dry_run=not args.live)

    if args.verbose:
        for i, entry in enumerate(state["tool_log"], 1):
            print(f"\n[{i}] {entry['tool']}")
            print(f"    args   {json.dumps(entry['args'], default=str)}")
            result = json.dumps(entry["result"], default=str)
            print(f"    result {result[:300]}{'...' if len(result) > 300 else ''}")
        print("-" * 70)

    decision = state.get("decision") or "(none - agent never called send_reply)"
    print(f"\nDecision : {decision}")
    print(f"Reply    : {state.get('reply') or '(none)'}")
    print(f"Steps    : {state.get('steps')}  Tool calls: {len(state['tool_log'])}")

    if request.expected_decision:
        ok = state.get("decision") == request.expected_decision
        print(f"Correct  : {'YES' if ok else 'NO -- expected ' + request.expected_decision}")


if __name__ == "__main__":
    main()
