"""
Black Box API routes for the customer support agent.

These routes extend the existing FastAPI app with Black Box functionality.
"""
import sys
from pathlib import Path

# Add Black Box SDK to path
SDK_PATH = Path(__file__).resolve().parents[3] / "blackbox" / "sdk"
if str(SDK_PATH) not in sys.path:
    sys.path.insert(0, str(SDK_PATH))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

from blackbox.diagnosis.model import DiagnosisModel
from blackbox.diagnosis.explanation import EvidenceGenerator
from support.blackbox_integration.instrumented_graph import get_storage
from support.blackbox_integration.replay import (
    ReplayEngine,
    CounterfactualEngine,
    compare_traces,
)


# Pydantic models for API
class ReplayRequest(BaseModel):
    checkpoint_id: str
    safe_mode: bool = True


class CounterfactualRequest(BaseModel):
    event_id: str
    modification: Dict[str, Any]
    safe_mode: bool = True


# Create router
router = APIRouter(prefix="/api/blackbox", tags=["blackbox"])


# Initialize diagnosis model
_diagnosis_model = None


def get_diagnosis_model():
    """Get or create diagnosis model."""
    global _diagnosis_model
    if _diagnosis_model is None:
        _diagnosis_model = DiagnosisModel(model_name="heuristic_v1")
    return _diagnosis_model


@router.get("/runs")
def list_runs(limit: int = 100, offset: int = 0):
    """List all Black Box runs."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        runs = storage.list_runs(limit=limit, offset=offset)
        return [run.dict() for run in runs]
    except Exception as exc:
        raise HTTPException(500, f"Failed to list runs: {exc}")


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    """Get a specific run."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        run = storage.get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        
        return run.dict()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Failed to get run: {exc}")


@router.get("/runs/{run_id}/trace")
def get_trace(run_id: str):
    """Get complete trace for a run (frontend-ready format)."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        # Get run
        run = storage.get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        
        # Get events
        events = storage.get_events_for_run(run_id)
        
        # Get diagnosis if available
        diagnosis = storage.get_diagnosis_for_run(run_id)
        diagnosis_dict = diagnosis.dict() if diagnosis else None
        
        # Get evidence if diagnosis exists
        evidence_list = []
        if diagnosis:
            evidence = storage.get_evidence_for_diagnosis(diagnosis.diagnosis_id)
            evidence_list = [ev.dict() for ev in evidence]
        
        return {
            "run": run.dict(),
            "events": [event.dict() for event in sorted(events, key=lambda e: e.sequence_number)],
            "diagnosis": diagnosis_dict,
            "evidence": evidence_list,
            "metadata": {},
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Failed to get trace: {exc}")


@router.get("/runs/{run_id}/events/{event_id}")
def get_event_detail(run_id: str, event_id: str):
    """Get detailed information for an event."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        # Get event
        event = storage.get_event(event_id)
        if not event or event.run_id != run_id:
            raise HTTPException(404, "Event not found")
        
        # Get checkpoint if exists
        checkpoint = storage.get_checkpoint_for_event(event_id)
        checkpoint_dict = checkpoint.dict() if checkpoint else None
        
        # Get diagnosis for the run
        diagnosis = storage.get_diagnosis_for_run(run_id)
        diagnosis_dict = None
        evidence_list = []
        
        if diagnosis:
            diagnosis_dict = diagnosis.dict()
            # Get evidence related to this event
            all_evidence = storage.get_evidence_for_diagnosis(diagnosis.diagnosis_id)
            evidence_list = [
                ev.dict() for ev in all_evidence
                if ev.event_id == event_id
            ]
        
        return {
            "event": event.dict(),
            "state_before": event.state_before,
            "state_after": event.state_after,
            "checkpoint": checkpoint_dict,
            "diagnosis": diagnosis_dict,
            "evidence": evidence_list,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Failed to get event detail: {exc}")


@router.get("/runs/{run_id}/checkpoints")
def get_checkpoints(run_id: str):
    """Get all checkpoints for a run."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        # Verify run exists
        run = storage.get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        
        checkpoints = storage.get_checkpoints_for_run(run_id)
        return [cp.dict() for cp in checkpoints]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Failed to get checkpoints: {exc}")


@router.get("/runs/{run_id}/diagnosis")
def get_diagnosis(run_id: str):
    """Get or generate diagnosis for a run."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        # Check if diagnosis already exists
        existing_diagnosis = storage.get_diagnosis_for_run(run_id)
        if existing_diagnosis:
            evidence = storage.get_evidence_for_diagnosis(existing_diagnosis.diagnosis_id)
            return {
                "diagnosis": existing_diagnosis.dict(),
                "evidence": [ev.dict() for ev in evidence],
            }
        
        # Generate new diagnosis
        run = storage.get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        
        events = storage.get_events_for_run(run_id)
        if not events:
            raise HTTPException(400, "No events found for this run")
        
        # Run diagnosis
        model = get_diagnosis_model()
        diagnosis = model.diagnose(run, events, storage=storage)
        
        # Generate evidence
        evidence_gen = EvidenceGenerator(storage=storage)
        evidence = evidence_gen.generate_evidence(diagnosis, run, events)
        
        return {
            "diagnosis": diagnosis.dict(),
            "evidence": [ev.dict() for ev in evidence],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Failed to get diagnosis: {exc}")


@router.post("/runs/{run_id}/replay")
def replay_run(run_id: str, request: ReplayRequest):
    """Replay execution from a checkpoint."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        # Verify run exists
        run = storage.get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        
        # Create replay engine and execute
        replay_engine = ReplayEngine(storage)
        result = replay_engine.replay_from_checkpoint(
            original_run_id=run_id,
            checkpoint_id=request.checkpoint_id,
            safe_mode=request.safe_mode
        )
        
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Replay failed: {exc}")


@router.post("/runs/{run_id}/counterfactual")
def run_counterfactual(run_id: str, request: CounterfactualRequest):
    """Run counterfactual execution with a modified event."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        # Verify run exists
        run = storage.get_run(run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        
        # Create counterfactual engine and execute
        cf_engine = CounterfactualEngine(storage)
        result = cf_engine.run_counterfactual(
            original_run_id=run_id,
            event_id_to_modify=request.event_id,
            modification=request.modification,
            safe_mode=request.safe_mode
        )
        
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Counterfactual execution failed: {exc}")


@router.get("/runs/{run_id}/compare/{other_run_id}")
def compare_runs(run_id: str, other_run_id: str):
    """Compare two traces."""
    try:
        storage = get_storage()
        if not storage:
            raise HTTPException(503, "Black Box is not enabled")
        
        result = compare_traces(storage, run_id, other_run_id)
        return result
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Trace comparison failed: {exc}")


@router.get("/health")
def blackbox_health():
    """Health check for Black Box integration."""
    try:
        storage = get_storage()
        if not storage:
            return {
                "enabled": False,
                "message": "Black Box is not enabled (set BLACKBOX_ENABLED=true)"
            }
        
        # Try to list runs to verify database works
        runs = storage.list_runs(limit=1)
        
        return {
            "enabled": True,
            "database": "connected",
            "runs_count": len(runs),
        }
    except Exception as exc:
        return {
            "enabled": True,
            "database": "error",
            "error": str(exc),
        }
