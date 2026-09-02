import { Link } from 'react-router-dom'
import { apiClient, publicConfig } from '../api/client'
import { useApiResource } from '../api/useApiResource'
import { DataTable } from '../components/DataTable'
import { ArrowRightIcon, ArrowUpRightIcon, InfoIcon } from '../components/Icons'
import { MetricCard } from '../components/MetricCard'
import { PageIntro } from '../components/PageIntro'
import { QualityLatencyChart } from '../components/QualityLatencyChart'
import { StatusPanel } from '../components/StatusPanel'

function signed(value: number) {
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(3)}`
}

export function EvaluationPage() {
  const resource = useApiResource((signal) => apiClient.getEvaluation(undefined, signal), 'evaluation')

  if (resource.status !== 'success') {
    return <div className="page-container status-page"><StatusPanel state={resource} subject="Evaluation report" retry={resource.retry} /></div>
  }

  const report = resource.data
  const validationOnly = report.evaluation_scope === 'validation'
  const fixtureLabel = report.evidence_mode === 'fixture'
    ? 'Illustrative fixture'
    : validationOnly
      ? 'Validation-only evidence'
      : 'Verified result'
  const interval = report.delta?.interval
  const machineReadableUrl = report.report_url
    ?? `${publicConfig.baseUrl}/api/v1/runs/${encodeURIComponent(report.run_id)}`
  const measuredLatencyModels = report.models.filter((model) => model.p95_inference_latency_ms !== null)

  return (
    <div className="page-container evaluation-page">
      <PageIntro
        eyebrow="Evaluation report"
        title={validationOnly ? 'Baseline selection, before the final test.' : 'Aggregate evidence, not a victory lap.'}
        description={validationOnly
          ? 'These values select an unchanged baseline on validation data. They do not establish held-out improvement or authorize a candidate claim.'
          : 'Quality, uncertainty, latency, sample counts, and exclusions are presented together so the release decision can be challenged.'}
        actions={
          <a className="button secondary" href={machineReadableUrl} target="_blank" rel="noreferrer">
            Machine-readable report <ArrowUpRightIcon />
          </a>
        }
        meta={validationOnly
          ? <><span>Validation split only</span><span>Held-out accesses: 0</span><span>Graded relevance</span></>
          : <><span>Paired by query</span><span>Locked held-out split</span><span>Graded relevance</span></>}
      />

      <section className="evaluation-lead" aria-labelledby="primary-result-title">
        <div className="primary-result">
          <p className="eyebrow">{fixtureLabel} · Primary release metric</p>
          <h2 id="primary-result-title">{validationOnly ? 'Selected unchanged baseline' : 'Candidate − strongest unchanged baseline'}</h2>
          <p className="primary-number">{validationOnly ? report.primary_metric.value.toFixed(3) : signed(report.delta!.value)}</p>
          <p className="interval-line">
            {validationOnly
              ? 'No held-out difference or release interval has been computed.'
              : interval
                ? `95% CI [${signed(interval.lower)}, ${signed(interval.upper)}]`
                : 'Confidence interval unavailable'}
          </p>
          <p className="method-note">{validationOnly
            ? 'Highest validation graded nDCG@10 under the frozen selection rule'
            : `${interval?.method ?? 'Interval method not reported'} · ${report.bootstrap_resamples?.toLocaleString() ?? 'No'} resamples`}</p>
        </div>
        <div className="gate-card">
          <span className="gate-index">Release gate</span>
          {report.release_status === 'validation_only' ? (
            <><strong>Not evaluated</strong><p>This baseline bootstrap is operational evidence only. The locked held-out gate remains untouched.</p></>
          ) : report.release_status === 'fixture' ? (
            <><strong>Demonstration only</strong><p>The illustrative lower bound is positive, showing the visual treatment of a passing outcome. No real gate decision is claimed.</p></>
          ) : report.release_status === 'passed' ? (
            <><strong>Passed</strong><p>The candidate is higher and the paired interval excludes zero under the preregistered rule.</p></>
          ) : report.release_status === 'failed' ? (
            <><strong>Not passed</strong><p>The prior model remains promoted. The negative result is preserved in the failure report.</p></>
          ) : (
            <><strong>Pending</strong><p>The held-out evaluation is not yet eligible for a release decision.</p></>
          )}
        </div>
      </section>

      <section className="evaluation-metrics" aria-labelledby="metric-summary-title">
        <header className="section-heading">
          <p className="eyebrow">Metric summary</p>
          <h2 id="metric-summary-title">Same candidates. Different ranking systems.</h2>
        </header>
        <div className="metric-grid compact">
          <MetricCard eyebrow={fixtureLabel} label={validationOnly ? 'Selected baseline nDCG@10' : 'Candidate nDCG@10'} value={report.primary_metric.value.toFixed(3)} note="Graded Exact → Irrelevant" accent />
          {validationOnly ? (
            <MetricCard eyebrow={fixtureLabel} label="Held-out accesses" value="0" note="No held-out performance claim" />
          ) : (
            <MetricCard eyebrow={fixtureLabel} label="Strongest baseline" value={report.strongest_baseline!.value.toFixed(3)} note={report.strongest_baseline!.display_name} />
          )}
          <MetricCard eyebrow={fixtureLabel} label={validationOnly ? 'Validation queries' : 'Evaluation queries'} value={report.evaluation_query_count.toLocaleString()} note={`${report.excluded_query_count} excluded · disclosed below`} />
        </div>
      </section>

      <section className="report-grid">
        <div className="report-table-card">
          <header>
            <p className="eyebrow">Secondary quality</p>
            <h2>Does the direction hold?</h2>
          </header>
          {report.secondary_metrics.length ? (
            <DataTable
              caption="Secondary metric comparison"
              headers={[{ label: 'Metric' }, { label: 'Baseline', align: 'right' }, { label: 'Candidate', align: 'right' }, { label: 'Delta', align: 'right' }]}
              rows={report.secondary_metrics.map((metric) => [
                metric.metric,
                metric.baseline.toFixed(3),
                metric.candidate.toFixed(3),
                <span className={metric.delta >= 0 ? 'delta-positive' : 'delta-negative'}>{signed(metric.delta)}</span>,
              ])}
            />
          ) : <p className="evidence-unavailable">No like-for-like secondary baseline measurements were published.</p>}
        </div>
        <div className="report-table-card">
          <header>
            <p className="eyebrow">System comparison</p>
            <h2>Quality with inference cost</h2>
          </header>
          <DataTable
            caption="Baseline and candidate quality and latency"
            headers={[{ label: 'System' }, { label: 'nDCG@10', align: 'right' }, { label: 'Exact MRR@10', align: 'right' }, { label: 'Inference p95 ms', align: 'right' }]}
            rows={report.models.map((model) => [
              <span className="model-cell"><strong>{model.display_name}</strong><small>{model.kind}</small></span>,
              model.graded_ndcg_at_10.toFixed(3),
              model.exact_mrr_at_10 === null ? '—' : model.exact_mrr_at_10.toFixed(3),
              model.p95_inference_latency_ms === null ? '—' : model.p95_inference_latency_ms.toFixed(1),
            ])}
          />
        </div>
      </section>

      {measuredLatencyModels.length ? (
        <QualityLatencyChart models={measuredLatencyModels} />
      ) : (
        <section className="chart-card evidence-unavailable" aria-label="Quality and latency evidence unavailable">
          <h2>Quality versus inference latency</h2>
          <p>No model has a published inference p95 measurement in this release artifact.</p>
        </section>
      )}

      <section className="evaluation-notes" aria-labelledby="evaluation-notes-title">
        <InfoIcon />
        <div>
          <p className="eyebrow">Evaluation notes</p>
          <h2 id="evaluation-notes-title">Sample and access disclosure</h2>
          <dl>
            <div><dt>{validationOnly ? 'Validation query count' : 'Held-out query count'}</dt><dd>{report.evaluation_query_count.toLocaleString()}</dd></div>
            <div><dt>Excluded queries</dt><dd>{report.excluded_query_count.toLocaleString()}</dd></div>
            <div><dt>Held-out accesses</dt><dd>{report.test_access_count}</dd></div>
            <div><dt>Bootstrap seed</dt><dd>{report.bootstrap_seed ?? 'Not run'}</dd></div>
          </dl>
          <p>{report.exclusion_note}</p>
        </div>
      </section>

      <div className="comparison-next">
        <p>Aggregate gains can conceal specific regressions. The failure report keeps those cases visible.</p>
        <Link className="button secondary" to="/failures">Inspect failures and slices <ArrowRightIcon /></Link>
      </div>
    </div>
  )
}
