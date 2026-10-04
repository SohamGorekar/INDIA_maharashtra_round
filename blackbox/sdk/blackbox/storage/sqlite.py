"""
SQLite storage backend for Black Box.
"""
import json
import sqlite3
from functools import wraps
from threading import RLock
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from blackbox.storage.interface import StorageBackend
from blackbox.events.schema import (
    ExecutionEvent,
    Run,
    Checkpoint,
    Diagnosis,
    Evidence,
    ReplayRun,
    CounterfactualRun,
    EventRanking,
)


def _serialized(method):
    """Serialize access to the shared SQLite connection across API threads."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class SQLiteStorage(StorageBackend):
    """SQLite-based storage backend."""
    
    def __init__(self, db_path: str = "blackbox.db"):
        """
        Initialize SQLite storage.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._lock = RLock()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._initialize_schema()
    
    @_serialized
    def _initialize_schema(self):
        """Create database schema if it doesn't exist."""
        cursor = self.conn.cursor()
        
        # Runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                parent_run_id TEXT,
                task_input TEXT,
                status TEXT NOT NULL,
                outcome TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms REAL,
                root_event_id TEXT,
                event_count INTEGER DEFAULT 0,
                diagnosis TEXT,
                metadata TEXT,
                FOREIGN KEY (parent_run_id) REFERENCES runs(run_id)
            )
        """)
        
        # Events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                parent_event_id TEXT,
                sequence_number INTEGER NOT NULL,
                component_id TEXT NOT NULL,
                component_name TEXT NOT NULL,
                component_type TEXT NOT NULL,
                input TEXT,
                output TEXT,
                state_before TEXT,
                state_after TEXT,
                status TEXT NOT NULL,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                duration_ms REAL,
                checkpoint_id TEXT,
                metadata TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (parent_event_id) REFERENCES events(event_id),
                FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id)
            )
        """)
        
        # Checkpoints table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                sequence_number INTEGER NOT NULL,
                state TEXT NOT NULL,
                state_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                storage_reference TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (event_id) REFERENCES events(event_id)
            )
        """)
        
        # Diagnoses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS diagnoses (
                diagnosis_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                suspected_event_id TEXT,
                suspected_event_ids TEXT NOT NULL DEFAULT '[]',
                confidence REAL NOT NULL,
                rankings TEXT NOT NULL,
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (suspected_event_id) REFERENCES events(event_id)
            )
        """)
        # Keep databases created before multi-stage simulated diagnosis usable.
        diagnosis_columns = {
            row["name"]
            for row in cursor.execute("PRAGMA table_info(diagnoses)").fetchall()
        }
        if "suspected_event_ids" not in diagnosis_columns:
            cursor.execute(
                "ALTER TABLE diagnoses ADD COLUMN suspected_event_ids TEXT NOT NULL DEFAULT '[]'"
            )
        
        # Evidence table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evidence (
                evidence_id TEXT PRIMARY KEY,
                diagnosis_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                description TEXT NOT NULL,
                observed_value TEXT,
                expected_value TEXT,
                source_event_ids TEXT,
                strength REAL NOT NULL,
                FOREIGN KEY (diagnosis_id) REFERENCES diagnoses(diagnosis_id),
                FOREIGN KEY (event_id) REFERENCES events(event_id)
            )
        """)
        
        # Replay runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS replay_runs (
                replay_run_id TEXT PRIMARY KEY,
                original_run_id TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                steps_reused INTEGER NOT NULL,
                steps_reexecuted INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (original_run_id) REFERENCES runs(run_id),
                FOREIGN KEY (checkpoint_id) REFERENCES checkpoints(checkpoint_id)
            )
        """)
        
        # Counterfactual runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS counterfactual_runs (
                counterfactual_run_id TEXT PRIMARY KEY,
                original_run_id TEXT NOT NULL,
                modified_event_id TEXT NOT NULL,
                patch TEXT NOT NULL,
                outcome TEXT NOT NULL,
                validation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (original_run_id) REFERENCES runs(run_id),
                FOREIGN KEY (modified_event_id) REFERENCES events(event_id)
            )
        """)
        
        # Create indexes for performance
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_run_id ON events(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_parent_id ON events(parent_event_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_sequence ON events(run_id, sequence_number)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON checkpoints(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_event_id ON checkpoints(event_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_diagnoses_run_id ON diagnoses(run_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_diagnosis_id ON evidence(diagnosis_id)")
        
        self.conn.commit()
    
    @_serialized
    def store_run(self, run: Run):
        """Store a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO runs 
            (run_id, parent_run_id, task_input, status, outcome, started_at, 
             finished_at, duration_ms, root_event_id, event_count, diagnosis, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run.run_id,
            run.parent_run_id,
            json.dumps(run.task_input) if run.task_input else None,
            run.status,
            run.outcome,
            run.started_at.isoformat(),
            run.finished_at.isoformat() if run.finished_at else None,
            run.duration_ms,
            run.root_event_id,
            run.event_count,
            json.dumps(run.diagnosis) if run.diagnosis else None,
            json.dumps(run.metadata),
        ))
        self.conn.commit()
    
    @_serialized
    def get_run(self, run_id: str) -> Optional[Run]:
        """Retrieve a run by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_run(row)
        return None
    
    @_serialized
    def list_runs(self, limit: int = 100, offset: int = 0) -> List[Run]:
        """List all runs."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM runs 
            ORDER BY started_at DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return [self._row_to_run(row) for row in cursor.fetchall()]
    
    @_serialized
    def update_run(self, run_id: str, updates: Dict[str, Any]):
        """Update a run."""
        # Build SET clause dynamically
        set_clauses = []
        values = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            if isinstance(value, (dict, list)):
                values.append(json.dumps(value))
            elif isinstance(value, datetime):
                values.append(value.isoformat())
            else:
                values.append(value)
        
        values.append(run_id)
        cursor = self.conn.cursor()
        cursor.execute(f"""
            UPDATE runs SET {', '.join(set_clauses)} WHERE run_id = ?
        """, values)
        self.conn.commit()
    
    @_serialized
    def store_event(self, event: ExecutionEvent):
        """Store an execution event."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO events 
            (event_id, run_id, parent_event_id, sequence_number, component_id,
             component_name, component_type, input, output, state_before, state_after,
             status, error, started_at, finished_at, duration_ms, checkpoint_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.event_id,
            event.run_id,
            event.parent_event_id,
            event.sequence_number,
            event.component_id,
            event.component_name,
            event.component_type,
            json.dumps(event.input) if event.input else None,
            json.dumps(event.output) if event.output else None,
            json.dumps(event.state_before) if event.state_before else None,
            json.dumps(event.state_after) if event.state_after else None,
            event.status,
            event.error,
            event.started_at.isoformat(),
            event.finished_at.isoformat() if event.finished_at else None,
            event.duration_ms,
            event.checkpoint_id,
            json.dumps(event.metadata),
        ))
        self.conn.commit()
        
        # Update run event count
        cursor.execute("""
            UPDATE runs SET event_count = event_count + 1 
            WHERE run_id = ?
        """, (event.run_id,))
        self.conn.commit()
    
    @_serialized
    def get_event(self, event_id: str) -> Optional[ExecutionEvent]:
        """Retrieve an event by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_event(row)
        return None
    
    @_serialized
    def get_events_for_run(self, run_id: str) -> List[ExecutionEvent]:
        """Get all events for a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM events 
            WHERE run_id = ? 
            ORDER BY sequence_number
        """, (run_id,))
        return [self._row_to_event(row) for row in cursor.fetchall()]
    
    @_serialized
    def get_event_children(self, event_id: str) -> List[ExecutionEvent]:
        """Get child events of a parent event."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM events 
            WHERE parent_event_id = ? 
            ORDER BY sequence_number
        """, (event_id,))
        return [self._row_to_event(row) for row in cursor.fetchall()]
    
    @_serialized
    def store_checkpoint(self, checkpoint: Checkpoint):
        """Store a checkpoint."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO checkpoints 
            (checkpoint_id, run_id, event_id, sequence_number, state, state_hash,
             created_at, storage_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            checkpoint.checkpoint_id,
            checkpoint.run_id,
            checkpoint.event_id,
            checkpoint.sequence_number,
            json.dumps(checkpoint.state),
            checkpoint.state_hash,
            checkpoint.created_at.isoformat(),
            checkpoint.storage_reference,
        ))
        self.conn.commit()
    
    @_serialized
    def get_checkpoint(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Retrieve a checkpoint by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_checkpoint(row)
        return None
    
    @_serialized
    def get_checkpoints_for_run(self, run_id: str) -> List[Checkpoint]:
        """Get all checkpoints for a run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM checkpoints 
            WHERE run_id = ? 
            ORDER BY sequence_number
        """, (run_id,))
        return [self._row_to_checkpoint(row) for row in cursor.fetchall()]
    
    @_serialized
    def get_checkpoint_for_event(self, event_id: str) -> Optional[Checkpoint]:
        """Get checkpoint associated with an event."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM checkpoints WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_checkpoint(row)
        return None
    
    @_serialized
    def store_diagnosis(self, diagnosis: Diagnosis):
        """Store a diagnosis."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO diagnoses 
            (diagnosis_id, run_id, status, suspected_event_id, suspected_event_ids,
             confidence, rankings, model_name, model_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            diagnosis.diagnosis_id,
            diagnosis.run_id,
            diagnosis.status,
            diagnosis.suspected_event_id,
            json.dumps(diagnosis.suspected_event_ids),
            diagnosis.confidence,
            json.dumps([r.dict() for r in diagnosis.rankings]),
            diagnosis.model_name,
            diagnosis.model_version,
            diagnosis.created_at.isoformat(),
        ))
        self.conn.commit()
    
    @_serialized
    def get_diagnosis(self, diagnosis_id: str) -> Optional[Diagnosis]:
        """Retrieve a diagnosis by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM diagnoses WHERE diagnosis_id = ?", (diagnosis_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_diagnosis(row)
        return None
    
    @_serialized
    def get_diagnosis_for_run(self, run_id: str) -> Optional[Diagnosis]:
        """Get diagnosis for a run."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM diagnoses WHERE run_id = ? ORDER BY created_at DESC LIMIT 1", (run_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_diagnosis(row)
        return None
    
    @_serialized
    def store_evidence(self, evidence: Evidence):
        """Store evidence."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO evidence 
            (evidence_id, diagnosis_id, event_id, evidence_type, description,
             observed_value, expected_value, source_event_ids, strength)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            evidence.evidence_id,
            evidence.diagnosis_id,
            evidence.event_id,
            evidence.evidence_type,
            evidence.description,
            json.dumps(evidence.observed_value) if evidence.observed_value is not None else None,
            json.dumps(evidence.expected_value) if evidence.expected_value is not None else None,
            json.dumps(evidence.source_event_ids),
            evidence.strength,
        ))
        self.conn.commit()
    
    @_serialized
    def get_evidence_for_diagnosis(self, diagnosis_id: str) -> List[Evidence]:
        """Get all evidence for a diagnosis."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM evidence WHERE diagnosis_id = ?", (diagnosis_id,))
        return [self._row_to_evidence(row) for row in cursor.fetchall()]
    
    @_serialized
    def store_replay_run(self, replay_run: ReplayRun):
        """Store a replay run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO replay_runs 
            (replay_run_id, original_run_id, checkpoint_id, steps_reused,
             steps_reexecuted, outcome, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            replay_run.replay_run_id,
            replay_run.original_run_id,
            replay_run.checkpoint_id,
            replay_run.steps_reused,
            replay_run.steps_reexecuted,
            replay_run.outcome,
            replay_run.created_at.isoformat(),
        ))
        self.conn.commit()
    
    @_serialized
    def get_replay_run(self, replay_run_id: str) -> Optional[ReplayRun]:
        """Retrieve a replay run by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM replay_runs WHERE replay_run_id = ?", (replay_run_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_replay_run(row)
        return None
    
    @_serialized
    def store_counterfactual_run(self, counterfactual_run: CounterfactualRun):
        """Store a counterfactual run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO counterfactual_runs 
            (counterfactual_run_id, original_run_id, modified_event_id, patch,
             outcome, validation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            counterfactual_run.counterfactual_run_id,
            counterfactual_run.original_run_id,
            counterfactual_run.modified_event_id,
            json.dumps(counterfactual_run.patch),
            counterfactual_run.outcome,
            json.dumps(counterfactual_run.validation),
            counterfactual_run.created_at.isoformat(),
        ))
        self.conn.commit()
    
    @_serialized
    def get_counterfactual_run(self, counterfactual_run_id: str) -> Optional[CounterfactualRun]:
        """Retrieve a counterfactual run by ID."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM counterfactual_runs WHERE counterfactual_run_id = ?", (counterfactual_run_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_counterfactual_run(row)
        return None
    
    @_serialized
    def close(self):
        """Close the database connection."""
        self.conn.close()
    
    # Helper methods to convert database rows to Pydantic models

    @staticmethod
    def _parse_datetime(value, field_name: str) -> datetime:
        """Parse timestamps from current and legacy SQLite representations."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            numeric_value = value.strip()
            try:
                if numeric_value and all(
                    character in "0123456789.-" for character in numeric_value
                ):
                    return datetime.fromtimestamp(float(numeric_value))
            except (OverflowError, ValueError) as exc:
                raise ValueError(
                    f"Invalid {field_name} timestamp: {value!r}"
                ) from exc
            try:
                return datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid {field_name} timestamp: {value!r}"
                ) from exc
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value)
        raise TypeError(
            f"Invalid {field_name} timestamp type: {type(value).__name__}"
        )

    def _row_to_run(self, row) -> Run:
        """Convert database row to Run model."""
        return Run(
            run_id=row['run_id'],
            parent_run_id=row['parent_run_id'],
            task_input=json.loads(row['task_input']) if row['task_input'] else None,
            status=row['status'],
            outcome=row['outcome'],
            started_at=self._parse_datetime(row['started_at'], "run.started_at"),
            finished_at=self._parse_datetime(row['finished_at'], "run.finished_at") if row['finished_at'] else None,
            duration_ms=row['duration_ms'],
            root_event_id=row['root_event_id'],
            event_count=row['event_count'],
            diagnosis=json.loads(row['diagnosis']) if row['diagnosis'] else None,
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
        )
    
    def _row_to_event(self, row) -> ExecutionEvent:
        """Convert database row to ExecutionEvent model."""
        return ExecutionEvent(
            event_id=row['event_id'],
            run_id=row['run_id'],
            parent_event_id=row['parent_event_id'],
            sequence_number=row['sequence_number'],
            component_id=row['component_id'],
            component_name=row['component_name'],
            component_type=row['component_type'],
            input=json.loads(row['input']) if row['input'] else None,
            output=json.loads(row['output']) if row['output'] else None,
            state_before=json.loads(row['state_before']) if row['state_before'] else None,
            state_after=json.loads(row['state_after']) if row['state_after'] else None,
            status=row['status'],
            error=row['error'],
            started_at=self._parse_datetime(row['started_at'], "event.started_at"),
            finished_at=self._parse_datetime(row['finished_at'], "event.finished_at") if row['finished_at'] else None,
            duration_ms=row['duration_ms'],
            checkpoint_id=row['checkpoint_id'],
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
        )
    
    def _row_to_checkpoint(self, row) -> Checkpoint:
        """Convert database row to Checkpoint model."""
        return Checkpoint(
            checkpoint_id=row['checkpoint_id'],
            run_id=row['run_id'],
            event_id=row['event_id'],
            sequence_number=row['sequence_number'],
            state=json.loads(row['state']),
            state_hash=row['state_hash'],
            created_at=self._parse_datetime(row['created_at'], "checkpoint.created_at"),
            storage_reference=row['storage_reference'],
        )
    
    def _row_to_diagnosis(self, row) -> Diagnosis:
        """Convert database row to Diagnosis model."""
        rankings_data = json.loads(row['rankings'])
        rankings = [EventRanking(**r) for r in rankings_data]
        suspected_event_ids = (
            json.loads(row['suspected_event_ids'])
            if 'suspected_event_ids' in row.keys() and row['suspected_event_ids']
            else []
        )
        if not suspected_event_ids and row['suspected_event_id']:
            suspected_event_ids = [row['suspected_event_id']]
        
        return Diagnosis(
            diagnosis_id=row['diagnosis_id'],
            run_id=row['run_id'],
            status=row['status'],
            suspected_event_id=row['suspected_event_id'],
            suspected_event_ids=suspected_event_ids,
            confidence=row['confidence'],
            rankings=rankings,
            model_name=row['model_name'],
            model_version=row['model_version'],
            created_at=self._parse_datetime(row['created_at'], "diagnosis.created_at"),
        )
    
    def _row_to_evidence(self, row) -> Evidence:
        """Convert database row to Evidence model."""
        return Evidence(
            evidence_id=row['evidence_id'],
            diagnosis_id=row['diagnosis_id'],
            event_id=row['event_id'],
            evidence_type=row['evidence_type'],
            description=row['description'],
            observed_value=json.loads(row['observed_value']) if row['observed_value'] else None,
            expected_value=json.loads(row['expected_value']) if row['expected_value'] else None,
            source_event_ids=json.loads(row['source_event_ids']),
            strength=row['strength'],
        )
    
    def _row_to_replay_run(self, row) -> ReplayRun:
        """Convert database row to ReplayRun model."""
        return ReplayRun(
            replay_run_id=row['replay_run_id'],
            original_run_id=row['original_run_id'],
            checkpoint_id=row['checkpoint_id'],
            steps_reused=row['steps_reused'],
            steps_reexecuted=row['steps_reexecuted'],
            outcome=row['outcome'],
            created_at=self._parse_datetime(row['created_at'], "replay.created_at"),
        )
    
    def _row_to_counterfactual_run(self, row) -> CounterfactualRun:
        """Convert database row to CounterfactualRun model."""
        return CounterfactualRun(
            counterfactual_run_id=row['counterfactual_run_id'],
            original_run_id=row['original_run_id'],
            modified_event_id=row['modified_event_id'],
            patch=json.loads(row['patch']),
            outcome=row['outcome'],
            validation=json.loads(row['validation']),
            created_at=self._parse_datetime(row['created_at'], "counterfactual.created_at"),
        )
