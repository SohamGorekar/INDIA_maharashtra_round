import { useEffect, useState } from 'react'
import { getOrders } from '../api'

const rupees = (n) =>
  `₹${Number(n).toLocaleString('en-IN', { minimumFractionDigits: 2,
                                          maximumFractionDigits: 2 })}`

const prettyDate = (iso) => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * Each order shows only what the store actually records for it. Nothing is
 * invented to fill space -- no fake delivery dates, tracking numbers or
 * ratings, because none of that exists in the data.
 */
function OrderCard({ order, onAsk }) {
  const delivered = order.status === 'active' && order.shipped
  const statusLabel =
    order.status !== 'active'
      ? order.status           // refunded / exchanged / cancelled
      : order.shipped
        ? 'Delivered'
        : 'Processing'

  return (
    <article className="order-card">
      <div className="order-main">
        <div className="order-title-row">
          <h3>{order.item}</h3>
          <span className={`pill ${delivered ? 'ok' : 'muted'}`}>{statusLabel}</span>
        </div>

        <div className="order-meta">
          <span>{order.order_id}</span>
          {order.size && order.size !== 'ONE' && <span>Size {order.size}</span>}
          <span>Ordered {prettyDate(order.purchase_date)}</span>
          {order.method && <span>Paid by {order.method.replace('_', ' ')}</span>}
          {order.final_sale && <span className="final">Final sale</span>}
        </div>
      </div>

      <div className="order-side">
        <div className="order-price">{rupees(order.price)}</div>
        <button onClick={() => onAsk(order)}>Get help</button>
      </div>
    </article>
  )
}

export default function Orders({ customer, onAsk, onSignOut }) {
  const [orders, setOrders] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getOrders()
      .then(setOrders)
      .catch((err) => setError(err.message))
  }, [])

  return (
    <div className="orders-page">
      <header className="site-header">
        <div className="chat-brand">
          <div className="logo">D</div>
          <div>
            <h1>Durva Shopping</h1>
            <p>Your orders</p>
          </div>
        </div>

        <div className="chat-header-right">
          <span className="muted">{customer.name}</span>
          <button className="ghost" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <main className="orders-main">
        {error && <div className="alert">{error}</div>}

        {orders === null && !error && <p className="muted">Loading your orders…</p>}

        {orders?.length === 0 && (
          <p className="muted">You have not placed any orders yet.</p>
        )}

        {orders?.length > 0 && (
          <>
            <p className="orders-hint">
              Something wrong with an order? Choose <strong>Get help</strong> and
              tell us what happened.
            </p>
            <div className="order-list">
              {orders.map((order) => (
                <OrderCard key={order.order_id} order={order} onAsk={onAsk} />
              ))}
            </div>
          </>
        )}
      </main>
    </div>
  )
}
