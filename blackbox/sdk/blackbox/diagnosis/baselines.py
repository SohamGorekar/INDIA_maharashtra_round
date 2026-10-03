"""
Baseline models for failure diagnosis.
"""
import random
from typing import List, Dict, Any, Tuple
import numpy as np

from blackbox.events.schema import ExecutionEvent, Run, EventStatus


class BaselineDiagnoser:
    """Base class for baseline diagnosis methods."""
    
    def diagnose(self, run: Run, events: List[ExecutionEvent]) -> List[Tuple[str, float]]:
        """
        Diagnose a failed run.
        
        Args:
            run: The run
            events: All events in the run
            
        Returns:
            List of (event_id, score) tuples, sorted by score descending
        """
        raise NotImplementedError


class RandomBaselineDiagnoser(BaselineDiagnoser):
    """Random baseline - assigns random scores to all events."""
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        self.rng = random.Random(seed)
    
    def diagnose(self, run: Run, events: List[ExecutionEvent]) -> List[Tuple[str, float]]:
        """Randomly score all events."""
        scores = [
            (event.event_id, self.rng.random())
            for event in events
        ]
        return sorted(scores, key=lambda x: x[1], reverse=True)


class LastToolCallBaselineDiagnoser(BaselineDiagnoser):
    """Baseline that suspects the last tool call."""
    
    def diagnose(self, run: Run, events: List[ExecutionEvent]) -> List[Tuple[str, float]]:
        """Score events, with highest score to last tool call."""
        scores = []
        
        # Find last tool call
        last_tool_idx = -1
        for idx, event in enumerate(events):
            if event.component_type == 'tool':
                last_tool_idx = idx
        
        for idx, event in enumerate(events):
            if idx == last_tool_idx:
                score = 1.0
            else:
                score = 0.1
            scores.append((event.event_id, score))
        
        return sorted(scores, key=lambda x: x[1], reverse=True)


class FirstErrorBaselineDiagnoser(BaselineDiagnoser):
    """Baseline that suspects the first event that returned an error."""
    
    def diagnose(self, run: Run, events: List[ExecutionEvent]) -> List[Tuple[str, float]]:
        """Score events, with highest score to first error."""
        scores = []
        
        # Find first error
        first_error_idx = -1
        for idx, event in enumerate(events):
            if event.status == EventStatus.ERROR:
                first_error_idx = idx
                break
        
        for idx, event in enumerate(events):
            if idx == first_error_idx:
                score = 1.0
            elif event.status == EventStatus.ERROR:
                score = 0.5
            else:
                score = 0.1
            scores.append((event.event_id, score))
        
        return sorted(scores, key=lambda x: x[1], reverse=True)


class LastEventBaselineDiagnoser(BaselineDiagnoser):
    """Baseline that suspects the last event."""
    
    def diagnose(self, run: Run, events: List[ExecutionEvent]) -> List[Tuple[str, float]]:
        """Score events, with highest score to last event."""
        scores = []
        
        for idx, event in enumerate(events):
            # Score decreases as we go back in time
            score = (idx + 1) / len(events)
            scores.append((event.event_id, score))
        
        return sorted(scores, key=lambda x: x[1], reverse=True)


class HeuristicDiagnoser(BaselineDiagnoser):
    """
    Heuristic-based diagnoser combining multiple signals.
    """
    
    def diagnose(self, run: Run, events: List[ExecutionEvent]) -> List[Tuple[str, float]]:
        """Score events using heuristics."""
        scores = []
        
        for event in events:
            score = 0.0
            
            # Error events are highly suspicious
            if event.status == EventStatus.ERROR:
                score += 0.5
            
            # Later events are more suspicious
            score += 0.2 * (event.sequence_number / len(events))
            
            # Tool calls are more suspicious than other components
            if event.component_type == 'tool':
                score += 0.2
            
            # Events with empty output are suspicious
            if event.output is None or event.output == {}:
                score += 0.1
            
            scores.append((event.event_id, score))
        
        return sorted(scores, key=lambda x: x[1], reverse=True)


def get_baseline_diagnoser(baseline_name: str) -> BaselineDiagnoser:
    """
    Get a baseline diagnoser by name.
    
    Args:
        baseline_name: Name of the baseline
        
    Returns:
        BaselineDiagnoser instance
    """
    baselines = {
        'random': RandomBaselineDiagnoser,
        'last_tool': LastToolCallBaselineDiagnoser,
        'first_error': FirstErrorBaselineDiagnoser,
        'last_event': LastEventBaselineDiagnoser,
        'heuristic': HeuristicDiagnoser,
    }
    
    if baseline_name not in baselines:
        raise ValueError(f"Unknown baseline: {baseline_name}")
    
    return baselines[baseline_name]()
