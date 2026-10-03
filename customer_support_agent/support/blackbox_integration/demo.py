"""
End-to-end demonstration of Black Box integration.

This script demonstrates:
1. Instrumented execution with trace collection
2. Failure diagnosis with evidence
3. Checkpoint-based replay
4. Counterfactual execution
5. Trace comparison
"""
import sys
from pathlib import Path

# Add Black Box SDK to path
SDK_PATH = Path(__file__).resolve().parents[3] / "blackbox" / "sdk"
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

import os
os.environ["BLACKBOX_ENABLED"] = "true"

from dataclasses import dataclass
from support.blackbox_integration.instrumented_graph import (
    run_with_blackbox,
    get_storage,
    initialize_blackbox,
)
from support.blackbox_integration.replay import ReplayEngine, CounterfactualEngine, compare_traces
from support.agent.prompts import build_user_message
from support.agent.graph import initial_state
from support.agent.tools import set_dry_run
from blackbox.diagnosis.model import DiagnosisModel
from blackbox.diagnosis.explanation import EvidenceGenerator


@dataclass
class DemoRequest:
    """Test request for demonstration."""
    customer_id: str
    message: str
    request_type: str = "refund"
    requested_size: str = ""
    photo_provided: bool = False
    order_id: str = "ORD-0045"
    expected_decision: str = "APPROVE"


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def demo_successful_run():
    """Demonstrate a successful run with tracing."""
    print_section("1. SUCCESSFUL RUN WITH TRACING")
    
    # Create a request that should succeed
    request = DemoRequest(
        customer_id="CUST-0001",
        message="My order ORD-0045 arrived damaged. I'd like a refund.",
        order_id="ORD-0045",
        expected_decision="APPROVE"
    )
    
    print(f"Request: {request.message}")
    print(f"Expected: {request.expected_decision}")
    
    # Run with Black Box
    set_dry_run(True)
    state = initial_state(build_user_message(request))
    final_state, run_id = run_with_blackbox(
        state,
        expected_decision=request.expected_decision,
        metadata={"demo": "successful_run"}
    )
    
    decision = final_state.get("decision", "")
    print(f"\nResult:")
    print(f"  Run ID: {run_id}")
    print(f"  Decision: {decision}")
    print(f"  Correct: {decision == request.expected_decision}")
    print(f"  Steps: {final_state.get('steps', 0)}")
    print(f"  Tools used: {len(final_state.get('tool_log', []))}")
    
    return run_id


def demo_failed_run():
    """Demonstrate a failed run that needs diagnosis."""
    print_section("2. FAILED RUN REQUIRING DIAGNOSIS")
    
    # Create a request that will fail (order not damaged, but requesting refund)
    # We'll simulate a failure by using a wrong order
    request = DemoRequest(
        customer_id="CUST-0001",
        message="I want a refund for my order ORD-0001",
        order_id="ORD-0001",
        expected_decision="DENY"  # Should be denied
    )
    
    print(f"Request: {request.message}")
    print(f"Expected: {request.expected_decision}")
    
    # Run with Black Box
    set_dry_run(True)
    state = initial_state(build_user_message(request))
    final_state, run_id = run_with_blackbox(
        state,
        expected_decision=request.expected_decision,
        metadata={"demo": "failed_run"}
    )
    
    decision = final_state.get("decision", "")
    print(f"\nResult:")
    print(f"  Run ID: {run_id}")
    print(f"  Decision: {decision}")
    print(f"  Correct: {decision == request.expected_decision}")
    print(f"  Steps: {final_state.get('steps', 0)}")
    
    return run_id


def demo_diagnosis(run_id: str):
    """Demonstrate failure diagnosis."""
    print_section("3. FAILURE DIAGNOSIS")
    
    storage = get_storage()
    
    # Get run and events
    run = storage.get_run(run_id)
    events = storage.get_events_for_run(run_id)
    
    print(f"Analyzing run: {run_id}")
    print(f"Events captured: {len(events)}")
    
    # Run diagnosis
    model = DiagnosisModel(model_name="heuristic_v1")
    diagnosis = model.diagnose(run, events, storage=storage)
    
    print(f"\nDiagnosis:")
    print(f"  Status: {diagnosis.status}")
    print(f"  Suspected event: {diagnosis.suspected_event_id}")
    print(f"  Confidence: {diagnosis.confidence:.2%}")
    
    # Show top 3 suspects
    print(f"\n  Top 3 suspects:")
    for ranking in diagnosis.rankings[:3]:
        event = storage.get_event(ranking.event_id)
        if event:
            print(f"    {ranking.rank}. {event.component_name} (score: {ranking.score:.2f})")
    
    # Generate evidence
    evidence_gen = EvidenceGenerator(storage=storage)
    evidence = evidence_gen.generate_evidence(diagnosis, run, events)
    
    print(f"\n  Evidence ({len(evidence)} items):")
    for ev in evidence[:3]:  # Show top 3
        print(f"    - {ev.evidence_type}: {ev.description}")
        print(f"      Strength: {ev.strength:.2f}")
    
    return diagnosis


def demo_replay(run_id: str):
    """Demonstrate checkpoint-based replay."""
    print_section("4. CHECKPOINT-BASED REPLAY")
    
    storage = get_storage()
    
    # Get checkpoints
    checkpoints = storage.get_checkpoints_for_run(run_id)
    print(f"Checkpoints available: {len(checkpoints)}")
    
    if not checkpoints:
        print("No checkpoints available for replay")
        return None
    
    # Use the middle checkpoint
    checkpoint = sorted(checkpoints, key=lambda c: c.sequence_number)[len(checkpoints)//2]
    print(f"Replaying from checkpoint: {checkpoint.checkpoint_id}")
    print(f"  Sequence number: {checkpoint.sequence_number}")
    
    # Execute replay
    replay_engine = ReplayEngine(storage)
    result = replay_engine.replay_from_checkpoint(
        original_run_id=run_id,
        checkpoint_id=checkpoint.checkpoint_id,
        safe_mode=True
    )
    
    print(f"\nReplay result:")
    print(f"  Replay run ID: {result.get('replay_run_id')}")
    print(f"  Steps reused: {result.get('steps_reused')}")
    print(f"  Steps re-executed: {result.get('steps_reexecuted')}")
    print(f"  Outcome: {result.get('outcome')}")
    print(f"  Safe mode: {result.get('safe_mode')}")
    
    if result.get('error'):
        print(f"  Error: {result.get('error')}")
    
    return result.get('replay_run_id')


def demo_counterfactual(run_id: str, diagnosis):
    """Demonstrate counterfactual execution."""
    print_section("5. COUNTERFACTUAL EXECUTION")
    
    storage = get_storage()
    
    suspected_event_id = diagnosis.suspected_event_id
    if not suspected_event_id:
        print("No suspected event to modify")
        return None
    
    suspected_event = storage.get_event(suspected_event_id)
    print(f"Modifying suspected event: {suspected_event.component_name}")
    print(f"  Event ID: {suspected_event_id}")
    print(f"  Original output: {str(suspected_event.output)[:100]}...")
    
    # Create a modification
    # For check_policy tool, change from not eligible to eligible
    modification = {
        "output": {
            "eligible": True,
            "policy": "Modified for counterfactual: customer is eligible"
        }
    }
    
    print(f"\nApplying modification: eligible = True")
    
    # Execute counterfactual
    cf_engine = CounterfactualEngine(storage)
    result = cf_engine.run_counterfactual(
        original_run_id=run_id,
        event_id_to_modify=suspected_event_id,
        modification=modification,
        safe_mode=True
    )
    
    print(f"\nCounterfactual result:")
    print(f"  Counterfactual run ID: {result.get('counterfactual_run_id')}")
    print(f"  Original outcome: {result.get('original_outcome')}")
    print(f"  New outcome: {result.get('outcome')}")
    
    validation = result.get('validation', {})
    print(f"\nValidation:")
    print(f"  Supported: {validation.get('supported')}")
    print(f"  Reason: {validation.get('reason')}")
    
    if result.get('error'):
        print(f"  Error: {result.get('error')}")
    
    return result.get('counterfactual_run_id')


def demo_trace_comparison(run_id_1: str, run_id_2: str):
    """Demonstrate trace comparison."""
    print_section("6. TRACE COMPARISON")
    
    if not run_id_1 or not run_id_2:
        print("Need two run IDs to compare")
        return
    
    storage = get_storage()
    
    print(f"Comparing runs:")
    print(f"  Original: {run_id_1}")
    print(f"  Alternative: {run_id_2}")
    
    diff = compare_traces(storage, run_id_1, run_id_2)
    
    print(f"\nComparison results:")
    print(f"  First divergence: {diff.get('first_divergence_event_id')}")
    print(f"  Changed events: {len(diff.get('changed_events', []))}")
    print(f"  Added events: {len(diff.get('added_events', []))}")
    print(f"  Removed events: {len(diff.get('removed_events', []))}")
    
    outcomes = diff.get('outcome', {})
    print(f"\n  Outcomes:")
    print(f"    Original: {outcomes.get('original')}")
    print(f"    Alternative: {outcomes.get('alternative')}")
    
    # Show first few changes
    changed = diff.get('changed_events', [])
    if changed:
        print(f"\n  First changes:")
        for change in changed[:3]:
            print(f"    Seq {change.get('sequence_number')}: {change.get('component_name')}")
            if change.get('output_changed'):
                print(f"      - Output changed")
            if change.get('status_changed'):
                print(f"      - Status changed")


def main():
    """Run the complete demonstration."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  BLACK BOX INTEGRATION DEMONSTRATION".center(68) + "║")
    print("║" + "  Customer Support Agent".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "═" * 68 + "╝")
    
    # Initialize Black Box
    initialize_blackbox()
    print("\n✓ Black Box initialized")
    
    try:
        # 1. Successful run
        success_run_id = demo_successful_run()
        
        # 2. Failed run
        failed_run_id = demo_failed_run()
        
        # 3. Diagnose the failed run
        diagnosis = demo_diagnosis(failed_run_id)
        
        # 4. Replay from checkpoint
        replay_run_id = demo_replay(failed_run_id)
        
        # 5. Counterfactual execution
        cf_run_id = demo_counterfactual(failed_run_id, diagnosis)
        
        # 6. Compare traces
        if cf_run_id:
            demo_trace_comparison(failed_run_id, cf_run_id)
        
        # Summary
        print_section("DEMONSTRATION COMPLETE")
        print("\nGenerated runs:")
        print(f"  1. Successful run: {success_run_id}")
        print(f"  2. Failed run: {failed_run_id}")
        if replay_run_id:
            print(f"  3. Replay run: {replay_run_id}")
        if cf_run_id:
            print(f"  4. Counterfactual run: {cf_run_id}")
        
        print("\nYou can now:")
        print(f"  - Start API: uvicorn support.api:app --reload --port 8000")
        print(f"  - View traces: GET /api/blackbox/runs/{failed_run_id}/trace")
        print(f"  - View diagnosis: GET /api/blackbox/runs/{failed_run_id}/diagnosis")
        print(f"  - Compare runs: GET /api/blackbox/runs/{failed_run_id}/compare/{cf_run_id}")
        print(f"\n  Database: customer_support_blackbox.db")
        
    except Exception as exc:
        print(f"\n❌ Error during demonstration: {exc}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
