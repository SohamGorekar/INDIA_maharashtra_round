# Integration Guide

This guide explains how to integrate Black Box SDK into your agent system.

## Installation

```bash
cd blackbox
pip install -e .
```

Or with ML dependencies:

```bash
pip install -e ".[ml]"
```

## Basic Integration

### Step 1: Initialize Storage

```python
from blackbox.storage.sqlite import SQLiteStorage

storage = SQLiteStorage("my_agent.db")
```

### Step 2: Create Event Collector

```python
from blackbox.events.collector import EventCollector, set_global_collector

collector = EventCollector(storage=storage)
set_global_collector(collector)
```

### Step 3: Instrument Your Functions

```python
from blackbox import trace

@trace(type="tool", name="web_search")
def search_web(query: str):
    # Your implementation
    return results

@trace(type="llm", name="gpt4")
async def call_llm(prompt: str):
    # Your implementation
    return response

@trace(type="agent", name="supervisor")
def agent_loop(task: str):
    results = search_web(task)
    response = await call_llm(results)
    return response
```

### Step 4: Wrap Execution in Context

```python
from blackbox import BlackBoxContext

with BlackBoxContext() as ctx:
    result = agent_loop("user task")
    print(f"Run ID: {ctx.run_id}")
```

## Advanced Integration

### With FastAPI

```python
from fastapi import FastAPI
from blackbox.instrumentation.middleware import BlackBoxMiddleware

app = FastAPI()
storage = SQLiteStorage("api_traces.db")

app.add_middleware(BlackBoxMiddleware, storage=storage)

@app.post("/agent/execute")
@trace(type="agent")
async def execute_agent(task: str):
    # Your agent logic
    return result
```

### With State Tracking

```python
from blackbox.checkpoint.manager import CheckpointManager

checkpoint_mgr = CheckpointManager(storage=storage)

@trace(type="agent")
def agent_with_state(task: str, state: dict):
    # Process
    new_state = process(task, state)
    
    # Create checkpoint
    checkpoint = checkpoint_mgr.create_checkpoint(
        run_id=get_current_run_id(),
        event_id=get_current_event_id(),
        sequence_number=seq_num,
        state=new_state
    )
    
    return new_state
```

### Custom Adapter

```python
from blackbox.adapters.base import AgentAdapter

class MyFrameworkAdapter(AgentAdapter):
    def serialize_state(self, state):
        # Convert your framework's state to dict
        return {"key": state.value}
    
    def restore_state(self, serialized_state):
        # Reconstruct your framework's state
        return MyState(serialized_state["key"])
    
    def classify_side_effect(self, component):
        # Your classification logic
        if component.writes_to_db:
            return SideEffectType.WRITE
        return SideEffectType.READ
    
    def evaluate_outcome(self, run):
        # Your success criteria
        return run.outcome == "SUCCESS"
```

## Running the API Server

### Start Server

```python
# Method 1: Direct
uvicorn blackbox.api.app:app --host 0.0.0.0 --port 8000

# Method 2: Custom
from blackbox.api.app import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Configure Storage

By default, the API uses `blackbox.db`. To use a custom database:

```python
from blackbox.api.app import app
from blackbox.storage.sqlite import SQLiteStorage

# Replace storage in routes
custom_storage = SQLiteStorage("custom.db")
# Update router dependencies
```

## Diagnosis Integration

### Automatic Diagnosis

```python
from blackbox.diagnosis.model import DiagnosisModel
from blackbox.diagnosis.explanation import EvidenceGenerator

# Initialize
model = DiagnosisModel(model_name="xgboost_v1")
evidence_gen = EvidenceGenerator(storage=storage)

# After a failed run
run = storage.get_run(run_id)
events = storage.get_events_for_run(run_id)

if run.outcome == "FAILURE":
    # Diagnose
    diagnosis = model.diagnose(run, events, storage=storage)
    
    # Generate evidence
    evidence = evidence_gen.generate_evidence(
        diagnosis, run, events
    )
    
    print(f"Suspected event: {diagnosis.suspected_event_id}")
    print(f"Confidence: {diagnosis.confidence}")
    print(f"Evidence count: {len(evidence)}")
```

### Baseline Comparison

```python
from blackbox.diagnosis.baselines import get_baseline_diagnoser

baselines = ['random', 'last_tool', 'first_error', 'heuristic']

for baseline_name in baselines:
    diagnoser = get_baseline_diagnoser(baseline_name)
    rankings = diagnoser.diagnose(run, events)
    print(f"{baseline_name}: top suspect = {rankings[0][0]}")
```

## Fault Injection

### Generate Training Data

```python
from blackbox.experiments.fault_injection import generate_fault_injected_dataset

# Collect successful runs
successful_runs = []
for run_id in success_run_ids:
    run = storage.get_run(run_id)
    events = storage.get_events_for_run(run_id)
    successful_runs.append({'run': run, 'events': events})

# Inject faults
fault_dataset = generate_fault_injected_dataset(
    successful_runs=successful_runs,
    num_faults_per_run=5,
    seed=42
)

# Store fault runs
for fault_run_data in fault_dataset:
    storage.store_run(fault_run_data['run'])
    for event in fault_run_data['events']:
        storage.store_event(event)
```

## Training Diagnosis Model

### Prepare Dataset

```python
training_runs = []

for fault_run_data in fault_dataset:
    training_runs.append({
        'run': fault_run_data['run'],
        'events': fault_run_data['events'],
        'culprit_event_id': fault_run_data['culprit_event_id']
    })
```

### Train Model

```python
from blackbox.diagnosis.model import DiagnosisModel

model = DiagnosisModel(model_name="xgboost_v1")
model.train(training_runs=training_runs)

# Save model
import joblib
joblib.dump(model, "diagnosis_model.pkl")
```

### Load and Use

```python
import joblib

model = joblib.load("diagnosis_model.pkl")
diagnosis = model.diagnose(run, events, storage=storage)
```

## Evaluation

### Compute Metrics

```python
from blackbox.evaluation.metrics import DiagnosisMetrics

# Collect predictions
predictions = []
ground_truth = []

for test_run in test_dataset:
    diagnosis = model.diagnose(test_run['run'], test_run['events'])
    predictions.append([r.event_id for r in diagnosis.rankings])
    ground_truth.append(test_run['culprit_event_id'])

# Compute metrics
metrics = DiagnosisMetrics.compute_all_metrics(
    predictions=predictions,
    ground_truth=ground_truth
)

print(f"Top-1 Accuracy: {metrics['top_1_accuracy']:.2%}")
print(f"Top-3 Accuracy: {metrics['top_3_accuracy']:.2%}")
print(f"MRR: {metrics['mrr']:.3f}")
```

## Security Configuration

### Redaction

```python
def redact_sensitive_data(data):
    """Redact passwords, API keys, etc."""
    if isinstance(data, dict):
        redacted = data.copy()
        for key in ['password', 'api_key', 'token']:
            if key in redacted:
                redacted[key] = "[REDACTED]"
        return redacted
    return data

# Set redactor
collector.set_redactor(redact_sensitive_data)
```

### Payload Limits

```python
# Configure max payload size (in bytes)
collector = EventCollector(
    storage=storage,
    max_payload_size=1_000_000  # 1MB
)
```

## Best Practices

### 1. Instrument Strategically

Don't instrument every function - focus on:
- Tool calls (database, API, search)
- LLM calls
- Agent decision points
- State transitions

### 2. Use Meaningful Names

```python
# Good
@trace(type="tool", name="postgres_query")
@trace(type="llm", name="gpt4_completion")

# Bad
@trace(type="function", name="func1")
```

### 3. Capture State Selectively

State can be large - only capture when needed for replay:

```python
@trace(type="agent", capture_state=True)
def stateful_agent(state: dict):
    # State will be checkpointed
    pass
```

### 4. Monitor Performance

Instrumentation adds overhead. Monitor:
- Event collection time
- Storage write latency
- API response times

### 5. Organize Runs

Use metadata to organize runs:

```python
with BlackBoxContext() as ctx:
    ctx.metadata['environment'] = 'production'
    ctx.metadata['user_id'] = user_id
    ctx.metadata['experiment'] = 'variant_a'
```

## Troubleshooting

### Events Not Appearing

1. Check collector is set: `set_global_collector(collector)`
2. Verify context: `with BlackBoxContext()`
3. Check storage connection

### Diagnosis Not Working

1. Ensure run has `outcome=FAILURE`
2. Check events exist: `storage.get_events_for_run(run_id)`
3. Verify model is trained or use heuristic fallback

### API Not Starting

1. Install FastAPI: `pip install fastapi uvicorn`
2. Check database path exists
3. Verify port is not in use

## Next Steps

- See `architecture.md` for system design
- See `api-contract.md` for API specification
- See `examples/` for reference implementations
