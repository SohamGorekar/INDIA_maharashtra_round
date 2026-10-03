"""
API routes for runs and events.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from blackbox.storage.interface import StorageBackend
from blackbox.events.schema import Run, ExecutionEvent


class TraceResponse(BaseModel):
    """Complete trace response for frontend rendering."""
    run: Dict[str, Any]
    events: List[Dict[str, Any]]
    diagnosis: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = {}


class EventDetailResponse(BaseModel):
    """Detailed event response."""
    event: Dict[str, Any]
    state_before: Optional[Dict[str, Any]] = None
    state_after: Optional[Dict[str, Any]] = None
    checkpoint: Optional[Dict[str, Any]] = None
    diagnosis: Optional[Dict[str, Any]] = None
    evidence: List[Dict[str, Any]] = []


def create_router(storage: StorageBackend) -> APIRouter:
    """Create runs router with storage dependency."""
    router = APIRouter()
    
    @router.get("/runs", response_model=List[Dict[str, Any]])
    def list_runs(
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0)
    ):
        """
        List all runs.
        
        Args:
            limit: Maximum number of runs to return
            offset: Offset for pagination
            
        Returns:
            List of runs
        """
        try:
            runs = storage.list_runs(limit=limit, offset=offset)
            return [run.dict() for run in runs]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/runs/{run_id}", response_model=Dict[str, Any])
    def get_run(run_id: str):
        """
        Get a specific run.
        
        Args:
            run_id: Run ID
            
        Returns:
            Run details
        """
        try:
            run = storage.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            return run.dict()
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/runs/{run_id}/trace", response_model=TraceResponse)
    def get_run_trace(run_id: str):
        """
        Get complete trace for a run (frontend-friendly format).
        
        Args:
            run_id: Run ID
            
        Returns:
            Complete trace with run, events, and diagnosis
        """
        try:
            # Get run
            run = storage.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            
            # Get events
            events = storage.get_events_for_run(run_id)
            
            # Get diagnosis if available
            diagnosis = storage.get_diagnosis_for_run(run_id)
            diagnosis_dict = None
            if diagnosis:
                diagnosis_dict = diagnosis.dict()
            
            return TraceResponse(
                run=run.dict(),
                events=[event.dict() for event in events],
                diagnosis=diagnosis_dict,
                metadata={},
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/runs/{run_id}/events/{event_id}", response_model=EventDetailResponse)
    def get_event_detail(run_id: str, event_id: str):
        """
        Get detailed information for an event.
        
        Args:
            run_id: Run ID
            event_id: Event ID
            
        Returns:
            Detailed event information
        """
        try:
            # Get event
            event = storage.get_event(event_id)
            if not event or event.run_id != run_id:
                raise HTTPException(status_code=404, detail="Event not found")
            
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
            
            return EventDetailResponse(
                event=event.dict(),
                state_before=event.state_before,
                state_after=event.state_after,
                checkpoint=checkpoint_dict,
                diagnosis=diagnosis_dict,
                evidence=evidence_list,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/runs/{run_id}/checkpoints", response_model=List[Dict[str, Any]])
    def get_run_checkpoints(run_id: str):
        """
        Get all checkpoints for a run.
        
        Args:
            run_id: Run ID
            
        Returns:
            List of checkpoints
        """
        try:
            # Verify run exists
            run = storage.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            
            checkpoints = storage.get_checkpoints_for_run(run_id)
            return [cp.dict() for cp in checkpoints]
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return router
