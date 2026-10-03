import { useEffect, useRef, useState } from 'react'
import { endChat, sendChat } from '../api'

const rupees = (n) =>
  `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

function Message({ from, text, photo }) {
  return (
    <div className={`msg ${from}`}>
      <div className="msg-inner">
        {photo && (
          <div className="attachment">
            <span className="attachment-icon">▣</span>
            <span>damage-photo.jpg</span>
          </div>
        )}
        {text && <p>{text}</p>}
      </div>
    </div>
  )
}

function Typing() {
  return (
    <div className="msg agent">
      <div className="msg-inner typing">
        <span />
        <span />
        <span />
      </div>
    </div>
  )
}

/** A support conversation about one specific order. */
export default function Chat({ customer, order, onBack, onSignOut }) {
  const greeting =
    `Hi ${customer.name.split(' ')[0]}, I can help with your ${order.item}. ` +
    `What has gone wrong with it?`

  const [messages, setMessages] = useState([{ from: 'agent', text: greeting }])
  const [draft, setDraft] = useState('')
  const [photoReady, setPhotoReady] = useState(false)
  const [sessionId, setSessionId] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const endRef = useRef(null)
  const inputRef = useRef(null)

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  async function send() {
    const text = draft.trim()
    if ((!text && !photoReady) || sending) return

    setMessages((m) => [...m, { from: 'customer', text, photo: photoReady }])
    setDraft('')
    const hadPhoto = photoReady
    setPhotoReady(false)
    setSending(true)
    setError('')

    try {
      const response = await sendChat({
        session_id: sessionId,
        order_id: order.order_id,
        message: text,
        photo_attached: hadPhoto,
      })
      setSessionId(response.session_id)
      setMessages((m) => [...m, { from: 'agent', text: response.reply }])
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  function onKeyDown(e) {
    // Enter sends, Shift+Enter makes a new line -- what people expect in chat.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  async function leave() {
    if (sessionId) await endChat(sessionId).catch(() => {})
    onBack()
  }

  return (
    <div className="chat-page">
      <header className="site-header">
        <div className="chat-brand">
          <button className="back" onClick={leave} title="Back to your orders">
            ‹
          </button>
          <div>
            <h1>{order.item}</h1>
            <p>
              {order.order_id} · {rupees(order.price)}
              {order.size && order.size !== 'ONE' ? ` · size ${order.size}` : ''}
            </p>
          </div>
        </div>

        <div className="chat-header-right">
          <span className="muted">{customer.name}</span>
          <button className="ghost" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <div className="chat-scroll">
        <div className="chat-thread">
          {messages.map((m, i) => (
            <Message key={i} {...m} />
          ))}
          {sending && <Typing />}
          {error && <div className="chat-error">{error}</div>}
          <div ref={endRef} />
        </div>
      </div>

      <div className="composer-wrap">
        <div className="composer">
          {photoReady && (
            <div className="pending-photo">
              <span className="attachment-icon">▣</span>
              damage-photo.jpg
              <button
                className="remove"
                onClick={() => setPhotoReady(false)}
                title="Remove"
              >
                ×
              </button>
            </div>
          )}

          <div className="composer-row">
            <button
              className={`attach${photoReady ? ' on' : ''}`}
              onClick={() => setPhotoReady(true)}
              disabled={photoReady || sending}
              title="Attach a photo"
            >
              ✚
            </button>

            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              placeholder="Tell us what happened…"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={sending}
            />

            <button
              className="send"
              onClick={send}
              disabled={(!draft.trim() && !photoReady) || sending}
              title="Send"
            >
              ➤
            </button>
          </div>
        </div>
        <p className="composer-hint">Enter to send · Shift + Enter for a new line</p>
      </div>
    </div>
  )
}
