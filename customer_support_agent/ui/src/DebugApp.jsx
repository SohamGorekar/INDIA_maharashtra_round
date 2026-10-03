import { useEffect, useState } from 'react'
import { clearCache, getCustomers, getHealth, getSamples, runAgent } from './api'
import Result from './components/Result'
import Sidebar from './components/Sidebar'

const EMPTY_CUSTOM = {
  customer_id: '',
  message: '',
  request_type: 'refund',
  requested_size: '',
  photo_provided: false,
}

export default function DebugApp() {
  const [health, setHealth] = useState(null)
  const [samples, setSamples] = useState([])
  const [customers, setCustomers] = useState([])
  const [loadError, setLoadError] = useState('')

  const [mode, setMode] = useState('sample')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const [custom, setCustom] = useState(EMPTY_CUSTOM)
  const [dryRun, setDryRun] = useState(true)

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [runError, setRunError] = useState('')
  const [ranMessage, setRanMessage] = useState('')

  // Load everything the UI needs up front. A failure here almost always means
  // the backend isn't running or the database hasn't been seeded, so the
  // message says exactly that rather than showing an empty screen.
  useEffect(() => {
    Promise.all([getHealth(), getSamples(40), getCustomers()])
      .then(([h, s, c]) => {
        setHealth(h)
        setSamples(s)
        setCustomers(c)
        setCustom((prev) => ({
          ...prev,
          customer_id: c[0]?.customer_id ?? '',
        }))
      })
      .catch((err) => setLoadError(err.message))
  }, [])

  const activeRequest =
    mode === 'sample' ? samples[selectedIndex] : custom.message.trim() ? custom : null

  const canRun = Boolean(activeRequest) && !loadError

  async function handleRun() {
    if (!activeRequest) return

    setRunning(true)
    setRunError('')
    setResult(null)
    setRanMessage(activeRequest.message)

    try {
      const payload =
        mode === 'sample'
          ? { ...activeRequest, dry_run: dryRun }
          : { ...custom, order_id: '', expected_decision: '', dry_run: dryRun }
      setResult(await runAgent(payload))
    } catch (err) {
      setRunError(err.message)
    } finally {
      setRunning(false)
      getHealth().then(setHealth).catch(() => {})
    }
  }

  async function handleClearCache() {
    await clearCache().catch(() => {})
    getHealth().then(setHealth).catch(() => {})
  }

  return (
    <div className="app">
      <Sidebar
        mode={mode}
        setMode={setMode}
        samples={samples}
        selectedIndex={selectedIndex}
        setSelectedIndex={setSelectedIndex}
        custom={custom}
        setCustom={setCustom}
        customers={customers}
        dryRun={dryRun}
        setDryRun={setDryRun}
        onRun={handleRun}
        running={running}
        canRun={canRun}
        health={health}
        onClearCache={handleClearCache}
      />

      <main className="main">
        {loadError && (
          <div className="alert">
            <strong>Could not reach the backend.</strong>
            <pre>{loadError}</pre>
            <p className="muted" style={{ marginBottom: 0 }}>
              Start it with <code>uvicorn support.api:app --reload --port 8000</code>,
              and make sure the store exists via{' '}
              <code>python -m support.data.seed</code>.
            </p>
          </div>
        )}

        {!dryRun && !loadError && (
          <div className="alert warn" style={{ marginBottom: '1.25rem' }}>
            Dry run is off — an approved request will really modify the store
            database.
          </div>
        )}

        {runError && (
          <div className="alert" style={{ marginBottom: '1.25rem' }}>
            <strong>The run failed.</strong>
            <pre>{runError}</pre>
          </div>
        )}

        {result ? (
          <Result result={result} message={ranMessage} />
        ) : (
          !loadError && (
            <div className="empty">
              {running
                ? 'The agent is working through the request…'
                : 'Pick a request on the left, then run the agent.'}
            </div>
          )
        )}
      </main>
    </div>
  )
}
