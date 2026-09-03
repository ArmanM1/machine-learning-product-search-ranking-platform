import { buildComparisonPath, buildOverviewData } from '../src/api/client'
import type { CuratedQuery, EvaluationData, ModelSummary } from '../src/types/api'

describe('API client contract', () => {
  it('sends the benchmark-judgment toggle as an explicit request parameter', () => {
    expect(buildComparisonPath('query / one', 'bm25-v1', 'candidate-v1', false)).toBe(
      '/api/v1/comparisons/query%20%2F%20one?baseline=bm25-v1&candidate=candidate-v1&include_judgments=false',
    )
    expect(buildComparisonPath('query-1', 'bm25-v1', 'candidate-v1', true)).toContain(
      'include_judgments=true',
    )
  })

  it.each([
    ['verified', {
      evidence_mode: 'verified',
      run_id: 'verified-run',
      status: 'complete',
      config_hash: 'sha256:config',
      dataset_manifest_hash: 'sha256:dataset',
      split_manifest_hash: `sha256:${'a'.repeat(64)}`,
      git_sha: 'a'.repeat(40),
      model_artifact_checksum: 'sha256:model',
      dataset_name: 'dataset',
      dataset_version: 'v1',
      locale: 'us',
      base_model_id: 'base',
      base_model_revision: 'revision',
      training_strategy: 'strategy',
      training_provenance: {},
      evaluation_provenance: {},
      test_access_count: 2,
      limitations: [],
      prohibited_claims: [],
      reproduction_command: 'reproduce',
    }],
    ['validation_only', {
      evidence_mode: 'validation_only',
      run_id: 'validation-run',
      status: 'validation_only',
      selected_model_id: 'baseline',
      config_hash: 'sha256:config',
      dataset_manifest_hash: 'sha256:dataset',
      split_manifest_hash: `sha256:${'b'.repeat(64)}`,
      git_sha: 'b'.repeat(40),
      image_digest: 'sha256:image',
      model_artifact_checksum: 'sha256:model',
      dataset_name: 'dataset',
      dataset_version: 'v1',
      locale: 'us',
      base_model_id: null,
      hardware_class: 'local-cpu',
      region: 'us-east-1',
      duration_seconds: 1,
      actual_cost_usd: null,
      cost_evidence: 'not billed',
      validation_only_notice: 'validation only',
      limitations: [],
      prohibited_claims: [],
      reproduction_command: 'reproduce',
    }],
  ] as const)('preserves the %s split identity when projecting API evidence', async (mode, run) => {
    vi.resetModules()
    vi.stubEnv('VITE_DATA_MODE', 'api')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ evidence_mode: mode, run }),
    }))
    const { apiClient: apiModeClient } = await import('../src/api/client')

    const projected = await apiModeClient.getRun(run.run_id)

    expect(projected.split_manifest_hash).toBe(run.split_manifest_hash)
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
  })
})

describe('negative release overview', () => {
  it('shows the evaluated failure while keeping the baseline active', () => {
    const model = (
      model_id: string,
      kind: ModelSummary['kind'],
      promoted: boolean,
    ): ModelSummary => ({
      model_id,
      display_name: model_id,
      kind,
      base_model_id: null,
      artifact_checksum: `sha256:${model_id}`,
      evaluation_report_id: 'report-1',
      promoted_at: promoted ? '2026-09-02T00:00:00Z' : null,
      limitations_url: '/limitations',
    })
    const models = [model('baseline-v1', 'pretrained', true), model('candidate-v1', 'fine_tuned', false)]
    const queries: CuratedQuery[] = [{
      query_id: 'q1', query: 'travel mug', descriptor: 'test', outcome: 'loss', candidate_count: 40,
    }]
    const evaluation = {
      evidence_mode: 'verified', evaluation_scope: 'held_out', report_id: 'report-1', run_id: 'run-1',
      release_status: 'failed', primary_metric: { metric: 'graded_ndcg@10', display_name: 'nDCG', value: 0.6 },
      strongest_baseline: { metric: 'graded_ndcg@10', display_name: 'Baseline', value: 0.61 },
      delta: { metric: 'graded_ndcg@10', display_name: 'Delta', value: -0.01, interval: { level: 0.95, lower: -0.02, upper: 0.001, method: 'paired' } },
      evaluation_query_count: 100, bootstrap_resamples: 10000, bootstrap_seed: 7,
      test_access_count: 2, excluded_query_count: 0, exclusion_note: 'None',
      models: [
        { model_id: 'baseline-v1', display_name: 'Baseline', kind: 'pretrained', graded_ndcg_at_10: 0.61, exact_mrr_at_10: null, recall_exact_or_substitute_at_10: null, pairwise_ordinal_accuracy: null, graded_ndcg_at_5: null, exact_top_1_rate: null, p95_inference_latency_ms: 10 },
        { model_id: 'candidate-v1', display_name: 'Candidate', kind: 'fine_tuned', graded_ndcg_at_10: 0.6, exact_mrr_at_10: null, recall_exact_or_substitute_at_10: null, pairwise_ordinal_accuracy: null, graded_ndcg_at_5: null, exact_top_1_rate: null, p95_inference_latency_ms: 12 },
      ],
      secondary_metrics: [],
    } satisfies EvaluationData

    const overview = buildOverviewData(models, queries, evaluation, {
      candidateId: 'candidate-v1', baselineId: 'baseline-v1', queryId: 'q1',
    })

    expect(overview.release_status).toBe('failed')
    expect(overview.promoted_model.model_id).toBe('baseline-v1')
    expect(overview.evaluated_candidate?.model_id).toBe('candidate-v1')
  })
})
