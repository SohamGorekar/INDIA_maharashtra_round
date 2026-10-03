"""
Fault injection for generating training data.
"""
import copy
import random
import uuid
from typing import List, Dict, Any, Optional
from enum import Enum

from blackbox.events.schema import ExecutionEvent, Run, EventStatus, RunOutcome


class FaultType(str, Enum):
    """Types of faults that can be injected."""
    CORRUPT_INPUT = "CORRUPT_INPUT"
    CORRUPT_OUTPUT = "CORRUPT_OUTPUT"
    REMOVE_STEP = "REMOVE_STEP"
    DUPLICATE_STEP = "DUPLICATE_STEP"
    CHANGE_ARGUMENT = "CHANGE_ARGUMENT"
    INJECT_ERROR = "INJECT_ERROR"
    DELAY_RESPONSE = "DELAY_RESPONSE"
    MODIFY_STATE = "MODIFY_STATE"


class FaultInjectionRecord:
    """Record of an injected fault."""
    
    def __init__(
        self,
        fault_id: str,
        fault_type: FaultType,
        fault_event_id: str,
        is_culprit: bool,
        original_value: Any,
        injected_value: Any,
        metadata: Dict[str, Any] = None
    ):
        self.fault_id = fault_id
        self.fault_type = fault_type
        self.fault_event_id = fault_event_id
        self.is_culprit = is_culprit
        self.original_value = original_value
        self.injected_value = injected_value
        self.metadata = metadata or {}


class FaultInjector:
    """
    Injects faults into execution traces to generate training data.
    """
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
    
    def inject_fault(
        self,
        run: Run,
        events: List[ExecutionEvent],
        fault_type: Optional[FaultType] = None,
        target_event_idx: Optional[int] = None
    ) -> tuple:
        """
        Inject a fault into a run.
        
        Args:
            run: The original run
            events: List of events in the run
            fault_type: Type of fault to inject (random if None)
            target_event_idx: Index of event to inject fault into (random if None)
            
        Returns:
            Tuple of (modified_run, modified_events, fault_record)
        """
        if not events:
            raise ValueError("Cannot inject fault into empty event list")
        
        # Select fault type
        if fault_type is None:
            fault_type = self.rng.choice(list(FaultType))
        
        # Select target event
        if target_event_idx is None:
            target_event_idx = self.rng.randint(0, len(events) - 1)
        
        # Create copies
        modified_run = copy.deepcopy(run)
        modified_events = copy.deepcopy(events)
        target_event = modified_events[target_event_idx]
        
        # Inject fault
        fault_record = None
        
        if fault_type == FaultType.CORRUPT_OUTPUT:
            fault_record = self._corrupt_output(target_event)
        elif fault_type == FaultType.CORRUPT_INPUT:
            fault_record = self._corrupt_input(target_event)
        elif fault_type == FaultType.INJECT_ERROR:
            fault_record = self._inject_error(target_event)
        elif fault_type == FaultType.CHANGE_ARGUMENT:
            fault_record = self._change_argument(target_event)
        elif fault_type == FaultType.MODIFY_STATE:
            fault_record = self._modify_state(target_event)
        elif fault_type == FaultType.DELAY_RESPONSE:
            fault_record = self._delay_response(target_event)
        else:
            # Fallback to output corruption
            fault_record = self._corrupt_output(target_event)
        
        # Update run outcome
        # Determine if fault affects final outcome
        # This is simplified - in reality, would need to re-execute
        is_culprit = self._is_culprit(target_event, events, fault_type)
        fault_record.is_culprit = is_culprit
        
        if is_culprit:
            modified_run.outcome = RunOutcome.FAILURE
        else:
            modified_run.outcome = RunOutcome.BENIGN
        
        # Update run ID to mark as synthetic
        modified_run.run_id = f"fault_{uuid.uuid4().hex[:12]}"
        modified_run.metadata['is_synthetic'] = True
        modified_run.metadata['original_run_id'] = run.run_id
        modified_run.metadata['fault_injected'] = True
        modified_run.metadata['fault_type'] = fault_type
        modified_run.metadata['fault_event_id'] = target_event.event_id
        
        return modified_run, modified_events, fault_record
    
    def _corrupt_output(self, event: ExecutionEvent) -> FaultInjectionRecord:
        """Corrupt the output of an event."""
        original_output = copy.deepcopy(event.output)
        
        if event.output and isinstance(event.output, dict):
            # Change a random key's value
            keys = list(event.output.keys())
            if keys:
                key = self.rng.choice(keys)
                event.output[key] = "CORRUPTED_VALUE"
        else:
            event.output = {"corrupted": True}
        
        return FaultInjectionRecord(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type=FaultType.CORRUPT_OUTPUT,
            fault_event_id=event.event_id,
            is_culprit=False,  # Will be determined later
            original_value=original_output,
            injected_value=event.output,
        )
    
    def _corrupt_input(self, event: ExecutionEvent) -> FaultInjectionRecord:
        """Corrupt the input of an event."""
        original_input = copy.deepcopy(event.input)
        
        if event.input and isinstance(event.input, dict):
            keys = list(event.input.keys())
            if keys:
                key = self.rng.choice(keys)
                event.input[key] = None
        else:
            event.input = {}
        
        return FaultInjectionRecord(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type=FaultType.CORRUPT_INPUT,
            fault_event_id=event.event_id,
            is_culprit=False,
            original_value=original_input,
            injected_value=event.input,
        )
    
    def _inject_error(self, event: ExecutionEvent) -> FaultInjectionRecord:
        """Inject an error into an event."""
        original_status = event.status
        original_error = event.error
        
        event.status = EventStatus.ERROR
        event.error = "Injected error for testing"
        
        return FaultInjectionRecord(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type=FaultType.INJECT_ERROR,
            fault_event_id=event.event_id,
            is_culprit=False,
            original_value={"status": original_status, "error": original_error},
            injected_value={"status": event.status, "error": event.error},
        )
    
    def _change_argument(self, event: ExecutionEvent) -> FaultInjectionRecord:
        """Change an argument in the event input."""
        return self._corrupt_input(event)  # Similar to input corruption
    
    def _modify_state(self, event: ExecutionEvent) -> FaultInjectionRecord:
        """Modify the state after an event."""
        original_state = copy.deepcopy(event.state_after)
        
        if event.state_after and isinstance(event.state_after, dict):
            keys = list(event.state_after.keys())
            if keys:
                key = self.rng.choice(keys)
                event.state_after[key] = "MODIFIED_STATE"
        else:
            event.state_after = {"modified": True}
        
        return FaultInjectionRecord(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type=FaultType.MODIFY_STATE,
            fault_event_id=event.event_id,
            is_culprit=False,
            original_value=original_state,
            injected_value=event.state_after,
        )
    
    def _delay_response(self, event: ExecutionEvent) -> FaultInjectionRecord:
        """Simulate a delayed response."""
        original_duration = event.duration_ms
        
        # Multiply duration by 10
        if event.duration_ms:
            event.duration_ms = event.duration_ms * 10
        else:
            event.duration_ms = 10000  # 10 seconds
        
        return FaultInjectionRecord(
            fault_id=f"fault_{uuid.uuid4().hex[:8]}",
            fault_type=FaultType.DELAY_RESPONSE,
            fault_event_id=event.event_id,
            is_culprit=False,
            original_value=original_duration,
            injected_value=event.duration_ms,
        )
    
    def _is_culprit(
        self,
        target_event: ExecutionEvent,
        all_events: List[ExecutionEvent],
        fault_type: FaultType
    ) -> bool:
        """
        Determine if the injected fault is the culprit.
        
        Simplified heuristic: tool/llm calls in the middle of execution
        are more likely to be culprits.
        """
        # Error injections are usually culprits
        if fault_type == FaultType.INJECT_ERROR:
            return self.rng.random() > 0.2  # 80% chance
        
        # Output corruptions are often culprits
        if fault_type == FaultType.CORRUPT_OUTPUT:
            return self.rng.random() > 0.3  # 70% chance
        
        # Others are less likely to be culprits
        return self.rng.random() > 0.6  # 40% chance


def generate_fault_injected_dataset(
    successful_runs: List[Dict[str, Any]],
    num_faults_per_run: int = 3,
    seed: int = 42
) -> List[Dict[str, Any]]:
    """
    Generate a dataset of fault-injected runs.
    
    Args:
        successful_runs: List of successful runs (each with 'run' and 'events')
        num_faults_per_run: Number of faults to inject per run
        seed: Random seed
        
    Returns:
        List of fault-injected runs with ground truth labels
    """
    injector = FaultInjector(seed=seed)
    fault_runs = []
    
    for run_data in successful_runs:
        run = run_data['run']
        events = run_data['events']
        
        for _ in range(num_faults_per_run):
            modified_run, modified_events, fault_record = injector.inject_fault(
                run, events
            )
            
            fault_runs.append({
                'run': modified_run,
                'events': modified_events,
                'fault_record': fault_record,
                'culprit_event_id': fault_record.fault_event_id if fault_record.is_culprit else None,
                'is_benign': not fault_record.is_culprit,
            })
    
    return fault_runs
