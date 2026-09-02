import type { ReactNode } from 'react'

interface MetricCardProps {
  label: string
  value: string
  note: string
  eyebrow?: string
  accent?: boolean
  children?: ReactNode
}

export function MetricCard({ label, value, note, eyebrow, accent = false, children }: MetricCardProps) {
  return (
    <article className={`metric-card${accent ? ' accent' : ''}`}>
      {eyebrow ? <p className="metric-eyebrow">{eyebrow}</p> : null}
      <h2 className="metric-label">{label}</h2>
      <p className="metric-value">{value}</p>
      <p className="metric-note">{note}</p>
      {children}
    </article>
  )
}
