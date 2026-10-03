"""
Real replay and counterfactual execution for the customer support agent.

This module implements actual checkpoint restoration and re-execution,
not just placeholder responses.
"""
import sys
from pathlib import Path

# Add Black Box SDK to path
SDK_PATH = Path(__file__).resolve().parents[3] / "blackbox" / "sdk"
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

from typing import Dict, Any, Optional
import uuid
from datetime import datetime
import copy

from blackbox.events.schema import RunOutcome, RunStatus, EventStatus
from blackbox.storage.interface import StorageBackend
from support.blackbox_integration.adapter import LangGraphAdapter
from support.blackbox_integration.instrumented_graph import (
    get_instrumented_graph,
    get_checkpoint_manager,
    get_adapter,
    run_with_blackbox,
    initialize_blackbox,
)


class ReplayEngine:
    """
    Handles replay execution from checkpoints.
    """
    
    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self.adapter = LangGraphAdapter()
        self.checkpoint_manager = get_checkpoint_manager()
    
    def replay_from_checkpoint(
        self,
        original_run_id: str,
        checkpoint_id: str,
        safe_mode: bool = True
    ) -> Dict[str, Any]:
        """
        Replay execution from a checkpoint.
        
        Args:
            original_run_id: Original run ID
            checkpoint_id: Checkpoint to restore from
            safe_mode: If True, prevent side effects
            
        Returns:
            Dict with replay results
        """
        # Get original run
        original_run = self.storage.get_run(original_run_id)
        if not original_run:
            raise ValueError(f"Run {original_run_id} not found")
        
        # Get checkpoint
        checkpoint = self.storage.get_checkpoint(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")
        
        if checkpoint.run_id != original_run_id:
            raise ValueError("Checkpoint does not belong to this run")
        
        # Get all events from original run
        original_events = self.storage.get_events_for_run(original_run_id)
        original_events_sorted = sorted(original_events, key=lambda e: e.sequence_number)
        
        # Determine which events to reuse
        checkpoint_seq = checkpoint.sequence_number
        events_to_reuse = [e for e in original_events_sorted if e.sequence_number <= checkpoint_seq]
        events_after = [e for e in original_events_sorted if e.sequence_number > checkpoint_seq]
        
        # Restore state from checkpoint
        restored_state = self.checkpoint_manager.restore_state(checkpoint)
        agent_state = self.adapter.restore_state(restored_state)
        
        # Clear terminal state so execution can continue
        agent_state["decision"] = ""
        agent_state["reply"] = ""
        agent_state["steps"] = checkpoint_seq
        
        # Run from restored state with safe mode
        if safe_mode:
            # In safe mode, we prevent writes
            from support.agent.tools import set_dry_run
            set_dry_run(True)
        
        # Execute replay
        replay_run_id = f"replay_{uuid.uuid4().hex[:12]}"
        
        try:
            # Run the agent from the restored state
            final_state, _ = run_with_blackbox(
                agent_state,
                metadata={
                    "is_replay": True,
                    "original_run_id": original_run_id,
                    "checkpoint_id": checkpoint_id,
                    "replay_run_id": replay_run_id,
                }
            )
            
            # Get replay events
            replay_events = self.storage.get_events_for_run(replay_run_id)
            
            return {
                "replay_run_id": replay_run_id,
                "original_run_id": original_run_id,
                "checkpoint_id": checkpoint_id,
                "steps_reused": len(events_to_reuse),
                "steps_reexecuted": len(replay_events) if replay_events else 0,
                "outcome": final_state.get("decision", "UNKNOWN"),
                "final_state": final_state,
                "safe_mode": safe_mode,
            }
            
        except Exception as exc:
            return {
                "replay_run_id": replay_run_id,
                "original_run_id": original_run_id,
                "checkpoint_id": checkpoint_id,
                "error": f"{type(exc).__name__}: {exc}",
                "steps_reused": len(events_to_reuse),
                "steps_reexecuted": 0,
                "outcome": "ERROR",
                "safe_mode": safe_mode,
            }


class CounterfactualEngine:
    """
    Handles counterfactual execution with modified events.
    """
    
    def __init__(self, storage: StorageBackend):
        self.storage = storage
        self.adapter = LangGraphAdapter()
        self.checkpoint_manager = get_checkpoint_manager()
    
    def run_counterfactual(
        self,
        original_run_id: str,
        event_id_to_modify: str,
        modification: Dict[str, Any],
        safe_mode: bool = True
    ) -> Dict[str, Any]:
        """
        Run counterfactual execution with a modified event.
        
        Args:
            original_run_id: Original run ID
            event_id_to_modify: Event to modify
            modification: Patch to apply (e.g., {"output": {...}})
            safe_mode: If True, prevent side effects
            
        Returns:
            Dict with counterfactual results
        """
        # Get original run and events
        original_run = self.storage.get_run(original_run_id)
        if not original_run:
            raise ValueError(f"Run {original_run_id} not found")
        
        # Get the event to modify
        event_to_modify = self.storage.get_event(event_id_to_modify)
        if not event_to_modify:
            raise ValueError(f"Event {event_id_to_modify} not found")
        
        if event_to_modify.run_id != original_run_id:
            raise ValueError("Event does not belong to this run")
        
        # Find checkpoint before this event
        checkpoints = self.storage.get_checkpoints_for_run(original_run_id)
        checkpoints_sorted = sorted(checkpoints, key=lambda c: c.sequence_number)
        
        # Find the checkpoint immediately before or at the event
        checkpoint_before = None
        for cp in checkpoints_sorted:
            if cp.sequence_number <= event_to_modify.sequence_number:
                checkpoint_before = cp
            else:
                break
        
        if not checkpoint_before:
            raise ValueError("No checkpoint found before the event to modify")
        
        # Restore state from checkpoint
        restored_state = self.checkpoint_manager.restore_state(checkpoint_before)
        agent_state = self.adapter.restore_state(restored_state)
        
        # Apply modification to the agent state
        # The modification typically affects the facts gathered by tools
        if "output" in modification and event_to_modify.component_name in agent_state.get("facts", {}):
            # Modify the stored fact for this tool
            agent_state["facts"][event_to_modify.component_name] = modification["output"]
        
        # Clear terminal state
        agent_state["decision"] = ""
        agent_state["reply"] = ""
        agent_state["steps"] = checkpoint_before.sequence_number
        
        # Set safe mode
        if safe_mode:
            from support.agent.tools import set_dry_run
            set_dry_run(True)
        
        # Create counterfactual run ID
        counterfactual_run_id = f"cf_{uuid.uuid4().hex[:12]}"
        
        try:
            # Run with the modified state
            final_state, _ = run_with_blackbox(
                agent_state,
                metadata={
                    "is_counterfactual": True,
                    "original_run_id": original_run_id,
                    "modified_event_id": event_id_to_modify,
                    "modification": modification,
                    "counterfactual_run_id": counterfactual_run_id,
                }
            )
            
            # Evaluate outcome change
            original_decision = original_run.metadata.get("final_decision", "UNKNOWN")
            if not original_decision or original_decision == "UNKNOWN":
                # Try to infer from outcome
                original_decision = "FAILURE" if original_run.outcome == RunOutcome.FAILURE else "SUCCESS"
            
            counterfactual_decision = final_state.get("decision", "UNKNOWN")
            
            # Determine if counterfactual validates the diagnosis
            outcome_changed = original_decision != counterfactual_decision
            validated = outcome_changed and (
                original_run.outcome == RunOutcome.FAILURE and
                counterfactual_decision in ["APPROVE", "DENY", "REQUEST_PHOTO", "ESCALATE"]
            )
            
            validation = {
                "supported": validated,
                "reason": (
                    f"Final outcome changed from {original_decision} to {counterfactual_decision} "
                    f"after modifying the suspected transition."
                    if outcome_changed
                    else f"Outcome remained {original_decision} after modification."
                )
            }
            
            return {
                "counterfactual_run_id": counterfactual_run_id,
                "original_run_id": original_run_id,
                "modified_event_id": event_id_to_modify,
                "modification": modification,
                "outcome": counterfactual_decision,
                "original_outcome": original_decision,
                "validation": validation,
                "final_state": final_state,
                "safe_mode": safe_mode,
            }
            
        except Exception as exc:
            return {
                "counterfactual_run_id": counterfactual_run_id,
                "original_run_id": original_run_id,
                "modified_event_id": event_id_to_modify,
                "error": f"{type(exc).__name__}: {exc}",
                "outcome": "ERROR",
                "validation": {
                    "supported": False,
                    "reason": f"Counterfactual execution failed: {exc}"
                },
                "safe_mode": safe_mode,
            }


def compare_traces(
    storage: StorageBackend,
    run_id_1: str,
    run_id_2: str
) -> Dict[str, Any]:
    """
    Compare two execution traces.
    
    Args:
        storage: Storage backend
        run_id_1: First run ID
        run_id_2: Second run ID
        
    Returns:
        Structured diff
    """
    # Get both runs
    run1 = storage.get_run(run_id_1)
    run2 = storage.get_run(run_id_2)
    
    if not run1 or not run2:
        raise ValueError("One or both runs not found")
    
    # Get events
    events1 = storage.get_events_for_run(run_id_1)
    events2 = storage.get_events_for_run(run_id_2)
    
    events1_sorted = sorted(events1, key=lambda e: e.sequence_number)
    events2_sorted = sorted(events2, key=lambda e: e.sequence_number)
    
    # Find first divergence
    first_divergence = None
    changed_events = []
    
    for i, (e1, e2) in enumerate(zip(events1_sorted, events2_sorted)):
        if (e1.component_name != e2.component_name or
            e1.output != e2.output or
            e1.status != e2.status):
            if first_divergence is None:
                first_divergence = e1.event_id
            
            changed_events.append({
                "sequence_number": e1.sequence_number,
                "event_id_1": e1.event_id,
                "event_id_2": e2.event_id,
                "component_name": e1.component_name,
                "output_changed": e1.output != e2.output,
                "status_changed": e1.status != e2.status,
            })
    
    # Find added/removed events
    added_events = []
    removed_events = []
    
    if len(events2_sorted) > len(events1_sorted):
        added_events = [e.event_id for e in events2_sorted[len(events1_sorted):]]
    elif len(events1_sorted) > len(events2_sorted):
        removed_events = [e.event_id for e in events1_sorted[len(events2_sorted):]]
    
    return {
        "first_divergence_event_id": first_divergence,
        "changed_events": changed_events,
        "added_events": added_events,
        "removed_events": removed_events,
        "outcome": {
            "original": run1.outcome,
            "alternative": run2.outcome,
        },
        "run_1": {
            "run_id": run_id_1,
            "event_count": len(events1),
        },
        "run_2": {
            "run_id": run_id_2,
            "event_count": len(events2),
        },
    }
