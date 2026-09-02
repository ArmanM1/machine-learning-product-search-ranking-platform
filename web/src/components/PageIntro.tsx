import type { ReactNode } from 'react'

interface PageIntroProps {
  eyebrow: string
  title: string
  description: string
  actions?: ReactNode
  meta?: ReactNode
}

export function PageIntro({ eyebrow, title, description, actions, meta }: PageIntroProps) {
  return (
    <header className="page-intro">
      <div className="page-intro-copy">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="lede">{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
      {meta ? <div className="page-meta">{meta}</div> : null}
    </header>
  )
}
