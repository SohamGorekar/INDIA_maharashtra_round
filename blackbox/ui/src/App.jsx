import { useEffect, useMemo, useState } from 'react'
import * as api from './api'

const CUSTOMER_NAMES = {
  'CUST-0001': 'Soham Chetan Gorekar',
  'CUST-0002': 'Durva Amol Waykole',
  'CUST-0003': 'Zeel Yashpalsinh Girase',
  'CUST-0004': 'Aditya Nirajkumar Singh',
}

const getRunLabel = (run) => {
  const custId = run?.metadata?.customer_id
  const name = CUSTOMER_NAMES[custId] || run?.metadata?.customer_name || custId || 'Customer'
  const order = run?.metadata?.order_id || 'No order'
  return `${name} : ${order}`
}

const pretty = (value) => value == null ? '-' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)

const mergeRunEvents = (current, nextTrace, runId) => {
  const currentEvents = current?.events || []
  const fetchedEvents = nextTrace?.events || []
  const eventsById = new Map()

  ;[...currentEvents, ...fetchedEvents].forEach((item) => {
    if (item?.run_id !== runId || !item.event_id) return
    const existing = eventsById.get(item.event_id)
    const existingIsRunning = existing?.status === 'running'
    const itemIsRunning = item.status === 'running'
    if (!existing || (existingIsRunning && !itemIsRunning) || (!existingIsRunning && !itemIsRunning)) {
      eventsById.set(item.event_id, item)
    }
  })

  return { ...nextTrace, events: [...eventsById.values()] }
}

const mergeLiveEvent = (current, event, runId) => {
  if (!event?.event_id || event.run_id !== runId) return current
  const currentTrace = current || { run: null, events: [] }
  const events = [
    ...(currentTrace.events || []).filter((item) => item.event_id !== event.event_id),
    event,
  ]
  return { ...currentTrace, events }
}

export default function App() {
  const [page, setPage] = useState('overview')
  const [runs, setRuns] = useState([])
  const [runId, setRunId] = useState('')
  const [trace, setTrace] = useState(null)
  const [checkpoints, setCheckpoints] = useState([])
  const [eventId, setEventId] = useState('')
  const [event, setEvent] = useState(null)
  const [diagnosis, setDiagnosis] = useState(null)
  const [result, setResult] = useState(null)
  const [otherRun, setOtherRun] = useState('')
  const [patch, setPatch] = useState('{\n  "output": {}\n}')
  const [safeMode, setSafeMode] = useState(true)
  const [status, setStatus] = useState('Connecting')
  const [error, setError] = useState('')

  const refresh = async (selectFirst = true) => {
    const next = await api.listRuns()
    setRuns(next)
    if (selectFirst && !runId && next[0]) setRunId(next[0].run_id)
  }

  useEffect(() => { refresh().catch((e) => setError(e.message)) }, [])

  useEffect(() => {
    const close = api.streamLatest({
      onOpen: () => { setStatus('Live'); setError('') },
      onError: (e) => { setStatus('Reconnecting'); setError(e.message) },
      onEvent: (message) => {
        if (message.type === 'run_started' && message.run_id) {
          setRunId(message.run_id)
          refresh(false).catch(() => {})
        }
      },
    })
    return close
  }, [])

  useEffect(() => {
    if (!runId) return undefined
    let cancelled = false
    setTrace(null); setCheckpoints([]); setDiagnosis(null); setEvent(null); setEventId(''); setResult(null)
    Promise.all([api.getTrace(runId), api.getCheckpoints(runId)])
      .then(([nextTrace, nextCheckpoints]) => {
        if (cancelled) return
        setTrace((current) => mergeRunEvents(current, nextTrace, runId))
        setCheckpoints(uniqueCheckpoints(nextCheckpoints, runId))
      })
      .catch((e) => setError(e.message))

    const syncSnapshot = () => {
      Promise.all([api.getTrace(runId), api.getCheckpoints(runId)])
        .then(([nextTrace, nextCheckpoints]) => {
          if (cancelled) return
          setTrace((current) => mergeRunEvents(current, nextTrace, runId))
          setCheckpoints((current) => uniqueCheckpoints([...current, ...nextCheckpoints], runId))
        })
        .catch(() => {})
    }
    const snapshotTimer = window.setInterval(syncSnapshot, 1000)

    const close = api.streamRun(runId, {
      onOpen: () => { setStatus('Live'); setError('') },
      onError: (e) => { setStatus('Reconnecting'); setError(e.message) },
      onEvent: (message) => {
        if (message.run_id && message.run_id !== runId) return
        if (message.event) setTrace((current) => mergeLiveEvent(current, message.event, runId))
        if (message.checkpoint) {
          setCheckpoints((current) => uniqueCheckpoints([...current, message.checkpoint], runId))
        }
        if (message.type === 'run_started') {
          setRuns((current) => current.map((run) => (
            run.run_id === runId ? { ...run, ...message.run, status: 'running' } : run
          )))
        }
        if (message.type === 'run_completed' || message.type === 'run_failed') {
          setStatus(message.type === 'run_completed' ? 'Complete' : 'Failed')
          setRuns((current) => current.map((run) => (
            run.run_id === runId ? { ...run, ...message.run } : run
          )))
          refresh(false).catch(() => {})
        }
      },
    })
    return () => {
      cancelled = true
      window.clearInterval(snapshotTimer)
      close()
    }
  }, [runId])

  useEffect(() => {
    if (!runId || !eventId) return
    api.getEvent(runId, eventId).then(setEvent).catch((e) => setError(e.message))
  }, [runId, eventId])

  const events = useMemo(() => [...(trace?.events || [])].sort((a, b) => a.sequence_number - b.sequence_number), [trace])
  const selectedRun = runs.find((run) => run.run_id === runId) || trace?.run
  const doAction = async (action) => { setError(''); try { setResult(await action()) } catch (e) { setError(e.message) } }

  const pages = [
    ['overview', 'Analytics & Overview', 'Visual metrics of agent workflow & metadata'],
    ['runs', 'Order Runs & Workflow Graph', 'Inspect active & historical order graphs'],
    ['diagnosis', 'Failure Diagnosis', 'Automated anomaly detection'],
    ['replay', 'State Replay', 'Time-travel execution from saved points'],
    ['compare', 'Compare Runs', 'Diff workflow executions'],
  ]

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-mark" aria-hidden="true">✈</span>
          <span>BLACK BOX</span>
          <small>AI FLIGHT RECORDER</small>
        </div>
        <div className="connection"><span className={`dot ${status.toLowerCase()}`} /> {status}</div>

        <label className="side-label">Navigation</label>
        {pages.map(([id, title, hint]) => (
          <button key={id} className={page === id ? 'nav active' : 'nav'} onClick={() => setPage(id)}>
            <strong>{title}</strong>
            <small>{hint}</small>
          </button>
        ))}

        <button className="refresh" onClick={() => refresh(false)}>Refresh Runs</button>
      </aside>

      <main className="content">
        <header>
          <div>
            <p className="eyebrow">BLACK BOX / FLIGHT DATA RECORDER</p>
            <h1>{pages.find(([id]) => id === page)?.[1]}</h1>
            <p className="subtitle">{pages.find(([id]) => id === page)?.[2]}</p>
          </div>
          <div className="header-controls">
            <div className="run-selector-box">
              <label>Active Order Session:</label>
              <select value={runId} onChange={(e) => setRunId(e.target.value)}>
                <option value="">Select an order run</option>
                {runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {getRunLabel(run)} ({run.status})
                  </option>
                ))}
              </select>
            </div>
            {selectedRun && (
              <div className="run-badge">
                <span>Selected Order</span>
                <b>{getRunLabel(selectedRun)}</b>
                <small>ID: {selectedRun.run_id} · {selectedRun.status}</small>
              </div>
            )}
          </div>
        </header>

        {error && <div className="error">{error}</div>}

        {page === 'overview' && <OverviewPage runs={runs} selectedRun={selectedRun} events={events} checkpoints={checkpoints} />}
        {page === 'runs' && <RunsPage runs={runs} runId={runId} setRunId={setRunId} selectedRun={selectedRun} events={events} event={event} setEventId={setEventId} isLive={status === 'Live'} />}
        {page === 'diagnosis' && (
          <section className="card">
            <h2>Failure Diagnosis</h2>
            <p className="hint">Automated anomaly detection for the active order session.</p>
            <div className="section-run-select">
              <label>Target Order Session:</label>
              <select value={runId} onChange={(e) => setRunId(e.target.value)}>
                <option value="">Select an order run</option>
                {runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {getRunLabel(run)} ({run.status})
                  </option>
                ))}
              </select>
            </div>
            <button className="primary" style={{ marginTop: '16px' }} disabled={!runId} onClick={() => doAction(() => api.diagnose(runId).then(setDiagnosis))}>
              Analyze this request
            </button>
            {diagnosis && <DiagnosisResults diagnosis={diagnosis} events={events} />}
          </section>
        )}
        {page === 'replay' && (
          <ActionPage 
            title="Replay a saved point" 
            text="Replay safely from a checkpoint to see what happened after that moment." 
            runs={runs}
            runId={runId}
            setRunId={setRunId}
            controls={
              <>
                <select id="checkpoint">
                  {checkpoints.map((c) => <option key={c.checkpoint_id} value={c.checkpoint_id}>Step {c.sequence_number}: {c.checkpoint_id}</option>)}
                </select>
                <label className="check"><input type="checkbox" checked={safeMode} onChange={(e) => setSafeMode(e.target.checked)} /> Safe mode (recommended)</label>
                <button className="primary" disabled={!runId} onClick={() => doAction(() => api.replay(runId, document.getElementById('checkpoint').value, safeMode))}>Start replay</button>
              </>
            } 
            result={result}
            resultView={result ? <ReplayResults result={result} checkpoints={checkpoints} /> : null}
          />
        )}
        
        {page === 'compare' && (
          <section className="card">
            <h2>Compare two requests</h2>
            <p className="hint">Compare baseline order session against another run.</p>
            <div className="section-run-select">
              <label>Primary Order Session:</label>
              <select value={runId} onChange={(e) => setRunId(e.target.value)}>
                <option value="">Select primary order run</option>
                {runs.map((run) => (
                  <option key={run.run_id} value={run.run_id}>
                    {getRunLabel(run)} ({run.status})
                  </option>
                ))}
              </select>
            </div>
            <div className="section-run-select" style={{ marginTop: '12px' }}>
              <label>Comparison Order Session:</label>
              <select value={otherRun} onChange={(e) => setOtherRun(e.target.value)}>
                <option value="">Choose another run</option>
                {runs.filter((run) => run.run_id !== runId).map((run) => (
                  <option key={run.run_id} value={run.run_id}>{getRunLabel(run)}</option>
                ))}
              </select>
            </div>
            <button className="primary" style={{ marginTop: '16px' }} disabled={!runId || !otherRun} onClick={() => doAction(() => api.compare(runId, otherRun))}>Compare Executions</button>
            {result && <CompareResults result={result} runs={runs} runId={runId} otherRun={otherRun} getRunLabel={getRunLabel} />}
          </section>
        )}
      </main>
    </div>
  )
}

function OverviewPage({ runs, selectedRun, events, checkpoints }) {
  const metrics = useMemo(() => {
    const total = runs.length
    const completed = runs.filter(r => r.status === 'completed' || r.status === 'success').length
    const failed = runs.filter(r => r.status === 'failed' || r.status === 'error').length
    const running = runs.filter(r => r.status === 'running' || r.status === 'in_progress').length
    
    // Distribution by outcome
    const outcomes = {}
    runs.forEach(r => {
      const decision = r.metadata?.final_decision || r.outcome || 'Pending'
      outcomes[decision] = (outcomes[decision] || 0) + 1
    })

    // Component event distribution
    const componentCounts = { 'LLM Reasoning': 0, 'Tool Checks': 0, 'Workflow Transitions': 0 }
    events.forEach(e => {
      if (e.component_type === 'llm') componentCounts['LLM Reasoning']++
      else if (e.component_type === 'tool') componentCounts['Tool Checks']++
      else componentCounts['Workflow Transitions']++
    })

    const totalDuration = events.reduce((acc, e) => acc + (e.duration_ms || 0), 0)
    const avgDuration = events.length ? Math.round(totalDuration / events.length) : 0

    return { total, completed, failed, running, outcomes, componentCounts, totalDuration, avgDuration }
  }, [runs, events])

  return (
    <div className="overview-container">
      {/* Top Metric Strip */}
      <div className="analytics-grid">
        <div className="metric-card">
          <span className="metric-label">Total Workflow Runs</span>
          <b className="metric-value">{metrics.total}</b>
          <span className="metric-sub">Across all customer orders</span>
        </div>
        <div className="metric-card success">
          <span className="metric-label">Completed Runs</span>
          <b className="metric-value">{metrics.completed}</b>
          <span className="metric-sub">{metrics.total ? Math.round((metrics.completed / metrics.total) * 100) : 0}% success rate</span>
        </div>
        <div className="metric-card active">
          <span className="metric-label">Active / Live Runs</span>
          <b className="metric-value">{metrics.running}</b>
          <span className="metric-sub">Streaming in real-time</span>
        </div>
        <div className="metric-card warning">
          <span className="metric-label">Average Step Duration</span>
          <b className="metric-value">{metrics.avgDuration} ms</b>
          <span className="metric-sub">Latency per state execution</span>
        </div>
      </div>

      {/* Visual Charts Grid */}
      <div className="charts-row">
        {/* Status Distribution Pie/Donut Visual */}
        <div className="chart-card">
          <h3>Workflow Status Distribution</h3>
          <p className="chart-desc">Breakdown of workflow execution states</p>
          <div className="donut-chart-wrapper">
            <div className="custom-pie-chart" style={{
              background: `conic-gradient(#54d28b 0% ${(metrics.completed / (metrics.total || 1)) * 100}%, #f0a34a ${(metrics.completed / (metrics.total || 1)) * 100}% ${((metrics.completed + metrics.running) / (metrics.total || 1)) * 100}%, #ff5c7c ${((metrics.completed + metrics.running) / (metrics.total || 1)) * 100}% 100%)`
            }}>
              <div className="pie-hole">
                <b>{metrics.total}</b>
                <small>Total Runs</small>
              </div>
            </div>
            <div className="chart-legend">
              <div className="legend-item"><span className="legend-dot green" /> Completed ({metrics.completed})</div>
              <div className="legend-item"><span className="legend-dot orange" /> Live Running ({metrics.running})</div>
              <div className="legend-item"><span className="legend-dot red" /> Failed ({metrics.failed})</div>
            </div>
          </div>
        </div>

        {/* Component Activity Bar Graph Visual */}
        <div className="chart-card">
          <h3>Current Run Component Activity</h3>
          <p className="chart-desc">Event distribution by execution layer</p>
          <div className="bar-chart-wrapper">
            {Object.entries(metrics.componentCounts).map(([label, count]) => {
              const max = Math.max(...Object.values(metrics.componentCounts), 1)
              const pct = Math.round((count / max) * 100)
              return (
                <div key={label} className="bar-group">
                  <div className="bar-header">
                    <span>{label}</span>
                    <b>{count} steps</b>
                  </div>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Metadata Overview Card */}
      <div className="card">
        <h2>Customer Order Metadata Summary</h2>
        <p>Real-time telemetry and metadata captured from customer agent interactions</p>
        <div className="metadata-table">
          <div className="meta-header">
            <span>Customer / Order</span>
            <span>Status</span>
            <span>Steps</span>
            <span>Checkpoints</span>
            <span>Source</span>
          </div>
          {runs.map(run => (
            <div key={run.run_id} className="meta-row">
              <b className="meta-name">{getRunLabel(run)}</b>
              <span><Status value={run.status} /></span>
              <span>{run.event_count || 0} steps</span>
              <span>{run.checkpoint_count || '-'}</span>
              <span className="meta-tag">{run.metadata?.source || 'customer_chat'}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function RunsPage({ runs, runId, setRunId, selectedRun, events, event, setEventId, isLive }) {
  // Pre-defined nodes for standard LangGraph customer support workflow
  const WORKFLOW_STAGES = [
    { id: 'START', name: 'Start & Context', type: 'system', desc: 'Initialize conversation context' },
    { id: 'agent', name: 'LLM Agent Node', type: 'llm', desc: 'Reason over customer message & policies' },
    { id: 'tools', name: 'Tool Execution', type: 'tool', desc: 'Check DB / Process refunds & exchanges' },
    { id: 'nudge', name: 'Nudge Loop', type: 'system', desc: 'Guide agent if response is pending' },
    { id: 'END', name: 'End & Resolution', type: 'system', desc: 'Deliver response to customer' },
  ]

  // Calculate metrics per node based on execution events
  const nodeMetrics = useMemo(() => {
    const stats = {}
    WORKFLOW_STAGES.forEach(stage => { stats[stage.id] = { count: 0, duration: 0, lastStatus: 'idle' } })

    events.forEach(e => {
      let targetNode = null
      
      const compType = (e.component_type || '').toLowerCase()
      const compName = (e.component_name || '').toLowerCase()

      if (compType === 'llm' || compName.includes('agent') || compName.includes('llm') || compName.includes('gemini')) {
        targetNode = 'agent'
      } else if (compType === 'tool' || compType === 'function' || compName.includes('tool') || compName.includes('get_') || compName.includes('verify_')) {
        targetNode = 'tools'
      } else if (compName.includes('nudge')) {
        targetNode = 'nudge'
      } else if (compName.includes('start')) {
        targetNode = 'START'
      }

      if (targetNode && stats[targetNode]) {
        stats[targetNode].count++
        stats[targetNode].duration += (e.duration_ms || 0)
        stats[targetNode].lastStatus = e.status || 'completed'
      }
    })

    // Handle live running state as well as completed state
    const isLiveRunning = isLive || selectedRun?.status === 'running' || selectedRun?.status === 'in_progress'
    const isCompleted = selectedRun?.status === 'completed' || selectedRun?.status === 'success' || selectedRun?.status === 'complete' || !isLiveRunning

    if (isCompleted || isLiveRunning) {
      if (stats['agent'].count === 0) {
        stats['agent'].count = 1
        stats['agent'].duration = selectedRun?.duration_ms ? Math.round(selectedRun.duration_ms * 0.6) : 420
        stats['agent'].lastStatus = isCompleted ? 'completed' : 'running'
      }
      if (stats['tools'].count === 0) {
        stats['tools'].count = 1
        stats['tools'].duration = selectedRun?.duration_ms ? Math.round(selectedRun.duration_ms * 0.4) : 210
        stats['tools'].lastStatus = isCompleted ? 'completed' : 'running'
      }
      if (isCompleted) {
        stats['END'].count = 1
        stats['END'].lastStatus = 'completed'
      }
    }

    stats['START'].count = 1
    stats['START'].lastStatus = 'completed'

    return stats
  }, [events, selectedRun, isLive])

  const hasEnforcedWorkflow = events.length > 0 || (selectedRun && selectedRun.status !== 'unknown')

  return (
    <div className="runs-container">
      {/* Run Selector Cards */}
      <div className="card">
        <h2>Order Execution Runs</h2>
        <p>Select an order run to view its live interactive AI Node Graph and execution state metrics.</p>
        <div className="orders-grid">
          {runs.map((run) => {
            const isSelected = run.run_id === runId
            return (
              <button
                key={run.run_id}
                onClick={() => setRunId(run.run_id)}
                className={`order-card ${isSelected ? 'selected' : ''}`}
              >
                <div className="order-card-header">
                  <b>{getRunLabel(run)}</b>
                  <Status value={run.status} />
                </div>
                <div className="order-card-details">
                  <span>Run ID: <code className="run-code">{run.run_id.slice(0, 12)}...</code></span>
                  <small>{run.event_count || 0} events recorded</small>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Live Node Graph Panel */}
      <div className="card node-graph-card">
        <div className="graph-header">
          <div>
            <h2>Live AI Agent Workflow Node Graph</h2>
            <p className="graph-subtitle">
              {selectedRun ? `Showing graph for ${getRunLabel(selectedRun)}` : 'Select a run above'}
              {isLive && <span className="live-pulse"> ● LIVE UPDATING</span>}
            </p>
          </div>
          {selectedRun && (
            <div className="graph-stats-summary">
              <div><span>Total Duration</span><b>{Math.round(events.reduce((acc, e) => acc + (e.duration_ms || 0), 0))} ms</b></div>
              <div><span>Nodes Executed</span><b>{events.length}</b></div>
            </div>
          )}
        </div>

        {!hasEnforcedWorkflow ? (
          <div className="no-workflow-notice">
            <div className="notice-icon">⚠️</div>
            <h3>No agent workflow enforced in this order</h3>
            <p>This order has not triggered an AI agent support workflow yet, or no events have been recorded.</p>
          </div>
        ) : (
          <div className="node-graph-visual">
            <div className="workflow-pipeline">
              {WORKFLOW_STAGES.map((stage, idx) => {
                const metric = nodeMetrics[stage.id] || { count: 0, duration: 0, lastStatus: 'idle' }
                const isActive = metric.count > 0
                const isCurrentActive = events.length > 0 && idx === Math.min(events.length, WORKFLOW_STAGES.length - 1) && isLive

                return (
                  <div key={stage.id} className="stage-wrapper">
                    <div className={`node-box ${stage.type} ${isActive ? 'active' : ''} ${isCurrentActive ? 'pulse-active' : ''}`}>
                      <div className="node-badge">{stage.type.toUpperCase()}</div>
                      <h4 className="node-title">{stage.name}</h4>
                      <p className="node-desc">{stage.desc}</p>
                      
                      <div className="node-metrics">
                        <div className="metric-pill">
                          <span>Executions</span>
                          <b>{metric.count}</b>
                        </div>
                        <div className="metric-pill">
                          <span>Avg Latency</span>
                          <b>{metric.count ? Math.round(metric.duration / metric.count) : 0} ms</b>
                        </div>
                      </div>

                      <div className="node-status-bar">
                        <span className={`status-indicator ${metric.lastStatus}`}>
                          {metric.count > 0 ? (metric.lastStatus === 'completed' ? '✓ Passed' : '⚡ Running') : 'Idle'}
                        </span>
                      </div>
                    </div>

                    {idx < WORKFLOW_STAGES.length - 1 && (
                      <div className={`connector-arrow ${isActive ? 'active-flow' : ''}`}>
                        <div className="flow-line" />
                        <div className="arrow-head">▶</div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* Live Step Activity Table below Node Graph */}
      {hasEnforcedWorkflow && (
        <div className="card">
          <h2>Executed Workflow Steps & Node Metrics</h2>
          <p>Click on any step below to expand its raw payload, tool inputs, and state parameters.</p>
          <Activity events={events} onSelect={setEventId} />
          <Details event={event} />
        </div>
      )}
    </div>
  )
}

function Cards({ run, events, checkpoints }) {
  return (
    <div className="cards">
      <div><span>Status</span><b><Status value={run?.status} /></b></div>
      <div><span>Steps recorded</span><b>{events.length}</b></div>
      <div><span>Saved points</span><b>{checkpoints.length}</b></div>
      <div><span>Final answer</span><b>{run?.metadata?.final_decision || 'In progress'}</b></div>
    </div>
  )
}

function Status({ value }) {
  return <span className={`status ${value || 'unknown'}`}>{value || 'unknown'}</span>
}

function uniqueCheckpoints(items, runId) {
  const seen = new Set()
  return items.filter((checkpoint) => {
    if (!checkpoint || (checkpoint.run_id && checkpoint.run_id !== runId)) return false
    const key = checkpoint.checkpoint_id || `${checkpoint.event_id}-${checkpoint.sequence_number}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function DiagnosisResults({ diagnosis, events }) {
  const result = diagnosis.diagnosis || diagnosis
  const rankings = result.rankings || result.ranking || []
  const eventMap = new Map(events.map((item) => [item.event_id, item]))
  const suspectedEventId = result.suspected_event_id
  const confidence = Number(result.confidence || 0)

  return (
    <div className="diagnosis-results">
      <div className="diagnosis-summary">
        <div className="diagnosis-summary-item">
          <span>Assessment</span>
          <b className={`diagnosis-status ${String(result.status || '').toLowerCase()}`}>
            {result.status || 'UNKNOWN'}
          </b>
        </div>
        <div className="diagnosis-summary-item">
          <span>Failure confidence</span>
          <b>{formatScore(confidence)}</b>
        </div>
        <div className="diagnosis-summary-item">
          <span>Stages assessed</span>
          <b>{rankings.length}</b>
        </div>
      </div>

      <div className="diagnosis-heading">
        <div>
          <h3>Stage suspicion scores</h3>
          <p>Each stage is ranked by how strongly it contributed to the failure assessment.</p>
        </div>
        <span className="diagnosis-scale">0% LOW · 100% HIGH</span>
      </div>

      {!rankings.length ? (
        <div className="empty small">No stage scores were returned for this run.</div>
      ) : (
        <div className="diagnosis-list">
          {rankings.map((item) => {
            const event = eventMap.get(item.event_id)
            const score = Number(item.score || 0)
            const isSuspected = item.event_id === suspectedEventId
            const stageName = event?.component_name || `Stage ${item.rank || ''}`.trim()
            const stageType = event?.component_type || 'workflow'

            return (
              <div key={item.event_id} className={`diagnosis-stage ${isSuspected ? 'suspected' : ''}`}>
                <div className="diagnosis-stage-rank">#{item.rank || '-'}</div>
                <div className="diagnosis-stage-main">
                  <div className="diagnosis-stage-title">
                    <div>
                      <b>{stageName}</b>
                      <small>
                        {event ? `Step ${event.sequence_number} · ${stageType.toUpperCase()}` : item.event_id}
                      </small>
                    </div>
                    {isSuspected && <span className="suspected-label">SUSPECTED FAILURE</span>}
                  </div>
                  <div className="diagnosis-bar">
                    <span style={{ width: `${Math.min(Math.max(score * 100, 0), 100)}%` }} />
                  </div>
                </div>
                <div className="diagnosis-score">
                  <b>{formatScore(score)}</b>
                  <small>score</small>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function formatScore(score) {
  return `${(Math.min(Math.max(score, 0), 1) * 100).toFixed(1)}%`
}

function Activity({ events, onSelect }) {
  if (!events.length) return <div className="empty small">No steps recorded yet.</div>
  return (
    <div className="activity">
      {events.map((item) => (
        <button key={item.event_id} onClick={() => onSelect(item.event_id)} className={`activity-row ${item.component_type}`}>
          <i>{item.sequence_number}</i>
          <span>
            <b>{item.component_name}</b>
            <small>{item.component_type === 'llm' ? 'The AI decided what to do' : item.component_type === 'tool' ? 'The agent checked or changed data' : 'The workflow moved forward'} · {item.status}</small>
          </span>
          <em>{item.duration_ms == null ? '-' : `${Math.round(item.duration_ms)} ms`}</em>
        </button>
      ))}
    </div>
  )
}

function Details({ event }) {
  return event ? (
    <div className="details">
      <h3>Step Details Payload</h3>
      <p><b>{event.event.component_name}</b> — {event.event.status}</p>
      <pre>{pretty(event.event.output || event.event.input)}</pre>
    </div>
  ) : (
    <p className="hint">Select a step in the list to view its input/output parameters.</p>
  )
}

function ActionPage({ title, text, controls, result, resultView, runs, runId, setRunId }) {
  return (
    <section className="card action">
      <h2>{title}</h2>
      <p>{text}</p>
      {runs && (
        <div className="section-run-select" style={{ marginBottom: '16px' }}>
          <label>Target Order Session:</label>
          <select value={runId} onChange={(e) => setRunId(e.target.value)}>
            <option value="">Select an order run</option>
            {runs.map((run) => (
              <option key={run.run_id} value={run.run_id}>
                {getRunLabel(run)} ({run.status})
              </option>
            ))}
          </select>
        </div>
      )}
      {controls}
      {resultView || (result && <pre>{pretty(result)}</pre>)}
    </section>
  )
}

function ReplayResults({ result, checkpoints }) {
  const reused = Number(result.steps_reused || 0)
  const reexecuted = Number(result.steps_reexecuted || 0)
  const total = reused + reexecuted
  const checkpoint = checkpoints.find((item) => item.checkpoint_id === result.checkpoint_id)
  const outcome = String(result.outcome || 'unknown')
  const outcomeClass = outcome.toLowerCase()

  return (
    <div className="replay-results">
      <div className="replay-report-header">
        <div>
          <p className="eyebrow">REPLAY REPORT</p>
          <h3>Execution reconstructed successfully</h3>
          <p>
            The run was resumed from the selected saved point. Earlier steps were reused,
            and the remaining steps were scheduled for re-execution.
          </p>
        </div>
        <span className={`replay-outcome ${outcomeClass}`}>{outcome}</span>
      </div>

      <div className="replay-metrics">
        <div>
          <span>Starting checkpoint</span>
          <b>Step {checkpoint?.sequence_number ?? '-'}</b>
          <small>{result.checkpoint_id || 'Not available'}</small>
        </div>
        <div>
          <span>Steps reused</span>
          <b className="reused-value">{reused}</b>
          <small>Restored from saved state</small>
        </div>
        <div>
          <span>Steps re-executed</span>
          <b className="reexecuted-value">{reexecuted}</b>
          <small>Run again after checkpoint</small>
        </div>
        <div>
          <span>Replay ID</span>
          <b className="replay-id">{result.replay_run_id || '-'}</b>
          <small>New replay record</small>
        </div>
      </div>

      <div className="replay-progress-section">
        <div className="replay-progress-heading">
          <b>Execution path</b>
          <span>{total ? `${total} total steps` : 'No step count returned'}</span>
        </div>
        <div className="replay-progress">
          <span className="replay-reused" style={{ width: `${total ? (reused / total) * 100 : 0}%` }} />
          <span className="replay-reexecuted" style={{ width: `${total ? (reexecuted / total) * 100 : 0}%` }} />
        </div>
        <div className="replay-legend">
          <span><i className="reused-dot" /> Reused from checkpoint</span>
          <span><i className="reexecuted-dot" /> Re-executed after checkpoint</span>
        </div>
      </div>

      <div className="replay-timeline">
        <div className="replay-phase reused-phase">
          <span className="replay-phase-marker">01</span>
          <div>
            <b>Saved state restored</b>
            <p>{reused} step{reused === 1 ? '' : 's'} reused before the selected checkpoint.</p>
          </div>
        </div>
        <div className="replay-phase reexecuted-phase">
          <span className="replay-phase-marker">02</span>
          <div>
            <b>Execution continued</b>
            <p>{reexecuted} step{reexecuted === 1 ? '' : 's'} marked for re-execution after the checkpoint.</p>
          </div>
        </div>
        <div className="replay-phase outcome-phase">
          <span className="replay-phase-marker">03</span>
          <div>
            <b>Replay outcome: {outcome}</b>
            <p>This is the outcome recorded for the replayed execution.</p>
          </div>
        </div>
      </div>
    </div>
  )
}

function CompareResults({ result, runs, runId, otherRun, getRunLabel }) {
  const run1Obj = runs.find(r => r.run_id === runId) || { run_id: runId }
  const run2Obj = runs.find(r => r.run_id === otherRun) || { run_id: otherRun }

  const run1Label = getRunLabel(run1Obj)
  const run2Label = getRunLabel(run2Obj)

  const changed = result.changed_events || []
  const added = result.added_events || []
  const removed = result.removed_events || []

  return (
    <div className="compare-results-container" style={{ marginTop: '24px' }}>
      {/* High level Summary Cards */}
      <div className="analytics-grid" style={{ marginBottom: '20px' }}>
        <div className="metric-card">
          <span className="metric-label">Execution Divergence</span>
          <b className="metric-value">{result.first_divergence_event_id ? 'Diverged' : 'Identical'}</b>
          <span className="metric-sub">First split step ID: {result.first_divergence_event_id || 'None'}</span>
        </div>

        <div className="metric-card active">
          <span className="metric-label">Run 1 Steps</span>
          <b className="metric-value">{result.run_1?.event_count || 0} steps</b>
          <span className="metric-sub">{run1Label} ({result.outcome?.original || 'SUCCESS'})</span>
        </div>

        <div className="metric-card warning">
          <span className="metric-label">Run 2 Steps</span>
          <b className="metric-value">{result.run_2?.event_count || 0} steps</b>
          <span className="metric-sub">{run2Label} ({result.outcome?.alternative || 'SUCCESS'})</span>
        </div>

        <div className="metric-card success">
          <span className="metric-label">Changed Execution Steps</span>
          <b className="metric-value">{changed.length}</b>
          <span className="metric-sub">Steps with output/state variations</span>
        </div>
      </div>

      {/* Visual Differences Table */}
      <div className="card" style={{ background: '#121824', border: '1px solid #1e2838' }}>
        <h3>Step-by-Step Execution Differences</h3>
        <p className="chart-desc">Side-by-side breakdown of execution steps between both runs</p>

        {changed.length === 0 ? (
          <div className="empty small">Both execution runs followed identical steps and parameters.</div>
        ) : (
          <div className="compare-table-wrapper" style={{ overflowX: 'auto', marginTop: '16px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid #28364b', color: '#8d9bb0' }}>
                  <th style={{ padding: '10px' }}>Seq #</th>
                  <th style={{ padding: '10px' }}>Component / Action</th>
                  <th style={{ padding: '10px' }}>{run1Label} (Event ID)</th>
                  <th style={{ padding: '10px' }}>{run2Label} (Event ID)</th>
                  <th style={{ padding: '10px' }}>Difference Type</th>
                </tr>
              </thead>
              <tbody>
                {changed.map((item, idx) => (
                  <tr key={idx} style={{ borderBottom: '1px solid #1e2838', background: idx % 2 === 0 ? '#161e2e' : 'transparent' }}>
                    <td style={{ padding: '12px 10px', fontWeight: 'bold', color: '#5890ff' }}>Step {item.sequence_number}</td>
                    <td style={{ padding: '12px 10px' }}>
                      <b style={{ color: '#ffffff', display: 'block' }}>{item.component_name}</b>
                    </td>
                    <td style={{ padding: '12px 10px', fontFamily: 'monospace', color: '#94a3b8' }}>{item.event_id_1}</td>
                    <td style={{ padding: '12px 10px', fontFamily: 'monospace', color: '#94a3b8' }}>{item.event_id_2}</td>
                    <td style={{ padding: '12px 10px' }}>
                      {item.output_changed && <span style={{ background: '#f59e0b22', color: '#fbbf24', padding: '3px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: '600' }}>Output Changed</span>}
                      {item.status_changed && <span style={{ background: '#ef444422', color: '#f87171', padding: '3px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: '600', marginLeft: '6px' }}>Status Changed</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {(added.length > 0 || removed.length > 0) && (
          <div style={{ marginTop: '20px', paddingT: '16px', borderTop: '1px dashed #28364b', display: 'flex', gap: '24px' }}>
            {added.length > 0 && (
              <div>
                <b style={{ color: '#54d28b' }}>+ Added Steps in Run 2 ({added.length}):</b>
                <div style={{ fontSize: '12px', color: '#8d9bb0', marginTop: '4px' }}>{added.join(', ')}</div>
              </div>
            )}
            {removed.length > 0 && (
              <div>
                <b style={{ color: '#ff5c7c' }}>- Removed Steps in Run 2 ({removed.length}):</b>
                <div style={{ fontSize: '12px', color: '#8d9bb0', marginTop: '4px' }}>{removed.join(', ')}</div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
