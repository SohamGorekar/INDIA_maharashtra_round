"""
Feature extraction for failure diagnosis.
"""
import json
from typing import List, Dict, Any, Optional
import numpy as np

from blackbox.events.schema import ExecutionEvent, Run, EventStatus


class FeatureExtractor:
    """
    Extracts features from execution events for diagnosis.
    """
    
    def __init__(self):
        self.feature_names = []
    
    def extract_event_features(
        self,
        event: ExecutionEvent,
        all_events: List[ExecutionEvent],
        run: Run
    ) -> Dict[str, float]:
        """
        Extract features for a single event.
        
        Args:
            event: The event to extract features for
            all_events: All events in the run
            run: The run
            
        Returns:
            Dictionary of feature name to value
        """
        features = {}
        
        # Basic event features
        features['sequence_position'] = event.sequence_number / max(len(all_events), 1)
        features['has_error'] = 1.0 if event.status == EventStatus.ERROR else 0.0
        features['duration_ms'] = event.duration_ms or 0.0
        
        # Component type one-hot encoding
        component_types = ['agent', 'tool', 'llm', 'retriever', 'router', 'function', 'custom']
        for ct in component_types:
            features[f'component_type_{ct}'] = 1.0 if event.component_type == ct else 0.0
        
        # Input/output size
        features['input_size'] = self._get_json_size(event.input)
        features['output_size'] = self._get_json_size(event.output)
        
        # State change magnitude
        features['state_change'] = self._compute_state_change(
            event.state_before, 
            event.state_after
        )
        
        # Position in execution graph
        features['is_root'] = 1.0 if event.parent_event_id is None else 0.0
        features['depth'] = self._compute_depth(event, all_events)
        features['num_children'] = self._count_children(event, all_events)
        
        # Timing features
        avg_duration = np.mean([e.duration_ms or 0.0 for e in all_events])
        features['duration_ratio'] = (event.duration_ms or 0.0) / max(avg_duration, 1.0)
        features['is_slow'] = 1.0 if (event.duration_ms or 0.0) > 2 * avg_duration else 0.0
        
        # Error propagation
        features['has_error_descendant'] = 1.0 if self._has_error_descendant(event, all_events) else 0.0
        features['has_error_ancestor'] = 1.0 if self._has_error_ancestor(event, all_events) else 0.0
        
        # Output anomaly (placeholder - would compare with successful runs)
        features['output_anomaly_score'] = 0.0
        
        return features
    
    def extract_run_features(
        self,
        run: Run,
        events: List[ExecutionEvent]
    ) -> np.ndarray:
        """
        Extract features for all events in a run.
        
        Args:
            run: The run
            events: All events in the run
            
        Returns:
            2D numpy array of shape (num_events, num_features)
        """
        feature_dicts = []
        for event in events:
            features = self.extract_event_features(event, events, run)
            feature_dicts.append(features)
        
        # Store feature names from first event
        if feature_dicts and not self.feature_names:
            self.feature_names = sorted(feature_dicts[0].keys())
        
        # Convert to numpy array
        feature_matrix = np.array([
            [fd.get(fname, 0.0) for fname in self.feature_names]
            for fd in feature_dicts
        ])
        
        return feature_matrix
    
    def _get_json_size(self, data: Any) -> float:
        """Get size of JSON-serializable data."""
        if data is None:
            return 0.0
        try:
            return float(len(json.dumps(data)))
        except:
            return 0.0
    
    def _compute_state_change(self, state_before: Any, state_after: Any) -> float:
        """Compute magnitude of state change."""
        if state_before is None or state_after is None:
            return 0.0
        
        try:
            before_str = json.dumps(state_before, sort_keys=True)
            after_str = json.dumps(state_after, sort_keys=True)
            
            # Simple diff: proportion of characters that changed
            if len(before_str) == 0:
                return 1.0 if len(after_str) > 0 else 0.0
            
            # Levenshtein-like approximation
            return float(len(after_str) - len(before_str)) / len(before_str)
        except:
            return 0.0
    
    def _compute_depth(self, event: ExecutionEvent, all_events: List[ExecutionEvent]) -> float:
        """Compute depth of event in execution tree."""
        depth = 0
        current_parent_id = event.parent_event_id
        
        event_map = {e.event_id: e for e in all_events}
        
        while current_parent_id:
            depth += 1
            parent = event_map.get(current_parent_id)
            if not parent:
                break
            current_parent_id = parent.parent_event_id
        
        return float(depth)
    
    def _count_children(self, event: ExecutionEvent, all_events: List[ExecutionEvent]) -> float:
        """Count number of child events."""
        return float(sum(1 for e in all_events if e.parent_event_id == event.event_id))
    
    def _has_error_descendant(self, event: ExecutionEvent, all_events: List[ExecutionEvent]) -> bool:
        """Check if any descendant has an error."""
        children = [e for e in all_events if e.parent_event_id == event.event_id]
        
        for child in children:
            if child.status == EventStatus.ERROR:
                return True
            if self._has_error_descendant(child, all_events):
                return True
        
        return False
    
    def _has_error_ancestor(self, event: ExecutionEvent, all_events: List[ExecutionEvent]) -> bool:
        """Check if any ancestor has an error."""
        if event.parent_event_id is None:
            return False
        
        event_map = {e.event_id: e for e in all_events}
        current_parent_id = event.parent_event_id
        
        while current_parent_id:
            parent = event_map.get(current_parent_id)
            if not parent:
                break
            if parent.status == EventStatus.ERROR:
                return True
            current_parent_id = parent.parent_event_id
        
        return False


class SuccessRunDatabase:
    """
    Database of successful runs for comparison.
    """
    
    def __init__(self):
        self.success_runs: List[Dict[str, Any]] = []
    
    def add_success_run(self, run: Run, events: List[ExecutionEvent]):
        """Add a successful run to the database."""
        self.success_runs.append({
            'run': run,
            'events': events,
        })
    
    def get_similar_successful_events(
        self,
        event: ExecutionEvent,
        top_k: int = 5
    ) -> List[ExecutionEvent]:
        """
        Find similar events from successful runs.
        
        Args:
            event: Event to find similar events for
            top_k: Number of similar events to return
            
        Returns:
            List of similar events from successful runs
        """
        similar_events = []
        
        for run_data in self.success_runs:
            for success_event in run_data['events']:
                # Simple similarity: same component type and name
                if (success_event.component_type == event.component_type and
                    success_event.component_name == event.component_name):
                    similar_events.append(success_event)
        
        return similar_events[:top_k]
    
    def compute_output_anomaly_score(
        self,
        event: ExecutionEvent
    ) -> float:
        """
        Compute how anomalous an event's output is compared to successful runs.
        
        Args:
            event: Event to score
            
        Returns:
            Anomaly score (higher = more anomalous)
        """
        similar_events = self.get_similar_successful_events(event)
        
        if not similar_events:
            return 0.0
        
        # Simple anomaly: output differs from all similar successful events
        event_output_str = json.dumps(event.output, sort_keys=True) if event.output else ""
        
        matches = 0
        for similar in similar_events:
            similar_output_str = json.dumps(similar.output, sort_keys=True) if similar.output else ""
            if event_output_str == similar_output_str:
                matches += 1
        
        # Anomaly score: proportion of non-matches
        return 1.0 - (matches / len(similar_events))
