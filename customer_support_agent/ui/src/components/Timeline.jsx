import { useState } from 'react'
import { TOOL_LABEL, stepHeadline } from '../labels'

function Step({ index, entry }) {
  const [open, setOpen] = useState(false)
  const { tool, args, result } = entry
  const headline = stepHeadline(tool, result)
  const isError = Boolean(result && typeof result === 'object' && result.error)

  return (
    <div className="step">
      <button className="step-head" onClick={() => setOpen(!open)}>
        <span className="step-num">{index}</span>
        <span>
          <span className="step-title">{TOOL_LABEL[tool] ?? tool}</span>
          <br />
          <span className="step-tool">{tool}</span>
        </span>
        {headline && (
          <span className={`step-headline${isError ? ' error' : ''}`}>
            {headline}
          </span>
        )}
      </button>

      {open && (
        <div className="step-body">
          <h4>Arguments</h4>
          <pre>{JSON.stringify(args, null, 2)}</pre>
          <h4>Returned</h4>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </div>
  )
}

/**
 * The sequence of tool calls the agent made. This is the part that shows the
 * reasoning rather than just the verdict -- which order it checked things in,
 * and what each lookup returned.
 */
export default function Timeline({ toolLog }) {
  if (!toolLog?.length) {
    return <p className="muted">The agent made no tool calls.</p>
  }

  return (
    <div>
      {toolLog.map((entry, i) => (
        <Step key={i} index={i + 1} entry={entry} />
      ))}
    </div>
  )
}
