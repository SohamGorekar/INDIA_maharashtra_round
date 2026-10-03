// Every call to the FastAPI backend lives here, so the rest of the UI never
// deals with fetch plumbing, auth headers, or error shapes.

const TOKEN_KEY = 'durva.token'

export const getToken = () => localStorage.getItem(TOKEN_KEY) || ''
export const setToken = (token) => localStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

/** Thrown when the server says the session is no longer valid. */
export class NotSignedIn extends Error {}

async function request(path, options = {}) {
  const token = getToken()
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })

  if (!response.ok) {
    // FastAPI puts its error text in `detail`; fall back to the status line.
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body.detail) detail = body.detail
    } catch {
      // No JSON body -- keep the status line.
    }
    if (response.status === 401) {
      clearToken()
      throw new NotSignedIn(detail)
    }
    throw new Error(detail)
  }

  return response.json()
}

// --- auth ------------------------------------------------------------------

export async function login(email, password) {
  const result = await request('/api/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  setToken(result.token)
  return result.customer
}

export async function logout() {
  await request('/api/logout', { method: 'POST' }).catch(() => {})
  clearToken()
}

export const getMe = () => request('/api/me')

// --- orders ----------------------------------------------------------------

export const getOrders = () => request('/api/orders')
export const getOrder = (orderId) => request(`/api/orders/${orderId}`)

// --- chat ------------------------------------------------------------------

export const sendChat = (payload) =>
  request('/api/chat', { method: 'POST', body: JSON.stringify(payload) })

export const endChat = (sessionId) =>
  request(`/api/chat/${sessionId}`, { method: 'DELETE' })
