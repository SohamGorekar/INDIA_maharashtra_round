"""
Storage interface for Black Box data persistence.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any

from blackbox.events.schema import (
    ExecutionEvent,
    Run,
    Checkpoint,
    Diagnosis,
    Evidence,
    ReplayRun,
    CounterfactualRun,
)


class StorageBackend(ABC):
    """Abstract base class for storage backends."""
    
    @abstractmethod
    def store_run(self, run: Run):
        """Store a run."""
        pass
    
    @abstractmethod
    def get_run(self, run_id: str) -> Optional[Run]:
        """Retrieve a run by ID."""
        pass
    
    @abstractmethod
    def list_runs(self, limit: int = 100, offset: int = 0) -> List[Run]:
        """List all runs."""
        pass
    
    @abstractmethod
    def update_run(self, run_id: str, updates: Dict[str, Any]):
        """Update a run."""
        pass
    
    @abstractmethod
    def store_event(self, event: ExecutionEvent):
        """Store an execution event."""
        pass
    
    @abstractmethod
    def get_event(self, event_id: str) -> Optional[ExecutionEvent]:
        """Retrieve an event by ID."""
        pass
    
    @abstractmethod
    def get_events_for_run(self, run_id: str) -> List[ExecutionEvent]:
        """Get all events for a run."""
        pass
    
    @abstractmethod
    def get_event_children(self, event_id: str) -> List[ExecutionEvent]:
        """Get child events of a parent event."""
        pass
    
    @abstractmethod
    def store_checkpoint(self, checkpoint: Checkpoint):
        """Store a checkpoint."""
        pass
    
    @abstractmethod
    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Retrieve a checkpoint by ID."""
        pass
    
    @abstractmethod
    def get_checkpoints_for_run(self, run_id: str) -> List[Checkpoint]:
        """Get all checkpoints for a run."""
        pass
    
    @abstractmethod
    def get_checkpoint_for_event(self, event_id: str) -> Optional[Checkpoint]:
        """Get checkpoint associated with an event."""
        pass
    
    @abstractmethod
    def store_diagnosis(self, diagnosis: Diagnosis):
        """Store a diagnosis."""
        pass
    
    @abstractmethod
    def get_diagnosis(self, diagnosis_id: str) -> Optional[Diagnosis]:
        """Retrieve a diagnosis by ID."""
        pass
    
    @abstractmethod
    def get_diagnosis_for_run(self, run_id: str) -> Optional[Diagnosis]:
        """Get diagnosis for a run."""
        pass
    
    @abstractmethod
    def store_evidence(self, evidence: Evidence):
        """Store evidence."""
        pass
    
    @abstractmethod
    def get_evidence_for_diagnosis(self, diagnosis_id: str) -> List[Evidence]:
        """Get all evidence for a diagnosis."""
        pass
    
    @abstractmethod
    def store_replay_run(self, replay_run: ReplayRun):
        """Store a replay run."""
        pass
    
    @abstractmethod
    def get_replay_run(self, replay_run_id: str) -> Optional[ReplayRun]:
        """Retrieve a replay run by ID."""
        pass
    
    @abstractmethod
    def store_counterfactual_run(self, counterfactual_run: CounterfactualRun):
        """Store a counterfactual run."""
        pass
    
    @abstractmethod
    def get_counterfactual_run(self, counterfactual_run_id: str) -> Optional[CounterfactualRun]:
        """Retrieve a counterfactual run by ID."""
        pass
    
    @abstractmethod
    def close(self):
        """Close the storage connection."""
        pass
