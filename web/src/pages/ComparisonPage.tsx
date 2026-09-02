import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiClient, publicConfig } from '../api/client'
import { useApiResource } from '../api/useApiResource'
import { ArrowRightIcon } from '../components/Icons'
import { PageIntro } from '../components/PageIntro'
import { JudgmentLegend, ProductRanking } from '../components/ProductRanking'
import { QueryPicker } from '../components/QueryPicker'
import { StatusPanel } from '../components/StatusPanel'

export function ComparisonPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedQueryId = searchParams.get('q') ?? publicConfig.queryId
  const [baselineId, setBaselineId] = useState(publicConfig.baselineId)
  const [candidateId, setCandidateId] = useState(publicConfig.candidateId)
  const [showJudgments, setShowJudgments] = useState(true)

  const queries = useApiResource((signal) => apiClient.getQueries('', signal), 'queries')
  const models = useApiResource((signal) => apiClient.getModels(signal), 'models')
  const comparison = useApiResource(
    (signal) => apiClient.getComparison(
      selectedQueryId,
      baselineId,
      candidateId,
      showJudgments,
      signal,
    ),
    `comparison:${selectedQueryId}:${baselineId}:${candidateId}:judgments-${showJudgments}`,
  )

  const modelNames = useMemo(() => {
    if (models.status !== 'success') return new Map<string, string>()
    return new Map(models.data.map((model) => [model.model_id, model.display_name]))
  }, [models])

  const isFineTuned = (kind: string) => kind === 'fine_tuned' || kind === 'fine_tuned_cross_encoder'
  const baselineOnly = models.status === 'success' && !models.data.some((model) => isFineTuned(model.kind))
  const candidateOptions = models.status === 'success'
    ? (models.data.some((model) => isFineTuned(model.kind))
        ? models.data.filter((model) => isFineTuned(model.kind))
        : models.data)
    : []

  const chooseQuery = (queryId: string) => {
    const next = new URLSearchParams(searchParams)
    next.set('q', queryId)
    next.delete('state')
    setSearchParams(next)
  }

  return (
    <div className="page-container comparison-page">
      <PageIntro
        eyebrow="Query comparison"
        title={baselineOnly ? 'Inspect the validation-selected baseline.' : 'See what moved—and why it matters.'}
        description={baselineOnly
          ? 'This bootstrap release exposes an unchanged model for serving verification. It does not contain a trained candidate or held-out comparison.'
          : 'Both systems receive the same curated products. Rank movement is model output; optional relevance badges are separate benchmark annotations.'}
        meta={baselineOnly
          ? <><span>Validation only</span><span>Held-out accesses: 0</span><span>Scores ≠ probabilities</span></>
          : <><span>Curated examples</span><span>Top 10 shown</span><span>Scores ≠ probabilities</span></>}
      />

      {queries.status === 'success' ? (
        <QueryPicker queries={queries.data} selectedId={selectedQueryId} onSelect={chooseQuery} />
      ) : (
        <StatusPanel state={queries} subject="Curated query index" retry={queries.retry} />
      )}

      <section className="comparison-controls" aria-label="Comparison controls">
        <label>
          <span>Reference system</span>
          <select value={baselineId} onChange={(event) => setBaselineId(event.target.value)} disabled={models.status !== 'success'}>
            {models.status === 'success' ? models.data.filter((model) => !isFineTuned(model.kind)).map((model) => (
              <option value={model.model_id} key={model.model_id}>{model.display_name}</option>
            )) : <option>Loading systems…</option>}
          </select>
        </label>
        <span className="control-versus" aria-hidden="true">versus</span>
        <label>
          <span>{baselineOnly ? 'Selected system' : 'Candidate system'}</span>
          <select value={candidateId} onChange={(event) => setCandidateId(event.target.value)} disabled={models.status !== 'success'}>
            {models.status === 'success' ? candidateOptions.map((model) => (
              <option value={model.model_id} key={model.model_id}>{model.display_name}</option>
            )) : <option>Loading systems…</option>}
          </select>
        </label>
        <label className="switch-control">
          <input type="checkbox" checked={showJudgments} onChange={(event) => setShowJudgments(event.target.checked)} />
          <span>Show benchmark labels</span>
        </label>
      </section>

      {comparison.status === 'success' ? (
        <>
          <section className="comparison-summary" aria-label="Selected comparison summary">
            <div>
              <p className="eyebrow">Selected query</p>
              <h2>“{comparison.data.query}”</h2>
            </div>
            <dl>
              <div><dt>Candidates</dt><dd>{comparison.data.candidate_count}</dd></div>
              <div><dt>Reference</dt><dd>{comparison.data.baseline.latency_ms.toFixed(1)} ms</dd></div>
              <div><dt>Candidate</dt><dd>{comparison.data.candidate.latency_ms.toFixed(1)} ms</dd></div>
            </dl>
          </section>
          <div className="rankings-grid">
            <ProductRanking
              response={comparison.data.baseline}
              title={modelNames.get(comparison.data.baseline.model_id) ?? 'Reference ranking'}
              subtitle="Unchanged reference"
              showJudgments={showJudgments}
            />
            <ProductRanking
              response={comparison.data.candidate}
              comparison={comparison.data.baseline}
              title={modelNames.get(comparison.data.candidate.model_id) ?? 'Candidate ranking'}
              subtitle={baselineOnly ? 'Unchanged validation baseline' : 'Trained candidate'}
              showJudgments={showJudgments}
              showMovement
            />
          </div>
          <div className="comparison-next">
            <p>{baselineOnly
              ? 'This ranking confirms the selected baseline can serve a curated candidate set; it is not held-out quality evidence.'
              : 'One curated example is context—not proof. Inspect the aggregate report before drawing a conclusion.'}</p>
            <Link className="button secondary" to="/evaluation">{baselineOnly ? 'View validation boundary' : 'View aggregate evidence'} <ArrowRightIcon /></Link>
          </div>
        </>
      ) : (
        <StatusPanel state={comparison} subject="Ranking comparison" retry={comparison.retry} />
      )}
      <JudgmentLegend />
    </div>
  )
}
