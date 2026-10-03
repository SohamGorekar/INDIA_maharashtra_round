import { useEffect, useState } from 'react'
import { clearToken, getMe, getToken, logout } from './api'
import Chat from './components/Chat'
import Login from './components/Login'
import Orders from './components/Orders'
import DebugApp from './DebugApp'

/**
 * Two surfaces, one app:
 *
 *   /        what a customer sees -- sign in, your orders, ask about one
 *   /debug   the engineer's view -- tool timeline, decision, correct/incorrect
 *
 * A tiny path check rather than a router: there are two routes and neither
 * takes parameters, so a routing library would be more moving parts than the
 * problem has.
 */
export default function App() {
  const isDebug = window.location.pathname.replace(/\/+$/, '') === '/debug'
  return isDebug ? <DebugApp /> : <CustomerApp />
}

function CustomerApp() {
  const [customer, setCustomer] = useState(null)
  const [order, setOrder] = useState(null)   // non-null means we are in a chat
  const [checking, setChecking] = useState(Boolean(getToken()))

  // A token in localStorage survives a refresh, but the server keeps sessions
  // in memory -- so a restarted backend invalidates it. Check before trusting.
  useEffect(() => {
    if (!getToken()) return
    getMe()
      .then(setCustomer)
      .catch(() => clearToken())
      .finally(() => setChecking(false))
  }, [])

  async function signOut() {
    await logout()
    setCustomer(null)
    setOrder(null)
  }

  if (checking) return <div className="empty">Loading…</div>

  if (!customer) return <Login onSignedIn={setCustomer} />

  if (order) {
    return (
      <Chat
        customer={customer}
        order={order}
        onBack={() => setOrder(null)}
        onSignOut={signOut}
      />
    )
  }

  return <Orders customer={customer} onAsk={setOrder} onSignOut={signOut} />
}
