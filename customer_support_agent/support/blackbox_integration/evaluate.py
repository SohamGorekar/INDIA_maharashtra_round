"""
Evaluation script for Black Box diagnosis on customer support agent.

Tests diagnosis accuracy, baseline comparison, and counterfactual validation.
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
from typing import List, Dict
from support.blackbox_integration.instrumented_graph import run_with_blackbox, get_storage, initialize_blackbox
from support.agent.prompts import build_user_message
from support.agent.graph import initial_state
from support.agent.tools import set_dry_run
from support.data.sample_requests import generate
from blackbox.diagnosis.model import DiagnosisModel
from blackbox.diagnosis.baselines import get_baseline_diagnoser
from blackbox.evaluation.metrics import DiagnosisMetrics
from blackbox.events.schema import EventStatus


def run_evaluation_suite(n_samples: int = 20):
    """Run evaluation on sample requests."""
    print("=" * 70)
    print("  BLACK BOX DIAGNOSIS EVALUATION")
    print("=" * 70)
    
    # Initialize
    initialize_blackbox()
    storage = get_storage()
    set_dry_run(True)
    
    # Generate sample requests
    print(f"\n1. Generating {n_samples} sample requests...")
    requests = generate(n_samples)
    
    # Run all requests and collect traces
    print("2. Running requests and collecting traces...")
    failed_runs = []
    
    for i, request in enumerate(requests, 1):
        print(f"   Processing {i}/{n_samples}...", end="\r")
        
        state = initial_state(build_user_message(request))
        final_state, run_id = run_with_blackbox(
            state,
            expected_decision=request.expected_decision,
            metadata={
                "evaluation": True,
                "sample_id": i,
                "expected_decision": request.expected_decision,
            }
        )
        
        decision = final_state.get("decision", "")
        
        # Only diagnose failures or incorrect decisions
        if decision != request.expected_decision or decision == "":
            events = storage.get_events_for_run(run_id)
            
            # Find the "culprit" event (simplified: find the tool that led to wrong decision)
            culprit_event_id = None
            for event in events:
                if event.component_type == "tool" and event.status == EventStatus.SUCCESS:
                    # Heuristic: the check_policy call is often the culprit
                    if event.component_name == "check_policy":
                        culprit_event_id = event.event_id
                        break
            
            if not culprit_event_id and events:
                # Fallback to last tool call
                for event in reversed(events):
                    if event.component_type == "tool":
                        culprit_event_id = event.event_id
                        break
            
            failed_runs.append({
                "run_id": run_id,
                "expected_decision": request.expected_decision,
                "actual_decision": decision,
                "culprit_event_id": culprit_event_id,
                "events": events,
                "run": storage.get_run(run_id),
            })
    
    print(f"\n   Collected {len(failed_runs)} failed/incorrect runs")
    
    if not failed_runs:
        print("\n✓ All runs succeeded! Nothing to diagnose.")
        return
    
    # Evaluate diagnosis models
    print("\n3. Evaluating diagnosis models...")
    
    # Initialize models
    ml_model = DiagnosisModel(model_name="heuristic_v1")
    baselines = {
        "Random": get_baseline_diagnoser("random"),
        "Last Tool": get_baseline_diagnoser("last_tool"),
        "First Error": get_baseline_diagnoser("first_error"),
        "Heuristic": get_baseline_diagnoser("heuristic"),
    }
    
    # Collect predictions
    results = {
        "ML Model": {"predictions": [], "ground_truth": []},
    }
    for name in baselines:
        results[name] = {"predictions": [], "ground_truth": []}
    
    for failed_run in failed_runs:
        run = failed_run["run"]
        events = failed_run["events"]
        ground_truth = failed_run["culprit_event_id"]
        
        # ML model diagnosis
        diagnosis = ml_model.diagnose(run, events, storage=storage)
        ml_predictions = [r.event_id for r in diagnosis.rankings]
        results["ML Model"]["predictions"].append(ml_predictions)
        results["ML Model"]["ground_truth"].append(ground_truth)
        
        # Baseline predictions
        for name, diagnoser in baselines.items():
            baseline_scores = diagnoser.diagnose(run, events)
            baseline_predictions = [event_id for event_id, score in baseline_scores]
            results[name]["predictions"].append(baseline_predictions)
            results[name]["ground_truth"].append(ground_truth)
    
    # Compute metrics
    print("\n4. Results:")
    print("\n" + "-" * 70)
    print(f"{'Model':<15} {'Top-1':>10} {'Top-3':>10} {'MRR':>10} {'Avg Rank':>12}")
    print("-" * 70)
    
    for model_name, data in results.items():
        predictions = data["predictions"]
        ground_truth = data["ground_truth"]
        
        top_1 = DiagnosisMetrics.top_k_accuracy(predictions, ground_truth, k=1)
        top_3 = DiagnosisMetrics.top_k_accuracy(predictions, ground_truth, k=3)
        mrr = DiagnosisMetrics.mean_reciprocal_rank(predictions, ground_truth)
        avg_rank = DiagnosisMetrics.average_rank(predictions, ground_truth)
        
        print(f"{model_name:<15} {top_1:>9.1%} {top_3:>9.1%} {mrr:>10.3f} {avg_rank:>12.1f}")
    
    print("-" * 70)
    
    # Counterfactual validation
    print("\n5. Counterfactual validation...")
    print("   (Testing if fixing suspected events changes outcomes)")
    
    from support.blackbox_integration.replay import CounterfactualEngine
    
    cf_engine = CounterfactualEngine(storage)
    validated = 0
    total_tested = 0
    
    # Test counterfactuals on first few failures
    for failed_run in failed_runs[:5]:
        run_id = failed_run["run_id"]
        diagnosis = ml_model.diagnose(failed_run["run"], failed_run["events"], storage=None)
        
        if not diagnosis.suspected_event_id:
            continue
        
        total_tested += 1
        
        try:
            # Create a "fix" modification
            suspected_event = storage.get_event(diagnosis.suspected_event_id)
            modification = {
                "output": {
                    "eligible": True,  # Simplified fix
                    "policy": "Modified for testing"
                }
            }
            
            result = cf_engine.run_counterfactual(
                original_run_id=run_id,
                event_id_to_modify=diagnosis.suspected_event_id,
                modification=modification,
                safe_mode=True
            )
            
            if result.get("validation", {}).get("supported"):
                validated += 1
        
        except Exception as e:
            print(f"     Counterfactual test failed: {e}")
    
    if total_tested > 0:
        success_rate = validated / total_tested
        print(f"   Counterfactual success rate: {success_rate:.1%} ({validated}/{total_tested})")
    
    print("\n" + "=" * 70)
    print("  EVALUATION COMPLETE")
    print("=" * 70)
    print(f"\n  Failed runs analyzed: {len(failed_runs)}")
    print(f"  Models tested: {len(results)}")
    print(f"  Database: customer_support_blackbox.db")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate Black Box diagnosis")
    parser.add_argument("--n", type=int, default=20, help="Number of samples to test")
    args = parser.parse_args()
    
    run_evaluation_suite(args.n)
