"""
Evidence generation for diagnosis explanations.
"""
import uuid
from typing import List, Dict, Any
import json

from blackbox.events.schema import (
    ExecutionEvent,
    Run,
    Diagnosis,
    Evidence,
    EvidenceType,
    EventStatus,
)
from blackbox.storage.interface import StorageBackend


class EvidenceGenerator:
    """
    Generates structured evidence supporting diagnosis results.
    """
    
    def __init__(self, storage: StorageBackend = None):
        self.storage = storage
    
    def generate_evidence(
        self,
        diagnosis: Diagnosis,
        run: Run,
        events: List[ExecutionEvent],
        success_runs: List[Dict[str, Any]] = None
    ) -> List[Evidence]:
        """
        Generate evidence supporting a diagnosis.
        
        Args:
            diagnosis: The diagnosis
            run: The failed run
            events: All events in the run
            success_runs: Optional list of successful runs for comparison
            
        Returns:
            List of Evidence objects
        """
        evidence_list = []
        
        if not diagnosis.suspected_event_id:
            return evidence_list
        
        # Find the suspected event
        suspected_event = None
        event_map = {e.event_id: e for e in events}
        suspected_event = event_map.get(diagnosis.suspected_event_id)
        
        if not suspected_event:
            return evidence_list
        
        # Generate different types of evidence
        evidence_list.extend(self._generate_error_evidence(
            diagnosis, suspected_event, events
        ))
        
        evidence_list.extend(self._generate_output_anomaly_evidence(
            diagnosis, suspected_event, success_runs
        ))
        
        evidence_list.extend(self._generate_state_change_evidence(
            diagnosis, suspected_event
        ))
        
        evidence_list.extend(self._generate_downstream_evidence(
            diagnosis, suspected_event, events
        ))
        
        evidence_list.extend(self._generate_latency_evidence(
            diagnosis, suspected_event, events
        ))
        
        # Store evidence
        if self.storage:
            for evidence in evidence_list:
                try:
                    self.storage.store_evidence(evidence)
                except Exception as e:
                    print(f"Warning: Failed to store evidence: {e}")
        
        return evidence_list
    
    def _generate_error_evidence(
        self,
        diagnosis: Diagnosis,
        suspected_event: ExecutionEvent,
        all_events: List[ExecutionEvent]
    ) -> List[Evidence]:
        """Generate evidence from errors."""
        evidence_list = []
        
        if suspected_event.status == EventStatus.ERROR:
            evidence = Evidence(
                evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
                diagnosis_id=diagnosis.diagnosis_id,
                event_id=suspected_event.event_id,
                evidence_type=EvidenceType.ERROR,
                description=f"Event returned an error: {suspected_event.error or 'Unknown error'}",
                observed_value=suspected_event.error,
                expected_value="No error",
                source_event_ids=[suspected_event.event_id],
                strength=0.9,
            )
            evidence_list.append(evidence)
        
        return evidence_list
    
    def _generate_output_anomaly_evidence(
        self,
        diagnosis: Diagnosis,
        suspected_event: ExecutionEvent,
        success_runs: List[Dict[str, Any]] = None
    ) -> List[Evidence]:
        """Generate evidence from output anomalies."""
        evidence_list = []
        
        if not success_runs:
            return evidence_list
        
        # Find similar events in successful runs
        similar_outputs = []
        for run_data in success_runs:
            for event in run_data.get('events', []):
                if (event.component_name == suspected_event.component_name and
                    event.component_type == suspected_event.component_type):
                    similar_outputs.append(event.output)
        
        if similar_outputs:
            # Check if output differs
            output_matches = sum(
                1 for out in similar_outputs
                if json.dumps(out, sort_keys=True) == json.dumps(suspected_event.output, sort_keys=True)
            )
            
            if output_matches == 0:
                evidence = Evidence(
                    evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
                    diagnosis_id=diagnosis.diagnosis_id,
                    event_id=suspected_event.event_id,
                    evidence_type=EvidenceType.DEVIATION_FROM_SUCCESS,
                    description="Output differs substantially from successful executions.",
                    observed_value=suspected_event.output,
                    expected_value=similar_outputs[0] if similar_outputs else None,
                    source_event_ids=[suspected_event.event_id],
                    strength=0.82,
                )
                evidence_list.append(evidence)
        
        return evidence_list
    
    def _generate_state_change_evidence(
        self,
        diagnosis: Diagnosis,
        suspected_event: ExecutionEvent
    ) -> List[Evidence]:
        """Generate evidence from unexpected state changes."""
        evidence_list = []
        
        if suspected_event.state_before and suspected_event.state_after:
            # Check for significant state changes
            before_str = json.dumps(suspected_event.state_before, sort_keys=True)
            after_str = json.dumps(suspected_event.state_after, sort_keys=True)
            
            if before_str != after_str:
                evidence = Evidence(
                    evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
                    diagnosis_id=diagnosis.diagnosis_id,
                    event_id=suspected_event.event_id,
                    evidence_type=EvidenceType.STATE_CHANGE,
                    description="Event caused unexpected state changes.",
                    observed_value=suspected_event.state_after,
                    expected_value=suspected_event.state_before,
                    source_event_ids=[suspected_event.event_id],
                    strength=0.6,
                )
                evidence_list.append(evidence)
        
        return evidence_list
    
    def _generate_downstream_evidence(
        self,
        diagnosis: Diagnosis,
        suspected_event: ExecutionEvent,
        all_events: List[ExecutionEvent]
    ) -> List[Evidence]:
        """Generate evidence from downstream dependencies."""
        evidence_list = []
        
        # Find downstream errors
        downstream_errors = [
            e for e in all_events
            if e.sequence_number > suspected_event.sequence_number
            and e.status == EventStatus.ERROR
        ]
        
        if downstream_errors:
            evidence = Evidence(
                evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
                diagnosis_id=diagnosis.diagnosis_id,
                event_id=suspected_event.event_id,
                evidence_type=EvidenceType.DOWNSTREAM_DEPENDENCY,
                description=f"Event preceded {len(downstream_errors)} downstream error(s).",
                observed_value=len(downstream_errors),
                expected_value=0,
                source_event_ids=[e.event_id for e in downstream_errors],
                strength=0.7,
            )
            evidence_list.append(evidence)
        
        return evidence_list
    
    def _generate_latency_evidence(
        self,
        diagnosis: Diagnosis,
        suspected_event: ExecutionEvent,
        all_events: List[ExecutionEvent]
    ) -> List[Evidence]:
        """Generate evidence from latency anomalies."""
        evidence_list = []
        
        # Compute average latency for same component type
        same_type_events = [
            e for e in all_events
            if e.component_type == suspected_event.component_type
            and e.duration_ms is not None
        ]
        
        if same_type_events and suspected_event.duration_ms:
            avg_duration = sum(e.duration_ms for e in same_type_events) / len(same_type_events)
            
            # Check if significantly slower
            if suspected_event.duration_ms > 3 * avg_duration:
                evidence = Evidence(
                    evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
                    diagnosis_id=diagnosis.diagnosis_id,
                    event_id=suspected_event.event_id,
                    evidence_type=EvidenceType.LATENCY_ANOMALY,
                    description=f"Event took {suspected_event.duration_ms:.0f}ms, significantly longer than average {avg_duration:.0f}ms.",
                    observed_value=suspected_event.duration_ms,
                    expected_value=avg_duration,
                    source_event_ids=[suspected_event.event_id],
                    strength=0.65,
                )
                evidence_list.append(evidence)
        
        return evidence_list
