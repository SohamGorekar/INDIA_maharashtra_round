"""
Black Box SDK - Execution instrumentation and failure diagnosis for agent systems.
"""
from blackbox.events.schema import (
    ExecutionEvent,
    Run,
    Checkpoint,
    Diagnosis,
    Evidence,
    ComponentType,
    EventStatus,
    RunOutcome,
    RunStatus,
    DiagnosisStatus,
    EvidenceType,
    SideEffectType,
)
from blackbox.instrumentation.decorator import trace
from blackbox.instrumentation.context import BlackBoxContext, get_current_run_id, set_current_run_id

__version__ = "0.1.0"

__all__ = [
    # Core decorator
    "trace",
    
    # Context
    "BlackBoxContext",
    "get_current_run_id",
    "set_current_run_id",
    
    # Schemas
    "ExecutionEvent",
    "Run",
    "Checkpoint",
    "Diagnosis",
    "Evidence",
    
    # Enums
    "ComponentType",
    "EventStatus",
    "RunOutcome",
    "RunStatus",
    "DiagnosisStatus",
    "EvidenceType",
    "SideEffectType",
]
