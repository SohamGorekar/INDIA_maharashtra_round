"""
Trace decorator for automatic instrumentation of functions and methods.
"""
import asyncio
import functools
import inspect
import time
from datetime import datetime
from typing import Any, Callable, Optional, Dict

from blackbox.events.schema import ExecutionEvent, ComponentType, EventStatus
from blackbox.events.collector import get_global_collector
from blackbox.instrumentation.context import (
    get_current_run_id,
    get_current_parent_event_id,
    get_next_sequence_number,
    generate_event_id,
    generate_component_id,
)


def trace(
    type: str = "function",
    name: Optional[str] = None,
    capture_state: bool = False,
    side_effect: str = "READ",
):
    """
    Decorator for tracing function execution.
    
    Args:
        type: Component type (tool, llm, agent, function, etc.)
        name: Optional custom name (defaults to function name)
        capture_state: Whether to capture state before/after
        side_effect: Side effect classification (READ, WRITE, EXTERNAL_SIDE_EFFECT)
    
    Example:
        @trace(type="tool")
        def search_web(query: str):
            return web_search(query)
        
        @trace(type="llm", name="gpt4")
        async def generate(prompt: str):
            return await llm_call(prompt)
    """
    def decorator(func: Callable) -> Callable:
        func_name = name or func.__name__
        
        # Determine if function is async
        is_async = asyncio.iscoroutinefunction(func)
        
        if is_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await _execute_traced(
                    func, func_name, type, capture_state, side_effect,
                    True, args, kwargs
                )
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                return _execute_traced(
                    func, func_name, type, capture_state, side_effect,
                    False, args, kwargs
                )
            return sync_wrapper
    
    return decorator


def _execute_traced(
    func: Callable,
    func_name: str,
    component_type: str,
    capture_state: bool,
    side_effect: str,
    is_async: bool,
    args: tuple,
    kwargs: dict,
) -> Any:
    """Execute a function with tracing."""
    # Get current context
    run_id = get_current_run_id()
    if not run_id:
        # No active run, execute without tracing
        if is_async:
            import asyncio
            return asyncio.create_task(func(*args, **kwargs))
        return func(*args, **kwargs)
    
    parent_event_id = get_current_parent_event_id()
    sequence_number = get_next_sequence_number()
    event_id = generate_event_id()
    component_id = generate_component_id(func_name)
    
    # Prepare event
    event = ExecutionEvent(
        event_id=event_id,
        run_id=run_id,
        parent_event_id=parent_event_id,
        sequence_number=sequence_number,
        component_id=component_id,
        component_name=func_name,
        component_type=_component_type(component_type),
        input=_serialize_call_args(func, args, kwargs),
        output=None,
        state_before=None,
        state_after=None,
        status=EventStatus.RUNNING,
        error=None,
        started_at=datetime.utcnow(),
        finished_at=None,
        duration_ms=None,
        checkpoint_id=None,
        metadata={
            "side_effect": side_effect,
            "is_async": is_async,
        }
    )
    
    # Update parent context
    from blackbox.instrumentation.context import _current_parent_event_id
    token = _current_parent_event_id.set(event_id)
    collector = get_global_collector()
    collector.publish_lifecycle("event_started", run_id, event=event)
    
    start_time = time.perf_counter()
    
    try:
        if is_async:
            # Async execution
            result = asyncio.ensure_future(_execute_async_traced(
                func, event, start_time, token, args, kwargs
            ))
            return result
        else:
            # Sync execution
            result = func(*args, **kwargs)
            
            # Update event with success
            end_time = time.perf_counter()
            event.output = _serialize_output(result)
            event.status = EventStatus.SUCCESS
            event.finished_at = datetime.utcnow()
            event.duration_ms = (end_time - start_time) * 1000
            
            # Collect event
            collector.collect(event)
            
            # Restore parent context
            _current_parent_event_id.reset(token)
            
            return result
    
    except Exception as exc:
        # Update event with error
        end_time = time.perf_counter()
        event.status = EventStatus.ERROR
        event.error = collector.serialize_exception(exc)
        event.finished_at = datetime.utcnow()
        event.duration_ms = (end_time - start_time) * 1000
        
        # Collect event
        collector.collect(event)
        
        # Restore parent context
        _current_parent_event_id.reset(token)
        
        # Re-raise exception
        raise


def _component_type(value: str) -> ComponentType:
    """Convert a decorator type to the schema enum without losing valid types."""
    try:
        return ComponentType(value)
    except ValueError:
        return ComponentType.CUSTOM


async def _execute_async_traced(
    func: Callable,
    event: ExecutionEvent,
    start_time: float,
    token,
    args: tuple,
    kwargs: dict,
) -> Any:
    """Execute async function with tracing."""
    from blackbox.instrumentation.context import _current_parent_event_id
    collector = get_global_collector()
    
    try:
        result = await func(*args, **kwargs)
        
        # Update event with success
        end_time = time.perf_counter()
        event.output = _serialize_output(result)
        event.status = EventStatus.SUCCESS
        event.finished_at = datetime.utcnow()
        event.duration_ms = (end_time - start_time) * 1000
        
        # Collect event
        collector.collect(event)
        
        # Restore parent context
        _current_parent_event_id.reset(token)
        
        return result
    
    except Exception as exc:
        # Update event with error
        end_time = time.perf_counter()
        event.status = EventStatus.ERROR
        event.error = collector.serialize_exception(exc)
        event.finished_at = datetime.utcnow()
        event.duration_ms = (end_time - start_time) * 1000
        
        # Collect event
        collector.collect(event)
        
        # Restore parent context
        _current_parent_event_id.reset(token)
        
        # Re-raise exception
        raise


def _serialize_call_args(func: Callable, args: tuple, kwargs: dict) -> Dict[str, Any]:
    """Serialize function call arguments."""
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        
        serialized = {}
        for param_name, param_value in bound.arguments.items():
            serialized[param_name] = _make_serializable(param_value)
        
        return serialized
    except Exception:
        # Fallback to positional/keyword format
        return {
            "args": [_make_serializable(a) for a in args],
            "kwargs": {k: _make_serializable(v) for k, v in kwargs.items()}
        }


def _serialize_output(result: Any) -> Any:
    """Serialize function output."""
    return _make_serializable(result)


def _make_serializable(obj: Any) -> Any:
    """Convert object to JSON-serializable form."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]
    
    if isinstance(obj, dict):
        return {str(k): _make_serializable(v) for k, v in obj.items()}
    
    # Try to get dict representation
    if hasattr(obj, '__dict__'):
        try:
            return {
                "_type": type(obj).__name__,
                "_module": type(obj).__module__,
                **{k: _make_serializable(v) for k, v in obj.__dict__.items()}
            }
        except Exception:
            pass
    
    # Fallback to string representation
    try:
        str_repr = str(obj)
        if len(str_repr) > 500:
            str_repr = str_repr[:500] + "..."
        return {"_repr": str_repr, "_type": type(obj).__name__}
    except Exception:
        return {"_repr": "<unserializable>", "_type": type(obj).__name__}
