"""
API routes for diagnosis and evidence.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

from blackbox.storage.interface import StorageBackend


class DiagnosisResponse(BaseModel):
    """Response for diagnosis."""
    diagnosis_id: str
    run_id: str
    status: str
    suspected_event_id: Optional[str]
    confidence: float
    ranking: List[Dict[str, Any]]
    evidence: List[Dict[str, Any]]


def create_router(storage: StorageBackend) -> APIRouter:
    """Create diagnosis router with storage dependency."""
    router = APIRouter()
    
    @router.get("/runs/{run_id}/diagnosis", response_model=Optional[DiagnosisResponse])
    def get_diagnosis(run_id: str):
        """
        Get diagnosis for a run.
        
        Args:
            run_id: Run ID
            
        Returns:
            Diagnosis result if available
        """
        try:
            # Verify run exists
            run = storage.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            
            # Get diagnosis
            diagnosis = storage.get_diagnosis_for_run(run_id)
            if not diagnosis:
                return None
            
            # Get evidence
            evidence = storage.get_evidence_for_diagnosis(diagnosis.diagnosis_id)
            
            return DiagnosisResponse(
                diagnosis_id=diagnosis.diagnosis_id,
                run_id=diagnosis.run_id,
                status=diagnosis.status,
                suspected_event_id=diagnosis.suspected_event_id,
                confidence=diagnosis.confidence,
                ranking=[r.dict() for r in diagnosis.rankings],
                evidence=[e.dict() for e in evidence],
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/runs/{run_id}/diagnose")
    def trigger_diagnosis(run_id: str):
        """
        Trigger diagnosis for a run.
        
        Args:
            run_id: Run ID
            
        Returns:
            Message indicating diagnosis was triggered
        """
        try:
            # Verify run exists
            run = storage.get_run(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="Run not found")
            
            # TODO: Implement actual diagnosis triggering
            return {
                "message": "Diagnosis triggered",
                "run_id": run_id,
                "status": "pending"
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    return router
