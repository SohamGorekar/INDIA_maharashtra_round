"""
Context management for Black Box instrumentation.
Handles run tracking, parent-child relationships, and thread-local state.
"""
import contextvars
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Callable
from dataclasses import dataclass, field

from blackbox.events.schema import RunStatus, RunOutcome


# Context variables for tracking current execution
_current_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'blackbox_run_id', default=None
)
_current_parent_event_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    'blackbox_parent_event_id', default=None
)
_current_sequence_number: contextvars.ContextVar[int] = contextvars.ContextVar(
    'blackbox_sequence_number', default=0
)


@dataclass
class BlackBoxContext:
    """
    Context for a Black Box execution run.
    Manages run-level state and event tracking.
    """
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    parent_run_id: Optional[str] = None
    task_input: Optional[Dict[str, Any]] = None
    status: RunStatus = RunStatus.RUNNING
    outcome: RunOutcome = RunOutcome.UNKNOWN
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Internal tracking
    _sequence_counter: int = field(default=0, init=False)
    _event_stack: list = field(default_factory=list, init=False)
    
    # Callbacks
    _redactor: Optional[Callable] = field(default=None, init=False)
    
    def __enter__(self):
        """Enter context and set as current run."""
        self._token = _current_run_id.set(self.run_id)
        self._seq_token = _current_sequence_number.set(0)
        self._parent_token = _current_parent_event_id.set(None)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and restore previous state."""
        if exc_type is not None:
            self.status = RunStatus.FAILED
        else:
            self.status = RunStatus.COMPLETED
        
        self.finished_at = datetime.utcnow()
        _current_run_id.reset(self._token)
        _current_sequence_number.reset(self._seq_token)
        _current_parent_event_id.reset(self._parent_token)
        return False
    
    def next_sequence_number(self) -> int:
        """Get the next sequence number for an event."""
        self._sequence_counter += 1
        current = _current_sequence_number.get()
        _current_sequence_number.set(current + 1)
        return self._sequence_counter
    
    def push_event(self, event_id: str):
        """Push an event onto the stack (entering nested execution)."""
        self._event_stack.append(event_id)
        _current_parent_event_id.set(event_id)
    
    def pop_event(self):
        """Pop an event from the stack (exiting nested execution)."""
        if self._event_stack:
            self._event_stack.pop()
        parent = self._event_stack[-1] if self._event_stack else None
        _current_parent_event_id.set(parent)
    
    def set_redactor(self, redactor: Callable):
        """Set a redactor function for sensitive data."""
        self._redactor = redactor
    
    def redact(self, data: Any) -> Any:
        """Apply redaction to data if redactor is configured."""
        if self._redactor:
            return self._redactor(data)
        return data


# Global singleton for when no explicit context is provided
_global_context: Optional[BlackBoxContext] = None


def get_current_context() -> Optional[BlackBoxContext]:
    """Get the current Black Box context."""
    return _global_context


def set_current_context(context: BlackBoxContext):
    """Set the global context."""
    global _global_context
    _global_context = context


def get_current_run_id() -> Optional[str]:
    """Get the current run ID from context."""
    return _current_run_id.get()


def set_current_run_id(run_id: str):
    """Set the current run ID in context."""
    _current_run_id.set(run_id)


def get_current_parent_event_id() -> Optional[str]:
    """Get the current parent event ID from context."""
    return _current_parent_event_id.get()


def get_next_sequence_number() -> int:
    """Get and increment the sequence number."""
    current = _current_sequence_number.get()
    _current_sequence_number.set(current + 1)
    return current + 1


def generate_event_id() -> str:
    """Generate a unique event ID."""
    return f"evt_{uuid.uuid4().hex[:12]}"


def generate_component_id(component_name: str) -> str:
    """Generate a unique component ID."""
    return f"{component_name}_{uuid.uuid4().hex[:8]}"
