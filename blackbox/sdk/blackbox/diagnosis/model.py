"""
ML-based failure diagnosis model.
"""
import uuid
import random
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from blackbox.events.schema import (
    ExecutionEvent, 
    Run, 
    Diagnosis, 
    DiagnosisStatus,
    EventRanking,
    RunOutcome,
)
from blackbox.diagnosis.features import FeatureExtractor
from blackbox.storage.interface import StorageBackend


class DiagnosisModel:
    """
    Machine learning model for failure diagnosis.
    Predicts which event is the culprit in a failed run.
    """
    
    def __init__(
        self,
        model_name: str = "xgboost_v1",
        model_version: str = "0.1.0",
        simulated: bool = False,
    ):
        self.model_name = model_name
        self.model_version = model_version
        self.simulated = simulated
        self.feature_extractor = FeatureExtractor()
        self.model = None  # Placeholder for trained model
        self.is_trained = False
    
    def train(
        self,
        training_runs: List[Dict[str, Any]],
        validation_runs: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Train the diagnosis model.
        
        Args:
            training_runs: List of dicts with 'run', 'events', 'culprit_event_id'
            validation_runs: Optional validation data
        """
        # Extract features and labels
        X_train = []
        y_train = []
        
        for run_data in training_runs:
            run = run_data['run']
            events = run_data['events']
            culprit_id = run_data.get('culprit_event_id')
            
            # Extract features for all events
            features = self.feature_extractor.extract_run_features(run, events)
            
            # Create labels (1 for culprit, 0 for others)
            labels = np.array([
                1.0 if event.event_id == culprit_id else 0.0
                for event in events
            ])
            
            X_train.append(features)
            y_train.append(labels)
        
        # Flatten for training
        X_train_flat = np.vstack(X_train)
        y_train_flat = np.concatenate(y_train)
        
        # TODO: Train actual model (XGBoost, LightGBM, etc.)
        # For now, just mark as trained
        self.is_trained = True
        
        print(f"Model trained on {len(training_runs)} runs, {len(X_train_flat)} total events")
    
    def diagnose(
        self,
        run: Run,
        events: List[ExecutionEvent],
        storage: Optional[StorageBackend] = None
    ) -> Diagnosis:
        """
        Diagnose a failed run.
        
        Args:
            run: The run to diagnose
            events: All events in the run
            storage: Optional storage to persist diagnosis
            
        Returns:
            Diagnosis result
        """
        if self.simulated:
            return self._simulated_diagnose(run, events, storage)

        if not self.is_trained and not self.model:
            # Use heuristic fallback if not trained
            return self._heuristic_diagnose(run, events, storage)
        
        # Extract features
        features = self.feature_extractor.extract_run_features(run, events)
        
        # TODO: Predict with actual model
        # For now, use simple heuristic
        scores = self._compute_heuristic_scores(events)
        
        # Rank events by score
        event_scores = list(zip([e.event_id for e in events], scores))
        event_scores_sorted = sorted(event_scores, key=lambda x: x[1], reverse=True)
        
        # Create rankings
        rankings = [
            EventRanking(
                event_id=event_id,
                score=float(score),
                rank=rank + 1
            )
            for rank, (event_id, score) in enumerate(event_scores_sorted)
        ]
        
        # Top suspect
        suspected_event_id = rankings[0].event_id if rankings else None
        confidence = rankings[0].score if rankings else 0.0
        
        # Determine status
        if confidence > 0.7:
            status = DiagnosisStatus.CULPRIT
        elif confidence > 0.3:
            status = DiagnosisStatus.UNCERTAIN
        else:
            status = DiagnosisStatus.BENIGN
        
        # Create diagnosis
        diagnosis = Diagnosis(
            diagnosis_id=f"diag_{uuid.uuid4().hex[:12]}",
            run_id=run.run_id,
            status=status,
            suspected_event_id=suspected_event_id,
            confidence=confidence,
            rankings=rankings,
            model_name=self.model_name,
            model_version=self.model_version,
            created_at=datetime.utcnow(),
        )
        
        # Persist if storage provided
        if storage:
            try:
                storage.store_diagnosis(diagnosis)
            except Exception as e:
                print(f"Warning: Failed to store diagnosis: {e}")
        
        return diagnosis
    
    def _heuristic_diagnose(
        self,
        run: Run,
        events: List[ExecutionEvent],
        storage: Optional[StorageBackend]
    ) -> Diagnosis:
        """Fallback heuristic diagnosis when model is not trained."""
        scores = self._compute_heuristic_scores(events)
        
        event_scores = list(zip([e.event_id for e in events], scores))
        event_scores_sorted = sorted(event_scores, key=lambda x: x[1], reverse=True)
        
        rankings = [
            EventRanking(
                event_id=event_id,
                score=float(score),
                rank=rank + 1
            )
            for rank, (event_id, score) in enumerate(event_scores_sorted)
        ]
        
        suspected_event_id = rankings[0].event_id if rankings else None
        confidence = rankings[0].score if rankings else 0.0
        
        if confidence > 0.7:
            status = DiagnosisStatus.CULPRIT
        elif confidence > 0.3:
            status = DiagnosisStatus.UNCERTAIN
        else:
            status = DiagnosisStatus.BENIGN
        
        diagnosis = Diagnosis(
            diagnosis_id=f"diag_{uuid.uuid4().hex[:12]}",
            run_id=run.run_id,
            status=status,
            suspected_event_id=suspected_event_id,
            confidence=confidence,
            rankings=rankings,
            model_name=f"{self.model_name}_heuristic",
            model_version=self.model_version,
            created_at=datetime.utcnow(),
        )
        
        if storage:
            try:
                storage.store_diagnosis(diagnosis)
            except Exception as e:
                print(f"Warning: Failed to store diagnosis: {e}")
        
        return diagnosis
    
    def _compute_heuristic_scores(self, events: List[ExecutionEvent]) -> np.ndarray:
        """Compute heuristic suspicion scores for events."""
        scores = np.zeros(len(events))
        
        for idx, event in enumerate(events):
            score = 0.0
            
            # Error events are highly suspicious
            if event.status == 'error':
                score += 0.5
            
            # Later events are more suspicious
            score += 0.3 * (event.sequence_number / len(events))
            
            # Tool calls are more suspicious
            if event.component_type == 'tool':
                score += 0.2
            
            scores[idx] = min(score, 1.0)
        
        return scores

    def _simulated_diagnose(
        self,
        run: Run,
        events: List[ExecutionEvent],
        storage: Optional[StorageBackend],
    ) -> Diagnosis:
        """Generate visibly dynamic demo results from this run's actual stages."""
        if not events:
            raise ValueError("Cannot diagnose a run with no events")

        rng = random.SystemRandom()
        event_ids = [event.event_id for event in events]

        # A run can have no highlighted stage, or one to three highlighted stages.
        suspected_count = rng.choices(
            [0, 1, 2, 3],
            weights=[0.20, 0.45, 0.25, 0.10],
            k=1,
        )[0]
        suspected_ids = rng.sample(event_ids, min(suspected_count, len(event_ids)))
        suspected_set = set(suspected_ids)

        scores = []
        for event in events:
            if event.event_id in suspected_set:
                score = rng.uniform(0.72, 0.99)
            else:
                score = rng.uniform(0.02, 0.68)
            scores.append((event.event_id, score))

        event_scores_sorted = sorted(scores, key=lambda item: item[1], reverse=True)
        rankings = [
            EventRanking(event_id=event_id, score=round(score, 4), rank=rank + 1)
            for rank, (event_id, score) in enumerate(event_scores_sorted)
        ]
        top_score = rankings[0].score if suspected_ids else 0.0
        status = (
            DiagnosisStatus.CULPRIT
            if suspected_ids
            else DiagnosisStatus.BENIGN
        )
        diagnosis = Diagnosis(
            diagnosis_id=f"diag_{uuid.uuid4().hex[:12]}",
            run_id=run.run_id,
            status=status,
            suspected_event_id=suspected_ids[0] if suspected_ids else None,
            suspected_event_ids=suspected_ids,
            confidence=top_score,
            rankings=rankings,
            model_name="simulated_demo",
            model_version="1.0.0",
            created_at=datetime.utcnow(),
        )

        if storage:
            storage.store_diagnosis(diagnosis)
        return diagnosis
    
    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """
        Predict probability scores for events.
        
        Args:
            features: Feature matrix (num_events, num_features)
            
        Returns:
            Probability scores (num_events,)
        """
        if not self.is_trained:
            raise ValueError("Model is not trained")
        
        # TODO: Implement actual prediction
        # For now, return uniform probabilities
        return np.ones(len(features)) / len(features)
