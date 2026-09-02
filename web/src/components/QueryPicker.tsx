import { useDeferredValue, useId, useMemo, useState } from 'react'
import type { CuratedQuery } from '../types/api'
import { SearchIcon } from './Icons'

interface QueryPickerProps {
  queries: CuratedQuery[]
  selectedId: string
  onSelect: (queryId: string) => void
}

export function QueryPicker({ queries, selectedId, onSelect }: QueryPickerProps) {
  const [search, setSearch] = useState('')
  const deferredSearch = useDeferredValue(search)
  const resultsId = useId()
  const filtered = useMemo(() => {
    const normalized = deferredSearch.trim().toLocaleLowerCase()
    if (!normalized) return queries
    return queries.filter((query) => (
      query.query.toLocaleLowerCase().includes(normalized)
      || query.descriptor.toLocaleLowerCase().includes(normalized)
    ))
  }, [deferredSearch, queries])

  return (
    <section className="query-picker" aria-labelledby={`${resultsId}-label`}>
      <div className="query-picker-heading">
        <div>
          <p className="eyebrow">Curated query</p>
          <h2 id={`${resultsId}-label`}>Choose a shopper intent</h2>
        </div>
        <label className="search-field">
          <span className="sr-only">Search curated queries</span>
          <SearchIcon />
          <input
            type="search"
            value={search}
            placeholder="Search examples"
            onChange={(event) => setSearch(event.target.value)}
            aria-controls={resultsId}
          />
        </label>
      </div>
      <div className="query-options" id={resultsId} aria-live="polite">
        {filtered.length ? filtered.map((query) => (
          <button
            className={`query-option${selectedId === query.query_id ? ' selected' : ''}`}
            key={query.query_id}
            type="button"
            onClick={() => onSelect(query.query_id)}
            aria-pressed={selectedId === query.query_id}
          >
            <span className={`outcome-dot ${query.outcome}`} aria-hidden="true" />
            <span>
              <strong>{query.query}</strong>
              <small>{query.descriptor}</small>
            </span>
          </button>
        )) : (
          <p className="query-empty">No curated query matches “{search}”.</p>
        )}
      </div>
    </section>
  )
}
