# Black Box - Quick Start Guide

Get up and running in 5 minutes.

## Installation

```bash
cd blackbox
pip install -e .
```

## Run Your First Trace

```python
# File: my_agent.py
from blackbox import trace, BlackBoxContext
from blackbox.storage.sqlite import SQLiteStorage
from blackbox.events.collector import EventCollector, set_global_collector

# Setup (once)
storage = SQLiteStorage("my_traces.db")
collector = EventCollector(storage=storage)
set_global_collector(collector)

# Instrument your functions
@trace(type="tool")
def search_database(query):
    return {"results": ["item1", "item2"]}

@trace(type="agent")
def my_agent(task):
    results = search_database(task)
    return {"status": "done", "data": results}

# Run with context
with BlackBoxContext() as ctx:
    result = my_agent("find users")
    print(f"Run ID: {ctx.run_id}")
```

## View Your Traces

### Option 1: API Server
```bash
uvicorn blackbox.api.app:app --reload

# Then visit:
# http://localhost:8000/api/runs
```

### Option 2: Direct Query
```python
from blackbox.storage.sqlite import SQLiteStorage

storage = SQLiteStorage("my_traces.db")
runs = storage.list_runs()

for run in runs:
    print(f"{run.run_id}: {run.outcome} ({run.event_count} events)")
```

## Run Examples

### Example 1: Quickstart Demo
```bash
python examples/quickstart.py
```
Shows basic tracing + diagnosis.

### Example 2: Customer Support Agent
```bash
python examples/customer_support/agent.py
```
Full agent with tools and decision logic.

## Diagnose Failures

```python
from blackbox.diagnosis.model import DiagnosisModel

# After a failure
run = storage.get_run(run_id)
events = storage.get_events_for_run(run_id)

model = DiagnosisModel()
diagnosis = model.diagnose(run, events, storage=storage)

print(f"Suspected: {diagnosis.suspected_event_id}")
print(f"Confidence: {diagnosis.confidence:.0%}")
```

## API Endpoints

- `GET /api/runs` - List all runs
- `GET /api/runs/{id}/trace` - Complete trace for frontend
- `GET /api/runs/{id}/diagnosis` - Diagnosis + evidence
- `POST /api/runs/{id}/replay` - Replay from checkpoint
- `POST /api/runs/{id}/counterfactual` - Test alternative

## Next Steps

1. **Read the docs**: `docs/integration.md`
2. **Explore API**: `docs/api-contract.md`
3. **System design**: `docs/architecture.md`
4. **Full summary**: `IMPLEMENTATION_SUMMARY.md`

## Common Issues

**Events not appearing?**
- Check: `set_global_collector(collector)` is called
- Check: Wrapped in `with BlackBoxContext()`

**API won't start?**
- Run: `pip install fastapi uvicorn`
- Check port 8000 is free

**Need help?**
- Check `README.md` for detailed documentation
- See `examples/` for working code
