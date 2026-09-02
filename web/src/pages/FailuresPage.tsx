import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiClient } from '../api/client'
import { useApiResource } from '../api/useApiResource'
import { DataTable } from '../components/DataTable'
import { AlertIcon, ArrowRightIcon } from '../components/Icons'
import { PageIntro } from '../components/PageIntro'
import { StatusPanel } from '../components/StatusPanel'
import type { FailureExample } from '../types/api'

type OutcomeFilter = 'all' | FailureExample['outcome']
type ConfusionFilter = 'all' | FailureExample['confusion_type']

const filterLabels: Array<{ value: OutcomeFilter; label: string }> = [
  { value: 'all', label: 'All examples' },
  { value: 'win', label: 'Wins' },
  { value: 'loss', label: 'Losses' },
  { value: 'tie', label: 'Ties' },
]

const confusionLabels: Record<FailureExample['confusion_type'], string> = {
  exact_vs_substitute: 'Exact vs substitute',
  complement_promotion: 'Complement promoted',
  lexical_ambiguity: 'Lexical ambiguity',
  none: 'No confusion type',
}

function signed(value: number) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}`
}

export function FailuresPage() {
  const resource = useApiResource((signal) => apiClient.getFailures(undefined, signal), 'failures')
  const [outcome, setOutcome] = useState<OutcomeFilter>('all')
  const [confusion, setConfusion] = useState<ConfusionFilter>('all')

  const filteredExamples = useMemo(() => {
    if (resource.status !== 'success') return []
    return resource.data.examples.filter((example) => (
      (outcome === 'all' || example.outcome === outcome)
      && (confusion === 'all' || example.confusion_type === confusion)
    ))
  }, [confusion, outcome, resource])

  if (resource.status !== 'success') {
    return <div className="page-container status-page"><StatusPanel state={resource} subject="Failure analysis" retry={resource.retry} /></div>
  }

  const report = resource.data
  if (report.status === 'not_performed') {
    return (
      <div className="page-container failures-page">
        <PageIntro
          eyebrow="Failure analysis"
          title="Held-out failure analysis has not run."
          description={report.reason ?? 'This baseline bootstrap contains validation-only operational evidence.'}
          meta={<><span>Validation only</span><span>Held-out accesses: 0</span><span>No release claim</span></>}
        />
        <section className="release-note fixture" aria-label="Validation-only boundary">
          <p className="eyebrow">Evidence boundary</p>
          <h2>Losses, slices, and causal interpretations remain unpublished until the held-out evaluation is authorized and completed.</h2>
        </section>
      </div>
    )
  }
  const sortedSlices = [...report.slices].sort(
    (left, right) => (left.delta ?? Number.POSITIVE_INFINITY) - (right.delta ?? Number.POSITIVE_INFINITY),
  )

  return (
    <div className="page-container failures-page">
      <PageIntro
        eyebrow="Failure analysis"
        title="The losses stay in the room."
        description="Aggregate improvement is not permission to hide regressions. Slices and representative examples expose where the candidate is weaker, tied, or uncertain."
        meta={<><span>Predeclared slices</span><span>Wins + losses</span><span>Interpretations labeled</span></>}
      />

      <section className="slice-section" aria-labelledby="slice-title">
        <header className="section-heading split">
          <div>
            <p className="eyebrow">Candidate − baseline</p>
            <h2 id="slice-title">Slice performance, weakest first.</h2>
          </div>
          <p>Rows are sorted by the change in graded nDCG@10. A warning appears below the declared minimum of {report.minimum_slice_size} queries.</p>
        </header>
        <DataTable
          caption="Candidate versus baseline performance by evaluation slice"
          className="slice-table"
          headers={[{ label: 'Slice' }, { label: 'Queries', align: 'right' }, { label: 'Baseline', align: 'right' }, { label: 'Candidate', align: 'right' }, { label: 'Delta', align: 'right' }]}
          rows={sortedSlices.map((slice) => [
            <span className="slice-cell"><strong>{slice.display_name}</strong><small>{slice.description}</small>{slice.low_sample ? <em><AlertIcon /> Low sample</em> : null}</span>,
            slice.query_count.toLocaleString(),
            slice.baseline_ndcg_at_10 === null ? '—' : slice.baseline_ndcg_at_10.toFixed(3),
            slice.candidate_ndcg_at_10 === null ? '—' : slice.candidate_ndcg_at_10.toFixed(3),
            slice.delta === null
              ? '—'
              : <span className={slice.delta > 0 ? 'delta-positive' : slice.delta < 0 ? 'delta-negative' : ''}>{signed(slice.delta)}</span>,
          ])}
        />
        {sortedSlices.some((slice) => slice.low_sample) ? (
          <p className="low-sample-note"><AlertIcon /> Low-sample rows are descriptive and should not drive a release decision alone.</p>
        ) : null}
      </section>

      <section className="examples-section" aria-labelledby="examples-title">
        <header className="section-heading split">
          <div>
            <p className="eyebrow">Representative queries</p>
            <h2 id="examples-title">Inspect what changed.</h2>
          </div>
          <p>Example deltas help explain behavior; they are not aggregate performance claims.</p>
        </header>

        <div className="example-filters" aria-label="Failure example filters">
          <div className="segmented-control" role="group" aria-label="Filter by outcome">
            {filterLabels.map((filter) => (
              <button
                key={filter.value}
                type="button"
                className={outcome === filter.value ? 'active' : undefined}
                aria-pressed={outcome === filter.value}
                onClick={() => setOutcome(filter.value)}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <label className="compact-select">
            <span>Confusion type</span>
            <select value={confusion} onChange={(event) => setConfusion(event.target.value as ConfusionFilter)}>
              <option value="all">All types</option>
              {Object.entries(confusionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
            </select>
          </label>
        </div>

        {filteredExamples.length ? (
          <div className="example-grid" aria-live="polite">
            {filteredExamples.map((example) => (
              <article className={`failure-card ${example.outcome}`} key={example.example_id}>
                <header>
                  <span className={`outcome-label ${example.outcome}`}>{example.outcome}</span>
                  <span className="example-delta">{signed(example.delta)}</span>
                </header>
                <p className="example-type">{confusionLabels[example.confusion_type]}</p>
                <h3>“{example.query.query}”</h3>
                <p className="example-summary">{example.summary}</p>
                <dl>
                  <div>
                    <dt>Interpretation—not established cause</dt>
                    <dd>{example.interpretation}</dd>
                  </div>
                  <div>
                    <dt>Next experiment</dt>
                    <dd>{example.next_experiment}</dd>
                  </div>
                </dl>
                <Link to={`/compare?q=${example.query.query_id}`}>
                  Open ranking <ArrowRightIcon />
                </Link>
              </article>
            ))}
          </div>
        ) : (
          <div className="inline-empty" aria-live="polite">
            <p>No examples match both filters.</p>
            <button type="button" className="text-link" onClick={() => { setOutcome('all'); setConfusion('all') }}>Clear filters</button>
          </div>
        )}
      </section>
    </div>
  )
}
