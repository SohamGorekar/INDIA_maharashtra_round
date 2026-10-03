"""
Checkpoint manager for state snapshots.
"""
import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from blackbox.events.schema import Checkpoint
from blackbox.storage.interface import StorageBackend


class CheckpointManager:
    """
    Manages state checkpoints for replay and counterfactual execution.
    """
    
    def __init__(self, storage: Optional[StorageBackend] = None):
        """
        Initialize checkpoint manager.
        
        Args:
            storage: Storage backend for persisting checkpoints
        """
        self.storage = storage
        self._checkpoints: Dict[str, Checkpoint] = {}
    
    def create_checkpoint(
        self,
        run_id: str,
        event_id: str,
        sequence_number: int,
        state: Dict[str, Any]
    ) -> Checkpoint:
        """
        Create a checkpoint from current state.
        
        Args:
            run_id: Run ID
            event_id: Event ID at which checkpoint is taken
            sequence_number: Sequence number in the run
            state: State to checkpoint
            
        Returns:
            Created Checkpoint
        """
        checkpoint_id = f"cp_{uuid.uuid4().hex[:12]}"
        state_hash = self._hash_state(state)
        
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            run_id=run_id,
            event_id=event_id,
            sequence_number=sequence_number,
            state=state,
            state_hash=state_hash,
            created_at=datetime.utcnow(),
            storage_reference=None,
        )
        
        # Store in memory
        self._checkpoints[checkpoint_id] = checkpoint
        
        # Persist to storage if available
        if self.storage:
            try:
                self.storage.store_checkpoint(checkpoint)
            except Exception as e:
                print(f"Warning: Failed to persist checkpoint: {e}")
        
        return checkpoint
    
    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """
        Retrieve a checkpoint by ID.
        
        Args:
            checkpoint_id: Checkpoint ID
            
        Returns:
            Checkpoint if found, None otherwise
        """
        # Check memory first
        if checkpoint_id in self._checkpoints:
            return self._checkpoints[checkpoint_id]
        
        # Try storage
        if self.storage:
            try:
                checkpoint = self.storage.get_checkpoint(checkpoint_id)
                if checkpoint:
                    self._checkpoints[checkpoint_id] = checkpoint
                    return checkpoint
            except Exception as e:
                print(f"Warning: Failed to retrieve checkpoint from storage: {e}")
        
        return None
    
    def restore_state(self, checkpoint: Checkpoint) -> Dict[str, Any]:
        """
        Restore state from a checkpoint.
        
        Args:
            checkpoint: Checkpoint to restore from
            
        Returns:
            Restored state
        """
        # Verify state hash
        computed_hash = self._hash_state(checkpoint.state)
        if computed_hash != checkpoint.state_hash:
            raise ValueError(f"Checkpoint state hash mismatch: {checkpoint.checkpoint_id}")
        
        return checkpoint.state.copy()
    
    def list_checkpoints_for_run(self, run_id: str) -> list:
        """
        List all checkpoints for a run.
        
        Args:
            run_id: Run ID
            
        Returns:
            List of checkpoints
        """
        if self.storage:
            try:
                return self.storage.get_checkpoints_for_run(run_id)
            except Exception as e:
                print(f"Warning: Failed to list checkpoints: {e}")
        
        # Fallback to memory
        return [
            cp for cp in self._checkpoints.values()
            if cp.run_id == run_id
        ]
    
    def _hash_state(self, state: Dict[str, Any]) -> str:
        """
        Compute hash of state for verification.
        
        Args:
            state: State dictionary
            
        Returns:
            Hash string
        """
        # Serialize state deterministically
        state_json = json.dumps(state, sort_keys=True)
        return hashlib.sha256(state_json.encode()).hexdigest()
