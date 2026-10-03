"""
Event collector for gathering and buffering execution events.
"""
import json
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from threading import Lock

from blackbox.events.schema import ExecutionEvent, EventStatus, ComponentType


class EventCollector:
    """
    Collects and buffers execution events.
    Thread-safe collection with optional callbacks.
    """
    
    def __init__(self, storage=None, max_payload_size: int = 10_000_000):
        """
        Initialize the event collector.
        
        Args:
            storage: Storage backend to persist events
            max_payload_size: Maximum size for event payloads (bytes)
        """
        self.storage = storage
        self.max_payload_size = max_payload_size
        self._events: List[ExecutionEvent] = []
        self._lock = Lock()
        self._callbacks: List[Callable] = []
        self._redactor: Optional[Callable] = None
    
    def collect(self, event: ExecutionEvent):
        """
        Collect an execution event.
        
        Args:
            event: The execution event to collect
        """
        # Apply redaction if configured
        if self._redactor:
            event = self._apply_redaction(event)
        
        # Truncate large payloads
        event = self._truncate_payloads(event)
        
        with self._lock:
            self._events.append(event)
        
        # Persist to storage if available
        if self.storage:
            try:
                self.storage.store_event(event)
            except Exception as e:
                # Log but don't fail the instrumentation
                print(f"Warning: Failed to store event: {e}")
        
        # Trigger callbacks
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"Warning: Event callback failed: {e}")
    
    def get_events(self, run_id: Optional[str] = None) -> List[ExecutionEvent]:
        """
        Get collected events, optionally filtered by run ID.
        
        Args:
            run_id: Optional run ID to filter by
            
        Returns:
            List of execution events
        """
        with self._lock:
            if run_id:
                return [e for e in self._events if e.run_id == run_id]
            return self._events.copy()
    
    def clear(self, run_id: Optional[str] = None):
        """
        Clear collected events.
        
        Args:
            run_id: Optional run ID to clear (clear all if None)
        """
        with self._lock:
            if run_id:
                self._events = [e for e in self._events if e.run_id != run_id]
            else:
                self._events.clear()
    
    def register_callback(self, callback: Callable):
        """
        Register a callback to be called when events are collected.
        
        Args:
            callback: Function to call with each event
        """
        self._callbacks.append(callback)
    
    def set_redactor(self, redactor: Callable):
        """
        Set a redactor function for sensitive data.
        
        Args:
            redactor: Function that takes data and returns redacted version
        """
        self._redactor = redactor
    
    def _apply_redaction(self, event: ExecutionEvent) -> ExecutionEvent:
        """Apply redaction to event data."""
        if event.input:
            event.input = self._redactor(event.input)
        if event.output:
            event.output = self._redactor(event.output)
        if event.state_before:
            event.state_before = self._redactor(event.state_before)
        if event.state_after:
            event.state_after = self._redactor(event.state_after)
        return event
    
    def _truncate_payloads(self, event: ExecutionEvent) -> ExecutionEvent:
        """Truncate large payloads to stay within size limits."""
        event.input = self._truncate_value(event.input)
        event.output = self._truncate_value(event.output)
        event.state_before = self._truncate_value(event.state_before)
        event.state_after = self._truncate_value(event.state_after)
        return event
    
    def _truncate_value(self, value: Any) -> Any:
        """Truncate a single value if too large."""
        if value is None:
            return value
        
        try:
            serialized = json.dumps(value)
            if len(serialized) > self.max_payload_size:
                return {
                    "_truncated": True,
                    "_original_size": len(serialized),
                    "_message": f"Payload truncated (exceeded {self.max_payload_size} bytes)"
                }
            return value
        except (TypeError, ValueError):
            # Non-serializable, return string representation
            str_repr = str(value)
            if len(str_repr) > 1000:
                str_repr = str_repr[:1000] + "..."
            return {"_repr": str_repr, "_type": type(value).__name__}
    
    def serialize_exception(self, exc: Exception) -> str:
        """
        Safely serialize an exception to a string.
        
        Args:
            exc: Exception to serialize
            
        Returns:
            String representation of the exception
        """
        try:
            return f"{type(exc).__name__}: {str(exc)}\n{''.join(traceback.format_tb(exc.__traceback__))}"
        except Exception:
            return f"{type(exc).__name__}: <unable to serialize exception>"


# Global singleton collector
_global_collector: Optional[EventCollector] = None


def get_global_collector() -> EventCollector:
    """Get or create the global event collector."""
    global _global_collector
    if _global_collector is None:
        _global_collector = EventCollector()
    return _global_collector


def set_global_collector(collector: EventCollector):
    """Set the global event collector."""
    global _global_collector
    _global_collector = collector
