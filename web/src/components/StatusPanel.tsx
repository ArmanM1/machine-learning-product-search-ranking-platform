import type { ResourceState } from '../api/useApiResource'
import { AlertIcon, RefreshIcon } from './Icons'

interface StatusPanelProps {
  state: Exclude<ResourceState<unknown>, { status: 'success' }>
  subject: string
  retry?: () => void
}

const copy = {
  loading: {
    title: 'Gathering evidence',
    body: 'Loading the public manifest and its linked artifacts.',
  },
  empty: {
    title: 'Nothing to show yet',
    body: 'No public evidence has been attached to this view.',
  },
  'not-ready': {
    title: 'Model not ready',
    body: 'The model or a required evidence artifact is still loading. Try again shortly.',
  },
  conflict: {
    title: 'Evidence version conflict',
    body: 'The selected artifact does not match the promoted manifest. No mixed-version result was displayed.',
  },
  error: {
    title: 'Evidence unavailable',
    body: 'The request could not be completed. The rest of the interface is still available.',
  },
} as const

export function StatusPanel({ state, subject, retry }: StatusPanelProps) {
  const content = copy[state.status]
  const error = state.status === 'error' || state.status === 'not-ready' || state.status === 'conflict'
    ? state.error
    : null

  return (
    <section className={`status-panel ${state.status}`} aria-live="polite" aria-busy={state.status === 'loading'}>
      <div className="status-symbol" aria-hidden="true">
        {state.status === 'loading' ? <span className="loading-orbit" /> : <AlertIcon />}
      </div>
      <p className="eyebrow">{subject}</p>
      <h1>{content.title}</h1>
      <p>{error?.message ?? content.body}</p>
      {error?.requestId ? <p className="request-id">Request ID: {error.requestId}</p> : null}
      {retry && state.status !== 'loading' && state.status !== 'empty' ? (
        <button className="button secondary" type="button" onClick={retry}>
          <RefreshIcon /> Try again
        </button>
      ) : null}
    </section>
  )
}
