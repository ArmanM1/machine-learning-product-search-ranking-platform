import { Link } from 'react-router-dom'
import { apiClient } from '../api/client'
import { useApiResource } from '../api/useApiResource'
import { ArrowRightIcon } from '../components/Icons'
import { MetricCard } from '../components/MetricCard'
import { StatusPanel } from '../components/StatusPanel'

function signed(value: number, digits = 3) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(digits)}`
}

export function OverviewPage() {
  const resource = useApiResource((signal) => apiClient.getOverview(signal), 'overview')

  if (resource.status !== 'success') {
    return (
      <div className="page-container status-page">
        <StatusPanel state={resource} subject="Evidence overview" retry={resource.retry} />
      </div>
    )
  }

  const overview = resource.data
  const validationOnly = overview.evaluation_scope === 'validation'
  const interval = overview.primary_metric_interval
    ? `${signed(overview.primary_metric_interval.lower)}, ${signed(overview.primary_metric_interval.upper)}`
    : null
  const fixtureLabel = overview.evidence_mode === 'fixture'
    ? 'Illustrative fixture'
    : validationOnly
      ? 'Validation-only evidence'
      : 'Verified release'
  const operational = overview.operational_evidence
  const operationalVerified = operational.status === 'verified'
  const latencyLabel = overview.evidence_mode === 'fixture'
    ? 'Illustrative offline p95'
    : 'Warm API Gateway/Lambda p95'
  const latencyValue = overview.evidence_mode === 'fixture'
    ? overview.p95_inference_latency_ms === null
      ? 'Not measured'
      : `${Math.round(overview.p95_inference_latency_ms)} ms`
    : operationalVerified
      ? `${Math.round(operational.warm.end_to_end_latency_ms.p95)} ms`
      : operational.status === 'unavailable'
        ? 'Unavailable'
        : 'Publishing'
  const latencyNote = overview.evidence_mode === 'fixture'
    ? `${overview.measured_candidate_count} candidates · no cloud-run claim`
    : operationalVerified
      ? `${operational.warm.candidate_count} candidates · ${operational.warm.successful_request_count}/${operational.warm.measured_request_count} successful · cold excluded`
      : operational.note

  const decision = validationOnly
    ? {
        label: 'Validation-only bootstrap',
        title: 'Held-out decision not run',
        note: 'The selected unchanged baseline is deployed only to verify the serving path.',
      }
    : overview.release_status === 'failed'
      ? {
          label: 'Release decision',
          title: 'Candidate not promoted',
          note: 'The trained candidate did not demonstrate a statistically supported improvement.',
        }
      : overview.release_status === 'fixture'
        ? {
            label: 'Demonstration state',
            title: 'Interface preview only',
            note: 'These values show the evidence contract; they are not measured portfolio claims.',
          }
        : {
            label: 'Release decision',
            title: 'Candidate promoted',
            note: 'The candidate cleared the preregistered held-out gate and is the active release.',
          }

  return (
    <div className="page-container evidence-hub">
      <header className="document-header">
        <div>
          <p className="eyebrow">Current release</p>
          <h1>Evidence</h1>
          <p>Evaluation, serving measurements, failure cases, and run provenance for the active ranking decision.</p>
        </div>
        <span className={`release-state ${overview.release_status}`}>{fixtureLabel}</span>
      </header>

      <section className="decision-panel" aria-labelledby="decision-title">
        <div>
          <p className="eyebrow">{decision.label}</p>
          <h2 id="decision-title">{decision.title}</h2>
          <p>{decision.note}</p>
        </div>
        {overview.release_status === 'failed' ? (
          <Link className="text-link" to="/failures">Read the failure report <ArrowRightIcon /></Link>
        ) : (
          <Link className="text-link" to="/evaluation">Open evaluation <ArrowRightIcon /></Link>
        )}
      </section>

      <section className="evidence-section" aria-labelledby="evidence-title">
        <header className="section-heading split">
          <div>
            <p className="eyebrow">Release snapshot</p>
            <h2 id="evidence-title">The decision and its boundaries</h2>
          </div>
          <p>{validationOnly
            ? 'Quality values are validation-only; no held-out improvement is implied.'
            : 'Every value is tied to the same candidate sets, locked split, and versioned run.'}</p>
        </header>

        <div className="metric-grid">
          <MetricCard
            eyebrow={fixtureLabel}
            label={validationOnly
              ? overview.primary_metric_name
              : overview.release_status === 'failed'
                ? 'Release gate'
                : `${overview.primary_metric_name} delta`}
            value={validationOnly
              ? 'Validation only'
              : overview.release_status === 'failed'
                ? 'Baseline retained'
                : signed(overview.primary_metric_delta!)}
            note={validationOnly
              ? 'Selected baseline; no held-out difference'
              : overview.release_status === 'failed'
                ? 'Held-out delta and interval remain on the Evaluation page'
                : `95% paired interval [${interval}]`}
            accent={overview.release_status !== 'failed'}
          />
          <MetricCard
            eyebrow={fixtureLabel}
            label={validationOnly ? 'Validation queries' : 'Held-out queries'}
            value={overview.evaluation_query_count.toLocaleString()}
            note={validationOnly ? 'Selection evidence only' : 'Query-level evaluation unit'}
          />
          <MetricCard
            eyebrow={overview.evidence_mode === 'fixture'
              ? fixtureLabel
              : operationalVerified
                ? 'Verified deployment'
                : 'Deployment evidence'}
            label={latencyLabel}
            value={latencyValue}
            note={latencyNote}
          />
        </div>

        {overview.evidence_mode !== 'fixture' && operationalVerified ? (
          <details className="operations-detail">
            <summary>Serving measurement protocol</summary>
            <div>
              <p>
                <strong>Warm:</strong> {operational.warm.warmup_request_count} warmups,
                {' '}{operational.warm.measured_request_count} measured requests at concurrency
                {' '}{operational.warm.concurrency}; model p95
                {' '}{Math.round(operational.warm.model_latency_ms.p95)} ms.
              </p>
              <p>
                <strong>Controlled cold start:</strong>
                {' '}{Math.round(operational.controlled_cold_start.end_to_end_latency_ms)} ms
                {' '}end to end from one observation, including
                {' '}{Math.round(operational.controlled_cold_start.init_duration_ms)} ms initialization
                {' '}and {Math.round(operational.controlled_cold_start.model_load_duration_ms)} ms model load.
                It is reported separately and excluded from warm percentiles.
              </p>
            </div>
          </details>
        ) : null}
      </section>

      <section className="evidence-index" aria-labelledby="evidence-index-title">
        <header>
          <p className="eyebrow">Evidence trail</p>
          <h2 id="evidence-index-title">Inspect the record</h2>
        </header>
        <nav aria-label="Evidence record">
          <Link to="/evaluation">
            <span><strong>Evaluation</strong><small>Metrics, paired interval, query count, and latency</small></span>
            <ArrowRightIcon />
          </Link>
          <Link to="/failures">
            <span><strong>Failures</strong><small>Wins, losses, ties, slices, and representative cases</small></span>
            <ArrowRightIcon />
          </Link>
          <Link to="/experiment">
            <span><strong>Run details</strong><small>Immutable configuration, training, evaluation, and cost boundaries</small></span>
            <ArrowRightIcon />
          </Link>
        </nav>
      </section>

      <div className="workspace-return">
        <p>Want to inspect a concrete result?</p>
        <Link className="button secondary" to={`/?q=${overview.default_query.query_id}`}>
          Open ranking workspace <ArrowRightIcon />
        </Link>
      </div>
    </div>
  )
}
