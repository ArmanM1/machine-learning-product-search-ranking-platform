import { useState } from 'react'
import { CheckIcon, CopyIcon } from './Icons'

interface CopyFieldProps {
  value: string | null
  label: string
}

export function CopyField({ value, label }: CopyFieldProps) {
  const [status, setStatus] = useState<'idle' | 'copied' | 'failed'>('idle')

  if (!value) return <span className="not-recorded">Not published</span>

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setStatus('copied')
      window.setTimeout(() => setStatus('idle'), 1600)
    } catch {
      setStatus('failed')
      window.setTimeout(() => setStatus('idle'), 2400)
    }
  }

  return (
    <div className="copy-field">
      <code title={value}>{value}</code>
      <button type="button" onClick={copy} aria-label={`Copy ${label}`} title={`Copy ${label}`}>
        {status === 'copied' ? <CheckIcon /> : <CopyIcon />}
      </button>
      <span className="sr-only" role="status" aria-live="polite">
        {status === 'copied' ? `${label} copied` : status === 'failed' ? `${label} could not be copied` : ''}
      </span>
    </div>
  )
}
