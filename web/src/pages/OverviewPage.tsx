import { Link } from 'react-router-dom'
import { apiClient } from '../api/client'
import { useApiResource } from '../api/useApiResource'
import { ArrowRightIcon, ArrowUpRightIcon } from '../components/Icons'
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
        <StatusPanel state={resource} subject="Overview" retry={resource.retry} />
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

  return (
    <div className="page-container overview-page">
      <section className="hero" aria-labelledby="hero-title">
        <div className="hero-copy">
          <p className="eyebrow">Applied ML · Relevance · Reproducible evidence</p>
          <h1 id="hero-title" aria-label="Machine Learning Product Search Ranking Platform">
            Machine Learning<br />Product Search<br /><em>Ranking Platform.</em>
          </h1>
          <p className="hero-sentence">
            {validationOnly
              ? 'An unchanged baseline is deployed for operational verification while the locked held-out evaluation remains untouched.'
              : overview.release_status === 'failed'
                ? `The evaluated reranker did not clear the release gate, so ${overview.promoted_model.display_name} remains active while the negative result stays public.`
                : 'A trained reranker learns which products best match ambiguous shopper queries and shows where it improves or fails against simpler search methods.'}
          </p>
          <div className="hero-actions">
            <Link className="button primary" to={validationOnly ? '/evaluation' : `/compare?q=${overview.default_query.query_id}`}>
              {validationOnly ? 'Inspect validation evidence' : 'Compare a query'} <ArrowRightIcon />
            </Link>
            <Link className="text-link" to="/evaluation">
              Inspect the evidence <ArrowUpRightIcon />
            </Link>
          </div>
        </div>
        <aside className="hero-specimen" aria-label="Model comparison summary">
          <div className="specimen-index">01 / {validationOnly ? 'baseline bootstrap' : 'controlled comparison'}</div>
          {validationOnly ? (
            <div className="system-comparison">
              <div>
                <span>Validation-selected system</span>
                <strong>{overview.promoted_model.display_name}</strong>
                <small>Unchanged baseline · no held-out claim</small>
              </div>
            </div>
          ) : (
            <div className="system-comparison">
              <div>
                <span>Reference</span>
                <strong>{overview.strongest_baseline!.display_name}</strong>
                <small>Weights unchanged</small>
              </div>
              <span className="versus" aria-label="versus">/</span>
              <div>
                <span>Candidate</span>
                <strong>{overview.evaluated_candidate!.display_name}</strong>
                <small>{overview.release_status === 'failed' ? 'Evaluated · not promoted' : 'Training candidate · promoted'}</small>
              </div>
            </div>
          )}
          <div className="specimen-query">
            <span>Selected shopper query</span>
            <blockquote>“{overview.default_query.query}”</blockquote>
            <p>{overview.default_query.descriptor}</p>
          </div>
          <Link to={validationOnly ? '/evaluation' : `/compare?q=${overview.default_query.query_id}`} className="specimen-link">
            {validationOnly ? 'Open selection evidence' : 'Open ranking movement'} <ArrowRightIcon />
          </Link>
        </aside>
      </section>

      {overview.release_status === 'validation_only' ? (
        <section className="release-note fixture" aria-labelledby="release-note-title">
          <p className="eyebrow">Validation-only bootstrap</p>
          <h2 id="release-note-title">No held-out ranking-improvement decision has been made.</h2>
          <p>This deployment verifies the baseline serving path before the one-time final evaluation.</p>
        </section>
      ) : overview.release_status === 'failed' ? (
        <section className="release-note failed" aria-labelledby="release-note-title">
          <p className="eyebrow">Release decision</p>
          <h2 id="release-note-title">The trained candidate did not demonstrate a statistically supported improvement.</h2>
          <p>{overview.promoted_model.display_name} remains the active ranking model.</p>
          <Link className="text-link" to="/failures">Read the failure report <ArrowRightIcon /></Link>
        </section>
      ) : overview.release_status === 'fixture' ? (
        <section className="release-note fixture" aria-labelledby="release-note-title">
          <p className="eyebrow">Demonstration state</p>
          <h2 id="release-note-title">This example shows how a gate-passing release would be presented.</h2>
          <p>No release decision has been made from these illustrative values.</p>
        </section>
      ) : null}

      <section className="evidence-section" aria-labelledby="evidence-title">
        <header className="section-heading split">
          <div>
            <p className="eyebrow">Release evidence</p>
            <h2 id="evidence-title">The result, with its boundaries attached.</h2>
          </div>
          <p>{validationOnly
            ? 'Every displayed quality number comes from versioned validation evidence; no held-out result is implied.'
            : 'Every quality number is tied to the same candidate lists, a locked held-out set, and a versioned run.'}</p>
        </header>
        <div className="metric-grid">
          <MetricCard
            eyebrow={fixtureLabel}
            label={validationOnly ? overview.primary_metric_name : `${overview.primary_metric_name} delta`}
            value={validationOnly ? 'Validation only' : signed(overview.primary_metric_delta!)}
            note={validationOnly ? 'Selected baseline; no held-out difference' : `95% paired interval [${interval}]`}
            accent
          />
          <MetricCard
            eyebrow={fixtureLabel}
            label={validationOnly ? 'Validation queries' : 'Held-out queries'}
            value={overview.evaluation_query_count.toLocaleString()}
            note={validationOnly ? 'Selection evidence only' : 'Query-level evaluation unit'}
          />
          <MetricCard
            eyebrow={fixtureLabel}
            label="Inference p95 latency"
            value={overview.p95_inference_latency_ms === null ? 'Not measured' : `${Math.round(overview.p95_inference_latency_ms)} ms`}
            note={overview.p95_inference_latency_ms === null ? 'No published inference p95 measurement' : `Offline model timing · ${overview.measured_candidate_count} candidates`}
          />
        </div>
      </section>

      <section className="method-strip" aria-labelledby="method-title">
        <header>
          <p className="eyebrow">What the platform proves</p>
          <h2 id="method-title">{validationOnly ? 'A baseline path, checked before held-out access.' : 'One ranking question. Three controlled systems.'}</h2>
        </header>
        {validationOnly ? (
          <ol>
            <li><span>01</span><strong>Validation selection</strong><p>Unchanged systems are compared only on the validation split.</p></li>
            <li><span>02</span><strong>Baseline bundle</strong><p>The selected model and curated query assets are checksum-verified.</p></li>
            <li><span>03</span><strong>Serving smoke test</strong><p>The API path can be exercised without touching the locked test split.</p></li>
            <li><span>04</span><strong>Claims withheld</strong><p>Improvement, intervals, and failure slices wait for final evaluation.</p></li>
          </ol>
        ) : <ol>
          <li><span>01</span><strong>Supplied candidates</strong><p>A known query and its fixed product list enter every system unchanged.</p></li>
          <li><span>02</span><strong>Credible baselines</strong><p>BM25 and an unchanged cross-encoder establish the reference.</p></li>
          <li><span>03</span><strong>Trained candidate</strong><p>A compact cross-encoder learns from graded relevance judgments.</p></li>
          <li><span>04</span><strong>Guarded evidence</strong><p>Paired uncertainty, latency, slices, wins, and losses travel together.</p></li>
        </ol>}
      </section>

      <section className="closing-cta">
        <div>
          <p className="eyebrow">Two-minute review</p>
          <h2>Start with a ranking. End with the evidence trail.</h2>
        </div>
        <Link className="button light" to={validationOnly ? '/evaluation' : `/compare?q=${overview.default_query.query_id}`}>
          {validationOnly ? 'Review the boundary' : 'Begin comparison'} <ArrowRightIcon />
        </Link>
      </section>
    </div>
  )
}
