# Black Box Backend - Documentation Index

## 🚀 Getting Started

1. **[QUICKSTART.md](QUICKSTART.md)** ⭐ START HERE
   - 5-minute quick start
   - Basic examples
   - Common issues

2. **[README.md](README.md)**
   - Project overview
   - Features
   - Installation

3. **[DELIVERY_CHECKLIST.md](DELIVERY_CHECKLIST.md)**
   - What's implemented
   - What works now
   - Known limitations

## 📚 Documentation

### For Developers
- **[docs/integration.md](docs/integration.md)** - How to integrate SDK into your agent
- **[docs/architecture.md](docs/architecture.md)** - System design and decisions
- **[requirements.txt](requirements.txt)** - Dependencies

### For Frontend Team
- **[docs/api-contract.md](docs/api-contract.md)** - API specification
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Complete backend overview

### For ML Team
- **[sdk/blackbox/diagnosis/](sdk/blackbox/diagnosis/)** - Diagnosis models
- **[experiments/fault_injection.py](experiments/fault_injection.py)** - Training data generation
- **[sdk/blackbox/evaluation/metrics.py](sdk/blackbox/evaluation/metrics.py)** - Evaluation metrics

## 🎯 Core Components

### SDK Structure
```
sdk/blackbox/
├── instrumentation/    → @trace decorator, context
├── events/            → Event schemas, collector
├── storage/           → SQLite backend
├── diagnosis/         → ML model, features, evidence
├── checkpoint/        → State snapshots
├── graph/             → Execution graph
├── api/               → REST API
├── adapters/          → Framework adapters
└── evaluation/        → Metrics
```

### Key Files
- **[sdk/blackbox/__init__.py](sdk/blackbox/__init__.py)** - Main exports
- **[sdk/blackbox/events/schema.py](sdk/blackbox/events/schema.py)** - Core schemas
- **[sdk/blackbox/instrumentation/decorator.py](sdk/blackbox/instrumentation/decorator.py)** - @trace
- **[sdk/blackbox/storage/sqlite.py](sdk/blackbox/storage/sqlite.py)** - Storage
- **[sdk/blackbox/api/app.py](sdk/blackbox/api/app.py)** - API server

## 💡 Examples

1. **[examples/quickstart.py](examples/quickstart.py)**
   - Basic tracing
   - Diagnosis
   - Evidence generation

2. **[examples/customer_support/agent.py](examples/customer_support/agent.py)**
   - Full agent with tools
   - Multiple scenarios
   - Database simulation

## 📊 Usage Patterns

### Basic Tracing
```python
from blackbox import trace, BlackBoxContext

with BlackBoxContext():
    @trace(type="tool")
    def my_function():
        pass
```

### With Storage
```python
from blackbox.storage.sqlite import SQLiteStorage
from blackbox.events.collector import EventCollector, set_global_collector

storage = SQLiteStorage("traces.db")
collector = EventCollector(storage=storage)
set_global_collector(collector)
```

### Diagnosis
```python
from blackbox.diagnosis.model import DiagnosisModel

model = DiagnosisModel()
diagnosis = model.diagnose(run, events, storage=storage)
```

### API Server
```bash
uvicorn blackbox.api.app:app --reload
```

## 🔗 Quick Links

### Start Development
1. Install: `pip install -e .`
2. Run example: `python examples/quickstart.py`
3. Start API: `uvicorn blackbox.api.app:app --reload`
4. Test: `curl http://localhost:8000/api/runs`

### Read Docs
1. [QUICKSTART.md](QUICKSTART.md) - Get started in 5 minutes
2. [docs/integration.md](docs/integration.md) - Integration guide
3. [docs/api-contract.md](docs/api-contract.md) - API reference

### Explore Code
1. [sdk/blackbox/](sdk/blackbox/) - Core SDK
2. [examples/](examples/) - Working examples
3. [docs/](docs/) - Documentation

## 📁 Repository Structure

```
blackbox/
├── INDEX.md                     ← You are here
├── QUICKSTART.md               ← Start here
├── README.md                   ← Project overview
├── IMPLEMENTATION_SUMMARY.md   ← Complete details
├── DELIVERY_CHECKLIST.md       ← What's done
│
├── sdk/blackbox/               ← Core SDK (27 modules)
│   ├── __init__.py
│   ├── instrumentation/
│   ├── events/
│   ├── storage/
│   ├── diagnosis/
│   ├── checkpoint/
│   ├── graph/
│   ├── replay/
│   ├── comparison/
│   ├── evaluation/
│   ├── adapters/
│   └── api/
│
├── examples/                   ← Working examples
│   ├── quickstart.py
│   └── customer_support/
│
├── experiments/                ← ML/training
│   └── fault_injection.py
│
├── docs/                       ← Documentation
│   ├── architecture.md
│   ├── integration.md
│   └── api-contract.md
│
├── pyproject.toml              ← Package config
├── requirements.txt            ← Dependencies
└── setup.sh                    ← Setup script
```

## 🎯 By Role

### I'm a Developer Integrating Black Box
1. Read [QUICKSTART.md](QUICKSTART.md)
2. Read [docs/integration.md](docs/integration.md)
3. Run [examples/quickstart.py](examples/quickstart.py)
4. Instrument your code

### I'm Building the Frontend
1. Read [docs/api-contract.md](docs/api-contract.md)
2. Start API: `uvicorn blackbox.api.app:app --reload`
3. Explore: `http://localhost:8000/api/runs`
4. See [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)

### I'm Training ML Models
1. Read [docs/architecture.md](docs/architecture.md)
2. See [experiments/fault_injection.py](experiments/fault_injection.py)
3. Check [sdk/blackbox/diagnosis/](sdk/blackbox/diagnosis/)
4. Use [sdk/blackbox/evaluation/metrics.py](sdk/blackbox/evaluation/metrics.py)

### I'm Deploying to Production
1. Read [docs/integration.md](docs/integration.md) security section
2. Add authentication to API
3. Configure redaction
4. Set up monitoring
5. Consider PostgreSQL migration

## ❓ FAQ

**Q: Where do I start?**  
A: Read [QUICKSTART.md](QUICKSTART.md), then run `python examples/quickstart.py`

**Q: How do I integrate this into my agent?**  
A: See [docs/integration.md](docs/integration.md)

**Q: What's the API format?**  
A: See [docs/api-contract.md](docs/api-contract.md)

**Q: How does diagnosis work?**  
A: See [docs/architecture.md](docs/architecture.md) section 4

**Q: Is this production ready?**  
A: Core features yes, add auth + tests for production

**Q: Where's the frontend?**  
A: Backend only - frontend team builds on the API

---

**Version**: 0.1.0  
**Status**: ✅ Ready for integration  
**Last Updated**: Implementation complete
