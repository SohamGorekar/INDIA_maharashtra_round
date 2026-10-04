"""
Core event and run schemas for Black Box instrumentation.
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ComponentType(str, Enum):
    """Types of components that can be traced."""
    AGENT = "agent"
    TOOL = "tool"
    LLM = "llm"
    RETRIEVER = "retriever"
    ROUTER = "router"
    FUNCTION = "function"
    CUSTOM = "custom"


class EventStatus(str, Enum):
    """Status of an execution event."""
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"
    CACHED = "cached"


class RunOutcome(str, Enum):
    """Overall outcome classification for a run."""
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    BENIGN = "BENIGN"
    UNKNOWN = "UNKNOWN"


class RunStatus(str, Enum):
    """Status of a run."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionEvent(BaseModel):
    """
    Universal execution event schema.
    Represents a single step/component execution in the trace.
    """
    event_id: str = Field(..., description="Unique identifier for this event")
    run_id: str = Field(..., description="ID of the parent run")
    parent_event_id: Optional[str] = Field(None, description="ID of parent event if nested")
    sequence_number: int = Field(..., description="Sequential order within the run")
    
    # Component identification
    component_id: str = Field(..., description="Unique ID for the component")
    component_name: str = Field(..., description="Human-readable component name")
    component_type: ComponentType = Field(..., description="Type of component")
    
    # Execution data
    input: Optional[Dict[str, Any]] = Field(None, description="Input to the component")
    output: Optional[Dict[str, Any]] = Field(None, description="Output from the component")
    
    # State tracking
    state_before: Optional[Dict[str, Any]] = Field(None, description="State before execution")
    state_after: Optional[Dict[str, Any]] = Field(None, description="State after execution")
    
    # Status tracking
    status: EventStatus = Field(..., description="Execution status")
    error: Optional[str] = Field(None, description="Error message if status is ERROR")
    
    # Timing
    started_at: datetime = Field(..., description="When execution started")
    finished_at: Optional[datetime] = Field(None, description="When execution finished")
    duration_ms: Optional[float] = Field(None, description="Duration in milliseconds")
    
    # Checkpoint
    checkpoint_id: Optional[str] = Field(None, description="Associated checkpoint ID")
    
    # Extensibility
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Run(BaseModel):
    """
    Run-level schema tracking an entire execution.
    """
    run_id: str = Field(..., description="Unique identifier for this run")
    parent_run_id: Optional[str] = Field(None, description="Parent run ID if nested")
    task_input: Optional[Dict[str, Any]] = Field(None, description="Initial task input")
    
    # Status tracking
    status: RunStatus = Field(..., description="Current run status")
    outcome: RunOutcome = Field(default=RunOutcome.UNKNOWN, description="Final outcome classification")
    
    # Timing
    started_at: datetime = Field(..., description="When run started")
    finished_at: Optional[datetime] = Field(None, description="When run finished")
    duration_ms: Optional[float] = Field(None, description="Total duration in milliseconds")
    
    # Structure
    root_event_id: Optional[str] = Field(None, description="ID of the root event")
    event_count: int = Field(default=0, description="Total number of events")
    
    # Diagnosis
    diagnosis: Optional[Dict[str, Any]] = Field(None, description="Diagnosis result if available")
    
    # Extensibility
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Checkpoint(BaseModel):
    """
    Checkpoint schema for state snapshots.
    """
    checkpoint_id: str = Field(..., description="Unique checkpoint identifier")
    run_id: str = Field(..., description="Associated run ID")
    event_id: str = Field(..., description="Event at which checkpoint was taken")
    sequence_number: int = Field(..., description="Sequence number in the run")
    
    # State
    state: Dict[str, Any] = Field(..., description="Serialized state snapshot")
    state_hash: str = Field(..., description="Hash of the state for verification")
    
    # Metadata
    created_at: datetime = Field(..., description="When checkpoint was created")
    storage_reference: Optional[str] = Field(None, description="Reference to external storage if needed")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class DiagnosisStatus(str, Enum):
    """Status of a diagnosis."""
    CULPRIT = "CULPRIT"
    BENIGN = "BENIGN"
    UNCERTAIN = "UNCERTAIN"


class EventRanking(BaseModel):
    """Ranking of a single event in diagnosis."""
    event_id: str
    score: float
    rank: int


class Diagnosis(BaseModel):
    """
    Failure diagnosis result.
    """
    diagnosis_id: str = Field(..., description="Unique diagnosis identifier")
    run_id: str = Field(..., description="Associated run ID")
    
    # Results
    status: DiagnosisStatus = Field(..., description="Diagnosis status")
    suspected_event_id: Optional[str] = Field(None, description="Most suspected event")
    suspected_event_ids: List[str] = Field(
        default_factory=list,
        description="Events selected as suspected failures",
    )
    confidence: float = Field(..., description="Confidence score (0-1)")
    
    # Rankings
    rankings: List[EventRanking] = Field(default_factory=list, description="Ranked list of events")
    
    # Model info
    model_name: str = Field(..., description="Name of the diagnosis model")
    model_version: str = Field(..., description="Version of the diagnosis model")
    
    # Metadata
    created_at: datetime = Field(..., description="When diagnosis was created")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class EvidenceType(str, Enum):
    """Types of evidence supporting a diagnosis."""
    OUTPUT_ANOMALY = "OUTPUT_ANOMALY"
    STATE_CHANGE = "STATE_CHANGE"
    ERROR = "ERROR"
    MISSING_STEP = "MISSING_STEP"
    DEVIATION_FROM_SUCCESS = "DEVIATION_FROM_SUCCESS"
    UNEXPECTED_SEQUENCE = "UNEXPECTED_SEQUENCE"
    LATENCY_ANOMALY = "LATENCY_ANOMALY"
    DOWNSTREAM_DEPENDENCY = "DOWNSTREAM_DEPENDENCY"


class Evidence(BaseModel):
    """
    Evidence supporting a diagnosis.
    """
    evidence_id: str = Field(..., description="Unique evidence identifier")
    diagnosis_id: str = Field(..., description="Associated diagnosis ID")
    event_id: str = Field(..., description="Event this evidence relates to")
    
    # Evidence details
    evidence_type: EvidenceType = Field(..., description="Type of evidence")
    description: str = Field(..., description="Human-readable description")
    
    # Comparative data
    observed_value: Optional[Any] = Field(None, description="Observed value")
    expected_value: Optional[Any] = Field(None, description="Expected value")
    
    # Supporting events
    source_event_ids: List[str] = Field(default_factory=list, description="Supporting event IDs")
    strength: float = Field(..., description="Strength of evidence (0-1)")
    
    class Config:
        use_enum_values = True


class SideEffectType(str, Enum):
    """Classification of side effects for replay safety."""
    READ = "READ"
    WRITE = "WRITE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


class ReplayRun(BaseModel):
    """
    Replay execution metadata.
    """
    replay_run_id: str = Field(..., description="Unique replay run identifier")
    original_run_id: str = Field(..., description="Original run being replayed")
    checkpoint_id: str = Field(..., description="Checkpoint from which replay started")
    
    # Execution stats
    steps_reused: int = Field(..., description="Number of steps reused from cache")
    steps_reexecuted: int = Field(..., description="Number of steps re-executed")
    outcome: RunOutcome = Field(..., description="Final outcome")
    
    # Metadata
    created_at: datetime = Field(..., description="When replay was executed")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class CounterfactualRun(BaseModel):
    """
    Counterfactual execution metadata.
    """
    counterfactual_run_id: str = Field(..., description="Unique counterfactual run identifier")
    original_run_id: str = Field(..., description="Original run")
    modified_event_id: str = Field(..., description="Event that was modified")
    patch: Dict[str, Any] = Field(..., description="Patch applied to the event")
    
    # Results
    outcome: RunOutcome = Field(..., description="Resulting outcome")
    validation: Dict[str, Any] = Field(..., description="Validation result")
    
    # Metadata
    created_at: datetime = Field(..., description="When counterfactual was executed")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TraceDiff(BaseModel):
    """
    Differences between two traces.
    """
    first_divergence_event_id: Optional[str] = Field(None, description="First diverging event")
    changed_events: List[Dict[str, Any]] = Field(default_factory=list, description="Changed events")
    added_events: List[str] = Field(default_factory=list, description="Added event IDs")
    removed_events: List[str] = Field(default_factory=list, description="Removed event IDs")
    outcome: Dict[str, str] = Field(..., description="Outcome comparison")
