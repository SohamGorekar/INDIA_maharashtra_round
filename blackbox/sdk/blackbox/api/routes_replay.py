"""
API routes for replay and counterfactual execution.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from blackbox.storage.interface import StorageBackend
from blackbox.events.schema import ReplayRun, CounterfactualRun, RunOutcome


class ReplayRequest(BaseModel):
    """Request to replay from a checkpoint."""
    checkpoint_id: str


class ReplayResponse(BaseModel):
    """Response from replay execution."""
    replay_run_id: str
    original_run_id: str
    checkpoint_id: str
    steps_reused: int
    steps_reexecuted: int
    outcome: str


class CounterfactualRequest(BaseModel):
    """Request to run counterfactual execution."""
    event_id: str
    patch: Dict[str, Any]


class CounterfactualResponse(BaseModel):
    """Response from counterfactual execution."""
    counterfactual_run_id: str
    original_run_id: str
    modified_event_id: str
    outcome: str
    validation: Dict[str, Any]


class TraceDiffResponse(BaseModel):
    """Response for trace comparison."""
    first_divergence_event_id: Optional[str]
    changed_events: list
    added_events: list
    removed_events: list
    outcome: Dict[str, str]


def create_router(storage: StorageBackend) -> APIRouter:
    """Create replay router with storage dependency."""
    router = APIRouter()
    
    @router.post("/runs/{run_id}/replay", response_model=ReplayResponse)
    def replay_run(run_id: str, request: ReplayRequest):
        """
        Replay execution from a checkpoint.
        
        Args:
            run_id: Original run ID
            request: Replay request with checkpoint ID
            
        Returns:
            Replay execution result
        """
        try:
            # Verify run exists
            run = storage.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            
            # Verify checkpoint exists
            checkpoint = storage.get_checkpoint(request.checkpoint_id)
            if not checkpoint or checkpoint.run_id != run_id:
                raise HTTPException(status_code=404, detail="Checkpoint not found")
            
            # TODO: Implement actual replay logic
            # For now, create a replay record
            replay_run_id = f"replay_{uuid.uuid4().hex[:12]}"
            
            replay_run = ReplayRun(
                replay_run_id=replay_run_id,
                original_run_id=run_id,
                checkpoint_id=request.checkpoint_id,
                steps_reused=checkpoint.sequence_number,
                steps_reexecuted=run.event_count - checkpoint.sequence_number,
                outcome=run.outcome,  # In real implementation, this would be the new outcome
                created_at=datetime.utcnow(),
            )
            
            storage.store_replay_run(replay_run)
            
            return ReplayResponse(
                replay_run_id=replay_run_id,
                original_run_id=run_id,
                checkpoint_id=request.checkpoint_id,
                steps_reused=replay_run.steps_reused,
                steps_reexecuted=replay_run.steps_reexecuted,
                outcome=replay_run.outcome,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/runs/{run_id}/counterfactual", response_model=CounterfactualResponse)
    def run_counterfactual(run_id: str, request: CounterfactualRequest):
        """
        Run counterfactual execution with a modified event.
        
        Args:
            run_id: Original run ID
            request: Counterfactual request with event ID and patch
            
        Returns:
            Counterfactual execution result
        """
        try:
            # Verify run exists
            run = storage.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            
            # Verify event exists
            event = storage.get_event(request.event_id)
            if not event or event.run_id != run_id:
                raise HTTPException(status_code=404, detail="Event not found")
            
            # TODO: Implement actual counterfactual logic
            # For now, create a counterfactual record
            counterfactual_run_id = f"cf_{uuid.uuid4().hex[:12]}"
            
            # Simulate validation
            validation = {
                "supported": True,
                "reason": "Final outcome changed from FAILURE to SUCCESS after modifying the suspected transition."
            }
            
            counterfactual_run = CounterfactualRun(
                counterfactual_run_id=counterfactual_run_id,
                original_run_id=run_id,
                modified_event_id=request.event_id,
                patch=request.patch,
                outcome=RunOutcome.SUCCESS,  # Simulated
                validation=validation,
                created_at=datetime.utcnow(),
            )
            
            storage.store_counterfactual_run(counterfactual_run)
            
            return CounterfactualResponse(
                counterfactual_run_id=counterfactual_run_id,
                original_run_id=run_id,
                modified_event_id=request.event_id,
                outcome=counterfactual_run.outcome,
                validation=validation,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/runs/{run_id}/compare/{other_run_id}", response_model=TraceDiffResponse)
    def compare_traces(run_id: str, other_run_id: str):
        """
        Compare two traces.
        
        Args:
            run_id: First run ID
            other_run_id: Second run ID
            
        Returns:
            Structured differences between traces
        """
        try:
            # Verify both runs exist
            run1 = storage.get_run(run_id)
            run2 = storage.get_run(other_run_id)
            
            if not run1:
                raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
            if not run2:
                raise HTTPException(status_code=404, detail=f"Run {other_run_id} not found")
            
            # Get events for both runs
            events1 = storage.get_events_for_run(run_id)
            events2 = storage.get_events_for_run(other_run_id)
            
            # Build event maps
            events1_map = {e.event_id: e for e in events1}
            events2_map = {e.event_id: e for e in events2}
            
            # Find differences
            changed_events = []
            first_divergence = None
            
            # Compare events by sequence
            for e1 in events1:
                # Try to find corresponding event in run2 by sequence number
                e2_candidates = [e for e in events2 if e.sequence_number == e1.sequence_number]
                
                if e2_candidates:
                    e2 = e2_candidates[0]
                    # Check for differences
                    input_changed = e1.input != e2.input
                    output_changed = e1.output != e2.output
                    state_changed = e1.state_after != e2.state_after
                    
                    if input_changed or output_changed or state_changed:
                        if first_divergence is None:
                            first_divergence = e1.event_id
                        
                        changed_events.append({
                            "event_id": e1.event_id,
                            "input_changed": input_changed,
                            "output_changed": output_changed,
                            "state_changed": state_changed,
                        })
            
            # Find added/removed events
            seq_nums1 = {e.sequence_number for e in events1}
            seq_nums2 = {e.sequence_number for e in events2}
            
            added_events = [
                e.event_id for e in events2
                if e.sequence_number not in seq_nums1
            ]
            removed_events = [
                e.event_id for e in events1
                if e.sequence_number not in seq_nums2
            ]
            
            return TraceDiffResponse(
                first_divergence_event_id=first_divergence,
                changed_events=changed_events,
                added_events=added_events,
                removed_events=removed_events,
                outcome={
                    "original": run1.outcome,
                    "alternative": run2.outcome,
                }
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return router
