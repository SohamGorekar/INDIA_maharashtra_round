import { useEffect, useMemo, useState } from 'react'
import * as api from './api'

const pages = [
  ['overview', 'Overview', 'What is happening now'],
  ['runs', 'Runs', 'Every customer request'],
  ['timeline', 'Timeline', 'Step-by-step activity'],
  ['diagnosis', 'Find the problem', 'Why a run failed'],
  ['replay', 'Replay a run', 'Run from a saved point'],
  ['alternative', 'Try an alternative', 'Test a different result'],
  ['compare', 'Compare runs', 'See what changed'],
]
const pretty = (value) => value == null ? '-' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)

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
        if (message.type === 'run_started' && message.run_id) { setRunId(message.run_id); refresh(false).catch(() => {}) }
      },
    })
    return close
  }, [])
  useEffect(() => {
    if (!runId) return undefined
    setTrace(null); setDiagnosis(null); setEvent(null); setEventId(''); setResult(null)
    Promise.all([api.getTrace(runId), api.getCheckpoints(runId)])
      .then(([nextTrace, nextCheckpoints]) => { setTrace(nextTrace); setCheckpoints(nextCheckpoints) })
      .catch((e) => setError(e.message))
    const close = api.streamRun(runId, {
      onOpen: () => { setStatus('Live'); setError('') },
      onError: (e) => { setStatus('Reconnecting'); setError(e.message) },
      onEvent: (message) => {
        if (message.event) setTrace((current) => current ? {
          ...current, events: [...(current.events || []).filter((item) => item.event_id !== message.event.event_id), message.event],
        } : current)
        if (message.checkpoint) setCheckpoints((current) => [...current, message.checkpoint])
        if (message.type === 'run_completed' || message.type === 'run_failed') { setStatus(message.type === 'run_completed' ? 'Complete' : 'Failed'); refresh(false).catch(() => {}) }
      },
    })
    return close
  }, [runId])
  useEffect(() => {
    if (!runId || !eventId) return
    api.getEvent(runId, eventId).then(setEvent).catch((e) => setError(e.message))
  }, [runId, eventId])

  const events = useMemo(() => [...(trace?.events || [])].sort((a, b) => a.sequence_number - b.sequence_number), [trace])
  const selectedRun = runs.find((run) => run.run_id === runId) || trace?.run
  const doAction = async (action) => { setError(''); try { setResult(await action()) } catch (e) { setError(e.message) } }

  return <div className="shell">
    <aside className="sidebar">
      <div className="logo">Black Box <small>Agent activity monitor</small></div>
      <div className="connection"><span className={`dot ${status.toLowerCase()}`} /> {status}</div>
      <label className="side-label">Explore</label>
      {pages.map(([id, title, hint]) => <button key={id} className={page === id ? 'nav active' : 'nav'} onClick={() => setPage(id)}>
        <strong>{title}</strong><small>{hint}</small>
      </button>)}
      <label className="side-label">Choose a request</label>
      <select value={runId} onChange={(e) => setRunId(e.target.value)}><option value="">Select a run</option>{runs.map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id} · {run.status}</option>)}</select>
      <button className="refresh" onClick={() => refresh(false)}>Refresh requests</button>
    </aside>
    <main className="content">
      <header><div><p className="eyebrow">BLACK BOX MONITOR</p><h1>{pages.find(([id]) => id === page)?.[1]}</h1><p className="subtitle">{pages.find(([id]) => id === page)?.[2]}</p></div>
        {selectedRun && <div className="run-badge"><span>Watching</span><b>{selectedRun.run_id}</b><small>{selectedRun.metadata?.source === 'customer_chat' ? 'Customer conversation' : 'Test run'}</small></div>}</header>
      {error && <div className="error">{error}</div>}
      {!runId ? <Empty /> : <Page page={page} trace={trace} runs={runs} events={events} event={event} eventId={eventId} setEventId={setEventId} checkpoints={checkpoints} diagnosis={diagnosis} setDiagnosis={setDiagnosis} runId={runId} setRunId={setRunId} otherRun={otherRun} setOtherRun={setOtherRun} patch={patch} setPatch={setPatch} safeMode={safeMode} setSafeMode={setSafeMode} result={result} doAction={doAction} />}
    </main>
  </div>
}

function Empty() { return <div className="empty"><h2>Waiting for a customer request</h2><p>Open the customer support app and send a message. This screen will automatically select the new request.</p></div> }
function Page({ page, trace, runs, events, event, eventId, setEventId, checkpoints, diagnosis, setDiagnosis, runId, setRunId, otherRun, setOtherRun, patch, setPatch, safeMode, setSafeMode, result, doAction }) {
  if (page === 'overview') return <><Cards run={trace?.run} events={events} checkpoints={checkpoints} /><section className="card"><h2>What happened?</h2><p>This request came from <b>{trace?.run?.metadata?.customer_id || 'the test page'}</b>. Each row below is one action performed by the support agent.</p><Activity events={events.slice(-5)} onSelect={setEventId} /></section></>
  if (page === 'runs') return <section className="card"><h2>Customer requests</h2><p>Choose a request to inspect. A run is one complete answer produced by the support agent.</p><div className="run-table">{runs.map((run) => <button key={run.run_id} onClick={() => { setRunId(run.run_id); setEventId(''); window.scrollTo(0, 0) }} className={run.run_id === runId ? 'selected' : ''}><b>{run.run_id}</b><span>{run.metadata?.customer_id || 'Test'} · {run.metadata?.order_id || 'No order'}</span><Status value={run.status} /></button>)}</div></section>
  if (page === 'timeline') return <section className="card"><h2>What did the agent do?</h2><p>Read from top to bottom. Blue means the model thought, green means a tool checked data, and orange means the workflow moved to its next step.</p><Activity events={events} onSelect={setEventId} /><Details event={event} /></section>
  if (page === 'diagnosis') return <section className="card"><h2>Why did it fail?</h2><p>This checks the recorded steps for unusual behavior. It is a helpful lead, not a guaranteed answer.</p><button className="primary" onClick={() => doAction(() => api.diagnose(runId).then(setDiagnosis))}>Analyze this request</button>{diagnosis && <pre>{pretty(diagnosis)}</pre>}</section>
  if (page === 'replay') return <ActionPage title="Replay a saved point" text="Replay safely from a checkpoint to see what happened after that moment." controls={<><select id="checkpoint">{checkpoints.map((c) => <option key={c.checkpoint_id} value={c.checkpoint_id}>Step {c.sequence_number}: {c.checkpoint_id}</option>)}</select><label className="check"><input type="checkbox" checked={safeMode} onChange={(e) => setSafeMode(e.target.checked)} /> Safe mode (recommended)</label><button className="primary" onClick={() => doAction(() => api.replay(runId, document.getElementById('checkpoint').value, safeMode))}>Start replay</button></>} result={result} />
  if (page === 'alternative') return <ActionPage title="Try a different result" text="Choose a step and provide a replacement output. The original run is never changed." controls={<><select value={eventId} onChange={(e) => setEventId(e.target.value)}><option value="">Choose a step</option>{events.map((e) => <option key={e.event_id} value={e.event_id}>{e.sequence_number}: {e.component_name}</option>)}</select><textarea value={patch} onChange={(e) => setPatch(e.target.value)} /><button className="primary" disabled={!eventId} onClick={() => { try { doAction(() => api.counterfactual(runId, eventId, JSON.parse(patch), safeMode)) } catch (error) { doAction(() => Promise.reject(error)) } }}>Run alternative safely</button></>} result={result} />
  return <section className="card"><h2>Compare two requests</h2><p>See which steps and final results changed between two runs.</p><select value={otherRun} onChange={(e) => setOtherRun(e.target.value)}><option value="">Choose another run</option>{runs.filter((run) => run.run_id !== runId).map((run) => <option key={run.run_id} value={run.run_id}>{run.run_id}</option>)}</select><button className="primary" disabled={!otherRun} onClick={() => doAction(() => api.compare(runId, otherRun))}>Compare them</button>{result && <pre>{pretty(result)}</pre>}</section>
}
function Cards({ run, events, checkpoints }) { return <div className="cards"><div><span>Status</span><b><Status value={run?.status} /></b></div><div><span>Steps recorded</span><b>{events.length}</b></div><div><span>Saved points</span><b>{checkpoints.length}</b></div><div><span>Final answer</span><b>{run?.metadata?.final_decision || 'In progress'}</b></div></div> }
function Status({ value }) { return <span className={`status ${value || 'unknown'}`}>{value || 'unknown'}</span> }
function Activity({ events, onSelect }) { if (!events.length) return <div className="empty small">No steps recorded yet.</div>; return <div className="activity">{events.map((item) => <button key={item.event_id} onClick={() => onSelect(item.event_id)} className={`activity-row ${item.component_type}`}><i>{item.sequence_number}</i><span><b>{item.component_name}</b><small>{item.component_type === 'llm' ? 'The AI decided what to do' : item.component_type === 'tool' ? 'The agent checked or changed data' : 'The workflow moved forward'} · {item.status}</small></span><em>{item.duration_ms == null ? '-' : `${Math.round(item.duration_ms)} ms`}</em></button>)}</div> }
function Details({ event }) { return event ? <div className="details"><h3>Step details</h3><p><b>{event.event.component_name}</b> — {event.event.status}</p><pre>{pretty(event.event.output || event.event.input)}</pre></div> : <p className="hint">Select a step to see what went in and what came out.</p> }
function ActionPage({ title, text, controls, result }) { return <section className="card action"><h2>{title}</h2><p>{text}</p>{controls}{result && <pre>{pretty(result)}</pre>}</section> }
