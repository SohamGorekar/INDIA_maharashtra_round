# API Contract

Frontend-backend API specification for Black Box.

## Base URL

```
http://localhost:8000/api
```

## Authentication

Currently no authentication. Add JWT/API keys as needed.

## Endpoints

### 1. List Runs

**GET** `/runs`

**Query Parameters**:
- `limit` (int, optional): Max runs to return (default: 100, max: 1000)
- `offset` (int, optional): Pagination offset (default: 0)

**Response**: `200 OK`
```json
[
  {
    "run_id": "run_abc123",
    "status": "completed",
    "outcome": "FAILURE",
    "started_at": "2024-01-15T10:30:00Z",
    "finished_at": "2024-01-15T10:30:05Z",
    "duration_ms": 5234,
    "event_count": 12,
    "metadata": {}
  }
]
```

### 2. Get Run

**GET** `/runs/{run_id}`

**Response**: `200 OK`
```json
{
  "run_id": "run_abc123",
  "status": "completed",
  "outcome": "FAILURE",
  "started_at": "2024-01-15T10:30:00Z",
  "finished_at": "2024-01-15T10:30:05Z",
  "duration_ms": 5234,
  "event_count": 12,
  "root_event_id": "evt_001",
  "metadata": {}
}
```

**Errors**:
- `404`: Run not found

### 3. Get Complete Trace

**GET** `/runs/{run_id}/trace`

Returns everything needed to render the execution graph.

**Response**: `200 OK`
```json
{
  "run": {
    "run_id": "run_abc123",
    "status": "completed",
    "outcome": "FAILURE",
    "started_at": "2024-01-15T10:30:00Z",
    "finished_at": "2024-01-15T10:30:05Z",
    "duration_ms": 5234
  },
  "events": [
    {
      "event_id": "evt_001",
      "parent_event_id": null,
      "sequence_number": 1,
      "component_name": "supervisor",
      "component_type": "agent",
      "status": "success",
      "input": {"task": "Process refund"},
      "output": {"decision": "DENIED"},
      "duration_ms": 1234,
      "checkpoint_id": "cp_001"
    },
    {
      "event_id": "evt_002",
      "parent_event_id": "evt_001",
      "sequence_number": 2,
      "component_name": "check_policy",
      "component_type": "tool",
      "status": "success",
      "input": {"policy_type": "refund"},
      "output": {"eligible": false},
      "duration_ms": 234,
      "checkpoint_id": "cp_002"
    }
  ],
  "diagnosis": {
    "status": "CULPRIT",
    "suspected_event_id": "evt_002",
    "confidence": 0.91,
    "ranking": [
      {"event_id": "evt_002", "score": 0.91, "rank": 1},
      {"event_id": "evt_003", "score": 0.17, "rank": 2}
    ]
  },
  "metadata": {}
}
```

### 4. Get Event Details

**GET** `/runs/{run_id}/events/{event_id}`

**Response**: `200 OK`
```json
{
  "event": {
    "event_id": "evt_002",
    "component_name": "check_policy",
    "component_type": "tool",
    "status": "success",
    "input": {"policy_type": "refund"},
    "output": {"eligible": false},
    "duration_ms": 234
  },
  "state_before": {"context": "..."},
  "state_after": {"context": "..."},
  "checkpoint": {
    "checkpoint_id": "cp_002",
    "state_hash": "abc123..."
  },
  "diagnosis": {
    "suspected_event_id": "evt_002",
    "confidence": 0.91
  },
  "evidence": [
    {
      "evidence_type": "DEVIATION_FROM_SUCCESS",
      "description": "Output differs from successful executions",
      "strength": 0.82
    }
  ]
}
```

### 5. Get Diagnosis

**GET** `/runs/{run_id}/diagnosis`

**Response**: `200 OK` or `null` if no diagnosis
```json
{
  "diagnosis_id": "diag_xyz789",
  "run_id": "run_abc123",
  "status": "CULPRIT",
  "suspected_event_id": "evt_002",
  "confidence": 0.91,
  "ranking": [
    {"event_id": "evt_002", "score": 0.91, "rank": 1},
    {"event_id": "evt_003", "score": 0.17, "rank": 2}
  ],
  "evidence": [
    {
      "evidence_id": "ev_001",
      "event_id": "evt_002",
      "evidence_type": "DEVIATION_FROM_SUCCESS",
      "description": "Output differs substantially from successful executions.",
      "observed_value": {"eligible": false},
      "expected_value": {"eligible": true},
      "source_event_ids": ["evt_002"],
      "strength": 0.82
    }
  ]
}
```

### 6. Get Checkpoints

**GET** `/runs/{run_id}/checkpoints`

**Response**: `200 OK`
```json
[
  {
    "checkpoint_id": "cp_001",
    "run_id": "run_abc123",
    "event_id": "evt_001",
    "sequence_number": 1,
    "state_hash": "abc123...",
    "created_at": "2024-01-15T10:30:01Z"
  }
]
```

### 7. Replay Execution

**POST** `/runs/{run_id}/replay`

**Request Body**:
```json
{
  "checkpoint_id": "cp_002"
}
```

**Response**: `200 OK`
```json
{
  "replay_run_id": "replay_def456",
  "original_run_id": "run_abc123",
  "checkpoint_id": "cp_002",
  "steps_reused": 2,
  "steps_reexecuted": 8,
  "outcome": "FAILURE"
}
```

### 8. Counterfactual Execution

**POST** `/runs/{run_id}/counterfactual`

**Request Body**:
```json
{
  "event_id": "evt_002",
  "patch": {
    "output": {
      "eligible": true
    }
  }
}
```

**Response**: `200 OK`
```json
{
  "counterfactual_run_id": "cf_ghi789",
  "original_run_id": "run_abc123",
  "modified_event_id": "evt_002",
  "outcome": "SUCCESS",
  "validation": {
    "supported": true,
    "reason": "Final outcome changed from FAILURE to SUCCESS after modifying the suspected transition."
  }
}
```

### 9. Compare Traces

**GET** `/runs/{run_id}/compare/{other_run_id}`

**Response**: `200 OK`
```json
{
  "first_divergence_event_id": "evt_002",
  "changed_events": [
    {
      "event_id": "evt_002",
      "input_changed": false,
      "output_changed": true,
      "state_changed": true
    }
  ],
  "added_events": [],
  "removed_events": [],
  "outcome": {
    "original": "FAILURE",
    "alternative": "SUCCESS"
  }
}
```

## Data Types

### Event Status
- `running`
- `success`
- `error`
- `skipped`
- `cached`

### Component Type
- `agent`
- `tool`
- `llm`
- `retriever`
- `router`
- `function`
- `custom`

### Run Outcome
- `SUCCESS`
- `FAILURE`
- `BENIGN` (fault injected but didn't affect outcome)
- `UNKNOWN`

### Diagnosis Status
- `CULPRIT` (high confidence)
- `UNCERTAIN` (medium confidence)
- `BENIGN` (low confidence)

### Evidence Type
- `OUTPUT_ANOMALY`
- `STATE_CHANGE`
- `ERROR`
- `MISSING_STEP`
- `DEVIATION_FROM_SUCCESS`
- `UNEXPECTED_SEQUENCE`
- `LATENCY_ANOMALY`
- `DOWNSTREAM_DEPENDENCY`

## Frontend Recommendations

### Rendering Execution Graph

Use `parent_event_id` to build the tree:

```javascript
function buildTree(events) {
  const nodes = {};
  const roots = [];
  
  // Create node map
  events.forEach(event => {
    nodes[event.event_id] = {
      ...event,
      children: []
    };
  });
  
  // Build parent-child relationships
  events.forEach(event => {
    if (event.parent_event_id && nodes[event.parent_event_id]) {
      nodes[event.parent_event_id].children.push(nodes[event.event_id]);
    } else {
      roots.push(nodes[event.event_id]);
    }
  });
  
  return roots;
}
```

### Highlighting Diagnosis

```javascript
function highlightSuspects(events, diagnosis) {
  if (!diagnosis) return events;
  
  const suspectIds = new Set(
    diagnosis.ranking.slice(0, 3).map(r => r.event_id)
  );
  
  return events.map(event => ({
    ...event,
    isSuspect: suspectIds.has(event.event_id),
    suspectRank: diagnosis.ranking.find(r => r.event_id === event.event_id)?.rank
  }));
}
```

### Evidence Panel

```javascript
function renderEvidence(evidence) {
  return evidence.map(ev => `
    <div class="evidence-item">
      <strong>${ev.evidence_type}</strong>
      <p>${ev.description}</p>
      <div class="strength">Strength: ${(ev.strength * 100).toFixed(0)}%</div>
    </div>
  `).join('');
}
```

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error message"
}
```

**Common Status Codes**:
- `400`: Bad request (invalid parameters)
- `404`: Resource not found
- `500`: Internal server error
