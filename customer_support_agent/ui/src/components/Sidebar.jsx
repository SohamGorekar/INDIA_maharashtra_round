import { useEffect, useState } from 'react'
import { getOrder } from '../api'

/**
 * Request picker: either choose one of the generated samples (which come with a
 * known correct answer) or type a request by hand (which does not).
 */
export default function Sidebar({
  mode,
  setMode,
  samples,
  selectedIndex,
  setSelectedIndex,
  custom,
  setCustom,
  customers,
  dryRun,
  setDryRun,
  onRun,
  running,
  canRun,
  health,
  onClearCache,
}) {
  const sample = mode === 'sample' ? samples[selectedIndex] : null
  const [order, setOrder] = useState(null)

  // Pull the order behind the selected sample so the operator can see the facts
  // the agent is about to reason over.
  useEffect(() => {
    if (!sample?.order_id) {
      setOrder(null)
      return
    }
    let cancelled = false
    getOrder(sample.order_id)
      .then((data) => !cancelled && setOrder(data))
      .catch(() => !cancelled && setOrder(null))
    return () => {
      cancelled = true
    }
  }, [sample?.order_id])

  const patch = (changes) => setCustom({ ...custom, ...changes })

  return (
    <aside className="sidebar">
      <div className="brand">
        <h1>Order Support</h1>
        <p>
          {health ? `${health.model} · store date ${health.today}` : 'connecting…'}
        </p>
      </div>

      <div className="segmented">
        <button
          className={mode === 'sample' ? 'active' : ''}
          onClick={() => setMode('sample')}
        >
          Samples
        </button>
        <button
          className={mode === 'custom' ? 'active' : ''}
          onClick={() => setMode('custom')}
        >
          Write your own
        </button>
      </div>

      {mode === 'sample' ? (
        <>
          <div className="field">
            <label htmlFor="sample">Request</label>
            <select
              id="sample"
              value={selectedIndex}
              onChange={(e) => setSelectedIndex(Number(e.target.value))}
            >
              {samples.map((s, i) => (
                <option key={s.request_id} value={i}>
                  {s.request_id}. [{s.request_type}] {s.message.slice(0, 46)}…
                </option>
              ))}
            </select>
          </div>

          {sample && (
            <div className="card">
              <p className="section-title">Request</p>
              <dl className="kv">
                <dt>Customer</dt>
                <dd>{sample.customer_id}</dd>
                <dt>Order</dt>
                <dd>{sample.order_id}</dd>
                <dt>Type</dt>
                <dd>{sample.request_type}</dd>
                <dt>Reason</dt>
                <dd>{sample.reason.replace('_', ' ')}</dd>
                <dt>Photo</dt>
                <dd>{sample.photo_provided ? 'attached' : 'none'}</dd>
                {sample.requested_size && (
                  <>
                    <dt>Wants size</dt>
                    <dd>{sample.requested_size}</dd>
                  </>
                )}
              </dl>
            </div>
          )}

          {order && (
            <div className="card">
              <p className="section-title">The order</p>
              <dl className="kv">
                <dt>Item</dt>
                <dd>
                  {order.item}
                  {order.size && order.size !== 'ONE' ? ` (${order.size})` : ''}
                </dd>
                <dt>Price</dt>
                <dd>Rs. {order.price.toLocaleString('en-IN')}</dd>
                <dt>Purchased</dt>
                <dd>{order.purchase_date}</dd>
                <dt>Shipped</dt>
                <dd>{order.shipped ? 'yes' : 'no'}</dd>
                <dt>Final sale</dt>
                <dd>{order.final_sale ? 'yes' : 'no'}</dd>
                <dt>Status</dt>
                <dd>{order.status}</dd>
              </dl>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="field">
            <label htmlFor="customer">Customer</label>
            <select
              id="customer"
              value={custom.customer_id}
              onChange={(e) => patch({ customer_id: e.target.value })}
            >
              {customers.map((c) => (
                <option key={c.customer_id} value={c.customer_id}>
                  {c.customer_id} — {c.name}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="message">Customer message</label>
            <textarea
              id="message"
              value={custom.message}
              placeholder="My order ORD-0045 arrived damaged, I'd like a refund…"
              onChange={(e) => patch({ message: e.target.value })}
            />
          </div>

          <div className="field">
            <label htmlFor="type">Request type</label>
            <select
              id="type"
              value={custom.request_type}
              onChange={(e) => patch({ request_type: e.target.value })}
            >
              <option value="refund">refund</option>
              <option value="exchange">exchange</option>
              <option value="cancellation">cancellation</option>
            </select>
          </div>

          {custom.request_type === 'exchange' && (
            <div className="field">
              <label htmlFor="size">Requested size</label>
              <input
                id="size"
                type="text"
                value={custom.requested_size}
                placeholder="M"
                onChange={(e) => patch({ requested_size: e.target.value })}
              />
            </div>
          )}

          <label className="toggle">
            <input
              type="checkbox"
              checked={custom.photo_provided}
              onChange={(e) => patch({ photo_provided: e.target.checked })}
            />
            <span>Customer attached a photo</span>
          </label>
        </>
      )}

      <div className="divider" />

      <label className="toggle" title="When on, the store database is never modified.">
        <input
          type="checkbox"
          checked={dryRun}
          onChange={(e) => setDryRun(e.target.checked)}
        />
        <span>Dry run</span>
      </label>

      <button className="primary" onClick={onRun} disabled={!canRun || running}>
        {running ? (
          <>
            <span className="spinner" /> &nbsp;Working…
          </>
        ) : (
          'Run agent'
        )}
      </button>

      <div className="divider" />

      <div className="row">
        <span className="muted">
          Cache: {health?.cache?.entries ?? 0} responses
        </span>
        <button onClick={onClearCache}>Clear</button>
      </div>
    </aside>
  )
}
