import { useState } from 'react'
import { CheckIcon, CopyIcon } from './Icons'

interface CopyFieldProps {
  value: string | null
  label: string
}

export function CopyField({ value, label }: CopyFieldProps) {
  const [copied, setCopied] = useState(false)

  if (!value) return <span className="not-recorded">Not published</span>

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="copy-field">
      <code title={value}>{value}</code>
      <button type="button" onClick={copy} aria-label={`Copy ${label}`} title={`Copy ${label}`}>
        {copied ? <CheckIcon /> : <CopyIcon />}
      </button>
    </div>
  )
}
