# Black Box Architecture

## Overview

Black Box is a backend SDK for execution instrumentation and failure diagnosis in agent systems. It provides structured tracing, ML-powered diagnosis, and APIs for frontend visualization.

## Core Components

### 1. Instrumentation Layer

**Purpose**: Capture execution events automatically

**Components**:
- `@trace` decorator - Instruments functions/methods
- `BlackBoxContext` - Manages run-level state
- `EventCollector` - Buffers and persists events
- `BlackBoxMiddleware` - FastAPI integration

**Flow**:
```
@trace decorator
    ↓
Generate event_id, sequence_number
    ↓
Capture input, output, timing
    ↓
EventCollector
    ↓
Storage (SQLite)
```

### 2. Storage Layer

**Purpose**: Persist and query execution data

**Schema**:
- `runs` - Run-level metadata
- `events` - Individual execution steps
- `checkpoints` - State snapshots
- `diagnoses` - Diagnosis results
- `evidence` - Supporting evidence
- `replay_runs` - Replay executions
- `counterfactual_runs` - Counterfactual executions

**Relationships**:
```
run (1) → (N) events
event (1) → (1) checkpoint
run (1) → (1) diagnosis
diagnosis (1) → (N) evidence
```

### 3. Graph Builder

**Purpose**: Construct execution graph from events

**Features**:
- Parent-child relationships via `parent_event_id`
- Sequence ordering via `sequence_number`
- Tree traversal (ancestors, descendants)
- Frontend-ready JSON export

### 4. Diagnosis Engine

**Components**:
- `FeatureExtractor` - Extracts ML features from events
- `BaselineDiagnoser` - Simple heuristic baselines
- `DiagnosisModel` - ML-based ranking model
- `EvidenceGenerator` - Generates structured evidence

**Diagnosis Flow**:
```
Failed Run + Events
    ↓
Extract Features (per event)
    ↓
Model Prediction (scores per event)
    ↓
Rank Events by Score
    ↓
Generate Evidence for Top Suspects
    ↓
Store Diagnosis + Evidence
```

### 5. Checkpoint System

**Purpose**: Enable replay and counterfactual execution

**Features**:
- State serialization with hash verification
- Checkpoint at every event (optional)
- Storage-backed persistence

### 6. Replay Engine

**Purpose**: Re-execute from checkpoints

**Features**:
- Restore state from checkpoint
- Reuse cached execution results
- Side-effect protection (read/write/external)
- Track steps reused vs. re-executed

### 7. Counterfactual Engine

**Purpose**: Validate diagnosis by patching events

**Flow**:
```
Original Run + Suspected Event
    ↓
Find Checkpoint Before Event
    ↓
Restore State
    ↓
Apply Patch to Event
    ↓
Re-execute from Checkpoint
    ↓
Compare Original vs. Counterfactual Outcome
    ↓
Validation: supported=True if outcome changed
```

### 8. API Layer

**Purpose**: Expose data to frontend

**Endpoints**:
- `/api/runs` - List/get runs
- `/api/runs/{id}/trace` - Complete trace (run + events + diagnosis)
- `/api/runs/{id}/events/{event_id}` - Event details
- `/api/runs/{id}/diagnosis` - Diagnosis + evidence
- `/api/runs/{id}/replay` - Trigger replay
- `/api/runs/{id}/counterfactual` - Trigger counterfactual
- `/api/runs/{id}/compare/{other_id}` - Trace diff

## Data Flow

### Successful Execution

```
Application Code
    ↓
@trace decorator captures events
    ↓
Events → EventCollector → SQLite
    ↓
Run marked as SUCCESS
```

### Failed Execution

```
Application Code (failure)
    ↓
@trace captures events (including error)
    ↓
Events → SQLite
    ↓
Run marked as FAILURE
    ↓
Trigger Diagnosis
    ↓
FeatureExtractor → Model → Rankings
    ↓
EvidenceGenerator → Evidence
    ↓
Store Diagnosis + Evidence
    ↓
Frontend retrieves via API
```

### Replay

```
Frontend: POST /api/runs/{id}/replay
    ↓
Backend: Get checkpoint
    ↓
Restore state
    ↓
Cache lookup for subsequent events
    ↓
Re-execute only cache misses
    ↓
Return replay results
```

### Counterfactual

```
Frontend: POST /api/runs/{id}/counterfactual
    ↓
Backend: Get checkpoint before event
    ↓
Restore state
    ↓
Apply patch to event
    ↓
Re-execute from patch point
    ↓
Compare outcome: original vs. counterfactual
    ↓
Return validation result
```

## Design Decisions

### 1. Structured Events vs. Logs

**Choice**: Structured `ExecutionEvent` schema

**Rationale**:
- Queryable (SQL joins, filters)
- Frontend can directly render
- Type-safe (Pydantic)
- Supports graph construction

### 2. SQLite vs. Other Databases

**Choice**: SQLite initially

**Rationale**:
- Zero setup
- Sufficient for 1000s of runs
- Easy to query
- Can migrate to Postgres later

### 3. No Causal Claims

**Choice**: Diagnosis ranks "suspicion", not "causality"

**Rationale**:
- True causality requires formal methods
- ML model is probabilistic
- Counterfactuals provide evidence, not proof
- Honest UX: "suspected", "confidence", "evidence"

### 4. Backend-Only

**Choice**: No visualization in SDK

**Rationale**:
- Separation of concerns
- Backend team focuses on data correctness
- Frontend team owns UX
- API contract as integration point

### 5. Side-Effect Classification

**Choice**: Classify components as READ/WRITE/EXTERNAL

**Rationale**:
- Replay safety (don't re-execute writes)
- Evidence generation (writes are suspicious)
- User transparency (show warnings)

## Performance Considerations

### Event Collection

- **Buffering**: Events buffered in-memory, batched writes
- **Async**: Decorator works with both sync and async functions
- **Overhead**: ~1-2ms per instrumented call

### Storage

- **Indexes**: On `run_id`, `parent_event_id`, `sequence_number`
- **Writes**: Batched where possible
- **Reads**: Optimized queries for frontend APIs

### Diagnosis

- **Lazy**: Only run on-demand or on failure
- **Caching**: Features computed once, cached
- **Incremental**: Can update diagnosis as new data arrives

## Security

### Redaction

- Configurable via `context.set_redactor(fn)`
- Applied before storage
- Can redact inputs, outputs, state

### Payload Limits

- Configurable `max_payload_size`
- Large payloads truncated with marker

### Replay Safety

- Side-effect classification prevents unsafe re-execution
- Sandbox mode for WRITE operations
- Block EXTERNAL_SIDE_EFFECT by default

## Extensibility

### Custom Adapters

Implement `AgentAdapter` interface:
- `serialize_state()` - Framework-specific state
- `restore_state()` - Deserialize state
- `classify_side_effect()` - Custom classification
- `evaluate_outcome()` - Custom success criteria

### Custom Storage

Implement `StorageBackend` interface:
- All CRUD operations
- Can plug in Postgres, MongoDB, etc.

### Custom Diagnosis Models

Extend `DiagnosisModel`:
- `train()` - Custom training logic
- `predict()` - Custom inference
- Same API contract

## Testing Strategy

### Unit Tests

- Individual components (decorator, collector, storage)
- Feature extraction
- Baselines
- Metrics

### Integration Tests

- End-to-end flows
- API endpoints
- Fault injection → diagnosis → counterfactual

### Evaluation

- Held-out test set
- Multiple baselines
- Cross-agent generalization
