import { DECISION_LABEL } from '../labels'
import Timeline from './Timeline'

/** The agent's answer, whether it was right, and how it got there. */
export default function Result({ result, message }) {
  const { decision, reply, tool_log: toolLog, steps, dry_run: dryRun } = result
  const expected = result.expected_decision
  const correct = result.correct

  return (
    <div className="stack">
      <div>
        <p className="section-title">Customer</p>
        <div className="bubble customer">
          <div className="who">Incoming message</div>
          {message}
        </div>
      </div>

      <div>
        <p className="section-title">Decision</p>
        <span className={`badge ${decision || 'NONE'}`}>
          {decision ? DECISION_LABEL[decision] ?? decision : 'No reply sent'}
          {decision && <span className="code">{decision}</span>}
        </span>
      </div>

      {!decision && (
        <div className="alert">
          The agent finished without calling <code>send_reply</code>, so the
          conversation was never closed.
        </div>
      )}

      {reply && (
        <div className="bubble agent">
          <div className="who">Reply to the customer</div>
          {reply}
        </div>
      )}

      {/* Only sample requests have a known-correct answer to grade against. */}
      {expected && (
        <div className={`verdict ${correct ? 'ok' : 'bad'}`}>
          {correct ? (
            <>
              <strong>Correct.</strong> Store policy requires{' '}
              <strong>{expected}</strong>.
            </>
          ) : (
            <>
              <strong>Incorrect.</strong> Store policy requires{' '}
              <strong>{expected}</strong>, but the agent answered{' '}
              <strong>{decision || 'nothing'}</strong>.
            </>
          )}
        </div>
      )}

      <div>
        <p className="section-title">How it got there</p>
        <Timeline toolLog={toolLog} />
      </div>

      <p className="muted">
        {steps} model turns · {toolLog?.length ?? 0} tool calls ·{' '}
        {dryRun ? 'dry run, store unchanged' : 'live, store modified'}
      </p>
    </div>
  )
}
