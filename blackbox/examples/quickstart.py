"""
Quick start example for Black Box SDK.
Demonstrates basic instrumentation and diagnosis.
"""
import sys
import os

# Add SDK to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'sdk'))

from blackbox import trace, BlackBoxContext
from blackbox.storage.sqlite import SQLiteStorage
from blackbox.events.collector import EventCollector, set_global_collector
from blackbox.diagnosis.model import DiagnosisModel
from blackbox.diagnosis.explanation import EvidenceGenerator


# Example tool functions
@trace(type="tool", name="database_query")
def query_database(query: str):
    """Simulated database query."""
    if query == "SELECT * FROM users WHERE id = 999":
        return {"error": "User not found"}
    return {"user_id": 1, "name": "Alice", "status": "active"}


@trace(type="tool", name="process_data")
def process_data(data: dict):
    """Process data."""
    if "error" in data:
        return {"processed": False, "error": data["error"]}
    return {"processed": True, "result": f"Processed {data.get('name', 'unknown')}"}


@trace(type="agent", name="main_agent")
def run_agent(user_id: int):
    """Main agent function."""
    # Query database
    query = f"SELECT * FROM users WHERE id = {user_id}"
    user_data = query_database(query)
    
    # Process results
    result = process_data(user_data)
    
    return result


def main():
    """Run quick start demo."""
    print("=== Black Box SDK Quick Start ===\n")
    
    # Step 1: Initialize storage
    print("1. Initializing storage...")
    storage = SQLiteStorage("quickstart.db")
    
    # Step 2: Set up event collector
    print("2. Setting up event collector...")
    collector = EventCollector(storage=storage)
    set_global_collector(collector)
    
    # Step 3: Run successful execution
    print("3. Running successful execution...")
    with BlackBoxContext() as ctx:
        result = run_agent(user_id=1)
        success_run_id = ctx.run_id
        print(f"   Result: {result}")
        print(f"   Run ID: {success_run_id}")
    
    # Step 4: Run failed execution
    print("\n4. Running failed execution...")
    with BlackBoxContext() as ctx:
        result = run_agent(user_id=999)  # Will fail
        failed_run_id = ctx.run_id
        print(f"   Result: {result}")
        print(f"   Run ID: {failed_run_id}")
    
    # Step 5: Diagnose failure
    print("\n5. Diagnosing failure...")
    failed_run = storage.get_run(failed_run_id)
    failed_events = storage.get_events_for_run(failed_run_id)
    
    model = DiagnosisModel()
    diagnosis = model.diagnose(failed_run, failed_events, storage=storage)
    
    print(f"   Status: {diagnosis.status}")
    print(f"   Suspected event: {diagnosis.suspected_event_id}")
    print(f"   Confidence: {diagnosis.confidence:.2%}")
    
    # Step 6: Generate evidence
    print("\n6. Generating evidence...")
    evidence_gen = EvidenceGenerator(storage=storage)
    evidence = evidence_gen.generate_evidence(diagnosis, failed_run, failed_events)
    
    print(f"   Evidence count: {len(evidence)}")
    for ev in evidence:
        print(f"   - {ev.evidence_type}: {ev.description}")
    
    # Step 7: Summary
    print("\n=== Summary ===")
    print(f"Database: quickstart.db")
    print(f"Successful run: {success_run_id}")
    print(f"Failed run: {failed_run_id}")
    print(f"\nTo explore data:")
    print(f"  1. Start API: uvicorn blackbox.api.app:app --reload")
    print(f"  2. Open: http://localhost:8000/api/runs/{failed_run_id}/trace")
    print(f"  3. Or use SQLite: sqlite3 quickstart.db")
    

if __name__ == "__main__":
    main()
