# Black Box SDK

**Execution instrumentation and failure diagnosis for agent systems.**

Black Box is a backend SDK that provides:
- 🔍 **Automatic execution tracing** with structured event collection
- 🎯 **ML-powered failure diagnosis** to identify culprit steps
- 🔄 **Checkpointed replay** for efficient debugging
- 🧪 **Counterfactual execution** to validate diagnosis
- 📊 **Structured APIs** for frontend visualization

## Quick Start

### Installation

```bash
pip install -e .
```

### Basic Usage

```python
from blackbox import trace, BlackBoxContext
from blackbox.storage.sqlite import SQLiteStorage

# Initialize storage
storage = SQLiteStorage("blackbox.db")

# Create a run context
with BlackBoxContext() as ctx:
    # Instrument your functions
    @trace(type="tool")
    def search_database(query: str):
        # Your tool logic
        return {"results": [...]}
    
    @trace(type="llm")
    def generate_response(context: dict):
        # Your LLM call
        return {"response": "..."}
    
    # Your agent execution
    results = search_database("user query")
    response = generate_response(results)
```

### Start the API Server

```python
# Run from blackbox/sdk directory
uvicorn blackbox.api.app:app --reload --port 8000
```

### API Endpoints

- `GET /api/runs` - List all runs
- `GET /api/runs/{run_id}` - Get run details
- `GET /api/runs/{run_id}/trace` - Get complete trace (frontend-ready)
- `GET /api/runs/{run_id}/events/{event_id}` - Get event details
- `GET /api/runs/{run_id}/diagnosis` - Get failure diagnosis
- `POST /api/runs/{run_id}/replay` - Replay from checkpoint
- `POST /api/runs/{run_id}/counterfactual` - Run counterfactual execution
- `GET /api/runs/{run_id}/compare/{other_run_id}` - Compare traces

## Architecture

```
Application
    ↓
@trace decorator → Events → Storage (SQLite)
    ↓                           ↓
Execution Graph          Diagnosis Model
    ↓                           ↓
Checkpoints              Evidence Generation
    ↓                           ↓
Replay/Counterfactual    REST API → Frontend
```

## Key Features

### 1. Structured Instrumentation

Every execution step is captured as a structured `ExecutionEvent`:
- Input/output
- State before/after
- Timing
- Status
- Parent-child relationships

### 2. Failure Diagnosis

ML model ranks events by suspicion score:
- Baseline: random, last tool, first error, heuristic
- ML: XGBoost/LightGBM trained on fault-injected data

### 3. Evidence Generation

Structured evidence explains why an event is suspicious:
- `OUTPUT_ANOMALY` - Output differs from successful runs
- `ERROR` - Event returned an error
- `STATE_CHANGE` - Unexpected state modification
- `DOWNSTREAM_DEPENDENCY` - Preceded downstream failures
- `LATENCY_ANOMALY` - Significantly slower than average

### 4. Replay & Counterfactuals

- **Replay**: Resume from checkpoint using cached results
- **Counterfactual**: Patch an event and re-execute to validate diagnosis

### 5. Frontend-Ready APIs

All data is exposed in structured, frontend-friendly JSON:
- Events include `parent_event_id` for graph rendering
- Diagnosis includes ranked suspects with confidence
- Evidence is machine-readable with types and sources

## Development

### Project Structure

```
blackbox/
├── sdk/blackbox/           # Core SDK
│   ├── instrumentation/    # @trace decorator, context, middleware
│   ├── events/             # Event schemas and collection
│   ├── storage/            # SQLite backend
│   ├── diagnosis/          # ML model, features, evidence
│   ├── checkpoint/         # State checkpointing
│   ├── replay/             # Replay and counterfactual execution
│   ├── graph/              # Execution graph building
│   ├── api/                # FastAPI routes
│   └── adapters/           # Framework adapters
├── examples/               # Reference agents
├── experiments/            # Fault injection, training
└── docs/                   # Documentation
```

### Running Tests

```bash
pytest tests/
```

### Generating Training Data

```python
from blackbox.experiments.fault_injection import generate_fault_injected_dataset

# Inject faults into successful runs
fault_runs = generate_fault_injected_dataset(
    successful_runs=success_data,
    num_faults_per_run=3
)
```

### Training Diagnosis Model

```python
from blackbox.diagnosis.model import DiagnosisModel

model = DiagnosisModel(model_name="xgboost_v1")
model.train(training_runs=fault_runs)
```

## Design Principles

1. **Backend Only** - No UI components, only data and APIs
2. **Framework Agnostic** - Works with any Python agent system
3. **Structured Data** - Everything is typed and queryable
4. **No Causal Claims** - Diagnosis ranks suspicion, counterfactuals provide evidence
5. **Security First** - Configurable redaction, payload limits, safe replay

## Integration Examples

### With FastAPI

```python
from fastapi import FastAPI
from blackbox.instrumentation.middleware import BlackBoxMiddleware
from blackbox.storage.sqlite import SQLiteStorage

app = FastAPI()
storage = SQLiteStorage()

app.add_middleware(BlackBoxMiddleware, storage=storage)
```

### With Custom Agent

```python
from blackbox import trace, BlackBoxContext
from blackbox.adapters.base import CustomPythonAdapter

adapter = CustomPythonAdapter()

with BlackBoxContext() as ctx:
    # Your agent loop
    pass
```

## Documentation

See [docs/](./docs/) for:
- `architecture.md` - System architecture
- `integration.md` - Integration guide
- `api-contract.md` - API specification

## License

MIT
