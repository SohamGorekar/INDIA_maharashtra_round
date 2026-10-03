async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try { detail = (await response.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return response.json()
}

export const getHealth = () => request('/api/blackbox/health')
export const listRuns = () => request('/api/blackbox/runs?limit=100')
export const getTrace = (id) => request(`/api/blackbox/runs/${id}/trace`)
export const getEvent = (runId, eventId) =>
  request(`/api/blackbox/runs/${runId}/events/${eventId}`)
export const getCheckpoints = (id) => request(`/api/blackbox/runs/${id}/checkpoints`)
export const diagnose = (id) => request(`/api/blackbox/runs/${id}/diagnosis`)
export const replay = (id, checkpointId, safeMode) =>
  request(`/api/blackbox/runs/${id}/replay`, {
    method: 'POST', body: JSON.stringify({ checkpoint_id: checkpointId, safe_mode: safeMode }),
  })
export const counterfactual = (id, eventId, modification, safeMode) =>
  request(`/api/blackbox/runs/${id}/counterfactual`, {
    method: 'POST',
    body: JSON.stringify({ event_id: eventId, modification, safe_mode: safeMode }),
  })
export const compare = (id, otherId) =>
  request(`/api/blackbox/runs/${id}/compare/${otherId}`)

function stream(url, handlers, closeOnTerminal = false) {
  const source = new EventSource(url)
  const types = ['latest_run', 'run_started', 'event_started', 'event_completed',
    'event_failed', 'checkpoint_created', 'run_completed', 'run_failed', 'heartbeat', 'stream_error']
  const onMessage = (event) => {
    try {
      const message = JSON.parse(event.data)
      handlers.onEvent?.(message)
      if (closeOnTerminal && (message.type === 'run_completed' || message.type === 'run_failed')) {
        source.close()
      }
    }
    catch (error) { handlers.onError?.(error) }
  }
  types.forEach((type) => source.addEventListener(type, onMessage))
  source.onopen = () => handlers.onOpen?.()
  source.onerror = () => handlers.onError?.(new Error('Live connection interrupted.'))
  return () => { types.forEach((type) => source.removeEventListener(type, onMessage)); source.close() }
}
export const streamLatest = (handlers) => stream('/api/blackbox/stream/latest', handlers)
export const streamRun = (id, handlers) => stream(`/api/blackbox/runs/${id}/stream`, handlers, true)
