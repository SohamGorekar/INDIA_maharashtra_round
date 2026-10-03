"""Measure how often the agent reaches the right decision.

Compares the agent's answer against `correct_decision` -- the policy oracle -- on
a batch of generated requests, and prints accuracy plus a confusion breakdown so
you can see WHICH way it goes wrong, not just how often.

    python -m support.agent.eval --n 50
"""

import argparse
import time
from collections import Counter

from support.agent.graph import get_graph, initial_state
from support.agent.llm import cache_stats
from support.agent.prompts import build_user_message
from support.agent.tools import set_dry_run
from support.data.sample_requests import generate
from support.rules.decision import DECISIONS

TARGET_ACCURACY = 0.70


def evaluate(n: int = 50, show_failures: bool = True) -> dict:
    # Always dry-run: an eval must not mutate the store, or the second run would
    # see different data than the first.
    set_dry_run(True)
    graph = get_graph()
    requests = generate(n)

    results = []
    started = time.time()

    for i, request in enumerate(requests, 1):
        try:
            state = graph.invoke(initial_state(build_user_message(request)))
            got = state.get("decision", "")
            tool_calls = [e["tool"] for e in state["tool_log"]]
            error = ""
        except Exception as exc:  # noqa: BLE001 - one bad run shouldn't kill the eval
            got, tool_calls, error = "", [], f"{type(exc).__name__}: {exc}"

        results.append({
            "request": request,
            "expected": request.expected_decision,
            "got": got,
            "correct": got == request.expected_decision,
            "tool_calls": tool_calls,
            "error": error,
        })
        mark = "ok " if results[-1]["correct"] else "FAIL"
        print(f"[{i:>3}/{n}] {mark} expected {request.expected_decision:<14} "
              f"got {got or '(none)'}")

    elapsed = time.time() - started
    correct = sum(r["correct"] for r in results)
    accuracy = correct / len(results) if results else 0.0

    print("\n" + "=" * 70)
    print(f"Accuracy: {correct}/{len(results)} = {accuracy:.1%}   "
          f"(target {TARGET_ACCURACY:.0%})   [{elapsed:.0f}s]")
    print("=" * 70)

    # Per-decision breakdown: shows whether the agent is weak on one specific
    # outcome rather than uniformly noisy.
    print("\nPer expected decision:")
    for decision in DECISIONS:
        subset = [r for r in results if r["expected"] == decision]
        if subset:
            hits = sum(r["correct"] for r in subset)
            print(f"  {decision:<14} {hits:>3}/{len(subset):<3} ({hits/len(subset):.0%})")

    print("\nWhat it answered instead (expected -> got):")
    confusion = Counter(
        (r["expected"], r["got"] or "NO_REPLY") for r in results if not r["correct"]
    )
    for (expected, got), count in confusion.most_common():
        print(f"  {expected:<14} -> {got:<14} {count}")

    # Process checks. These catch an agent that lands on the right answer by
    # luck while skipping the steps the policy requires.
    checked_policy = sum(1 for r in results if "check_policy" in r["tool_calls"])
    acted_before_policy = sum(
        1 for r in results
        if "take_action" in r["tool_calls"] and (
            "check_policy" not in r["tool_calls"]
            or r["tool_calls"].index("take_action") < r["tool_calls"].index("check_policy")
        )
    )
    no_reply = sum(1 for r in results if not r["got"])
    errored = sum(1 for r in results if r["error"])

    print("\nProcess:")
    print(f"  checked policy            {checked_policy}/{len(results)}")
    print(f"  acted before checking     {acted_before_policy}  (should be 0)")
    print(f"  never called send_reply   {no_reply}")
    print(f"  crashed                   {errored}")
    print(f"  llm cache                 {cache_stats()['entries']} entries")

    if show_failures:
        failures = [r for r in results if not r["correct"]][:5]
        if failures:
            print("\nFirst failures in detail:")
            for r in failures:
                print(f"\n  {r['request'].message}")
                print(f"    order    {r['request'].order_id}")
                print(f"    expected {r['expected']}   got {r['got'] or '(none)'}")
                print(f"    tools    {' -> '.join(r['tool_calls']) or '(none)'}")
                if r["error"]:
                    print(f"    error    {r['error']}")

    verdict = "PASS" if accuracy >= TARGET_ACCURACY else "BELOW TARGET"
    print(f"\n{verdict}")
    return {"accuracy": accuracy, "correct": correct, "total": len(results),
            "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate agent decision accuracy")
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--quiet", action="store_true", help="skip failure detail")
    args = parser.parse_args()
    evaluate(args.n, show_failures=not args.quiet)
