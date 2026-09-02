import {
  fixtureEvaluation,
  fixtureFailures,
  fixtureModels,
  fixtureOverview,
  fixtureQueries,
  fixtureRun,
  makeFixtureComparison,
} from './fixtures'
import type {
  ApiErrorBody,
  CanonicalComparisonResponse,
  ComparisonResponse,
  CuratedQuery,
  EvaluationData,
  FailureAnalysisData,
  ModelSummary,
  OverviewData,
  PublicEvidenceEnvelope,
  PublicRunSummary,
} from '../types/api'

const config = {
  mode: import.meta.env.VITE_DATA_MODE ?? 'fixture',
  baseUrl: (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, ''),
  runId: import.meta.env.VITE_PUBLIC_RUN_ID ?? 'run-demo-fixture',
  queryId: import.meta.env.VITE_DEFAULT_QUERY_ID ?? 'query-fixture-001',
  baselineId: import.meta.env.VITE_BASELINE_MODEL_ID ?? 'bm25-v1',
  candidateId: import.meta.env.VITE_CANDIDATE_MODEL_ID ?? 'candidate-v1',
} as const

export const publicConfig = config
export const isFixtureMode = config.mode !== 'api'

export class ApiClientError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId?: string

  constructor(message: string, status: number, code = 'api_error', requestId?: string) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

function waitForFixture(signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(resolve, 80)
    signal?.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer)
        reject(new DOMException('The request was cancelled.', 'AbortError'))
      },
      { once: true },
    )
  })
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${config.baseUrl}${path}`, {
      headers: { Accept: 'application/json' },
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiClientError('The evidence service could not be reached.', 0, 'network_error')
  }

  if (!response.ok) {
    let body: ApiErrorBody | undefined
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      body = undefined
    }
    const flatBody = body as unknown as { message?: string; code?: string; request_id?: string }
    throw new ApiClientError(
      body?.error?.message ?? flatBody.message ?? `The evidence service returned HTTP ${response.status}.`,
      response.status,
      body?.error?.code ?? flatBody.code ?? 'http_error',
      body?.error?.request_id ?? flatBody.request_id,
    )
  }

  return (await response.json()) as T
}

function unwrapList<T>(value: T[] | { items?: T[]; models?: T[]; queries?: T[] }): T[] {
  if (Array.isArray(value)) return value
  return value.items ?? value.models ?? value.queries ?? []
}

async function getRunEnvelope(runId: string, signal?: AbortSignal): Promise<PublicEvidenceEnvelope> {
  return getJson<PublicEvidenceEnvelope>(`/api/v1/runs/${encodeURIComponent(runId)}`, signal)
}

export function buildComparisonPath(
  queryId: string,
  baselineId: string,
  candidateId: string,
  includeJudgments: boolean,
): string {
  const params = new URLSearchParams({
    baseline: baselineId,
    candidate: candidateId,
    include_judgments: String(includeJudgments),
  })
  return `/api/v1/comparisons/${encodeURIComponent(queryId)}?${params.toString()}`
}

export const apiClient = {
  async getModels(signal?: AbortSignal): Promise<ModelSummary[]> {
    if (isFixtureMode) {
      await waitForFixture(signal)
      return fixtureModels
    }
    const value = await getJson<ModelSummary[] | { models: ModelSummary[] }>('/api/v1/models', signal)
    return unwrapList(value)
  },

  async getQueries(search = '', signal?: AbortSignal): Promise<CuratedQuery[]> {
    if (isFixtureMode) {
      await waitForFixture(signal)
      const normalized = search.trim().toLocaleLowerCase()
      return normalized
        ? fixtureQueries.filter((item) => item.query.toLocaleLowerCase().includes(normalized))
        : fixtureQueries
    }
    const params = new URLSearchParams({ limit: '40' })
    if (search.trim()) params.set('search', search.trim())
    const value = await getJson<Array<Partial<CuratedQuery> & { display_text?: string }> | { queries: Array<Partial<CuratedQuery> & { display_text?: string }> }>(
      `/api/v1/queries?${params.toString()}`,
      signal,
    )
    return unwrapList(value).flatMap((item) => {
      const queryId = item.query_id
      const query = item.query ?? item.display_text
      if (!queryId || !query) return []
      const outcome = item.outcome === 'win' || item.outcome === 'loss' || item.outcome === 'tie'
        ? item.outcome
        : 'unclassified'
      return [{
        query_id: queryId,
        query,
        descriptor: item.descriptor ?? 'Curated benchmark query',
        outcome,
        candidate_count: item.candidate_count ?? 40,
      }]
    })
  },

  async getComparison(
    queryId: string,
    baselineId: string,
    candidateId: string,
    includeJudgments = true,
    signal?: AbortSignal,
  ): Promise<ComparisonResponse> {
    if (isFixtureMode) {
      await waitForFixture(signal)
      if (!fixtureQueries.some((item) => item.query_id === queryId)) {
        throw new ApiClientError('This curated query does not exist.', 404, 'query_not_found')
      }
      return makeFixtureComparison(queryId, baselineId, candidateId)
    }
    const value = await getJson<CanonicalComparisonResponse>(
      buildComparisonPath(queryId, baselineId, candidateId, includeJudgments),
      signal,
    )
    const judgments = new Map(value.benchmark_judgments?.map((item) => [item.product_id, item.esci_label]) ?? [])
    return {
      evidence_mode: 'verified',
      query_id: value.query_id,
      query: value.query,
      candidate_count: value.candidate_count,
      baseline: {
        model_id: value.baseline_model_id,
        latency_ms: value.baseline_latency_ms,
        results: value.baseline_results.map((product) => ({ ...product, benchmark_label: judgments.get(product.product_id) })),
      },
      candidate: {
        model_id: value.candidate_model_id,
        latency_ms: value.candidate_latency_ms,
        results: value.candidate_results.map((product) => ({ ...product, benchmark_label: judgments.get(product.product_id) })),
      },
    }
  },

  async getEvaluation(runId = config.runId, signal?: AbortSignal): Promise<EvaluationData> {
    if (isFixtureMode) {
      await waitForFixture(signal)
      return fixtureEvaluation
    }
    const run = await getRunEnvelope(runId, signal)
    if (run.evidence_mode === 'validation_only') {
      return {
        evidence_mode: 'validation_only',
        evaluation_scope: 'validation',
        report_id: run.evaluation.evidence_id,
        run_id: run.evaluation.run_id,
        release_status: 'validation_only',
        primary_metric: {
          metric: run.evaluation.primary_metric.metric,
          display_name: run.evaluation.primary_metric.display_name,
          value: run.evaluation.primary_metric.value,
        },
        strongest_baseline: null,
        delta: null,
        evaluation_query_count: run.evaluation.validation_query_count,
        bootstrap_resamples: null,
        bootstrap_seed: null,
        test_access_count: 0,
        excluded_query_count: run.evaluation.excluded_query_count,
        exclusion_note: run.evaluation.selection_note,
        models: run.evaluation.models,
        secondary_metrics: [],
      }
    }
    const evaluation = run.evaluation
    const toInterval = (interval: NonNullable<typeof evaluation.delta.interval>) => ({
      level: interval.confidence_level,
      lower: interval.lower,
      upper: interval.upper,
      method: 'paired nonparametric percentile bootstrap',
    })
    return {
      evidence_mode: 'verified',
      evaluation_scope: 'held_out',
      report_id: evaluation.report_id,
      run_id: evaluation.run_id,
      release_status: evaluation.release_status,
      primary_metric: {
        metric: evaluation.primary_metric.metric,
        display_name: evaluation.primary_metric.display_name,
        value: evaluation.primary_metric.value,
      },
      strongest_baseline: {
        metric: evaluation.strongest_baseline.metric,
        display_name: evaluation.strongest_baseline.display_name,
        value: evaluation.strongest_baseline.value,
      },
      delta: {
        metric: evaluation.delta.metric,
        display_name: evaluation.delta.display_name,
        value: evaluation.delta.value,
        interval: evaluation.delta.interval ? toInterval(evaluation.delta.interval) : undefined,
      },
      evaluation_query_count: evaluation.held_out_query_count,
      bootstrap_resamples: evaluation.bootstrap_resamples,
      bootstrap_seed: evaluation.bootstrap_seed,
      test_access_count: evaluation.test_access_count,
      excluded_query_count: evaluation.excluded_query_count,
      exclusion_note: evaluation.exclusion_note,
      models: evaluation.models,
      secondary_metrics: evaluation.secondary_metrics.map((metric) => ({
        metric: metric.display_name,
        baseline: metric.baseline,
        candidate: metric.candidate,
        delta: metric.delta,
      })),
    }
  },

  async getFailures(runId = config.runId, signal?: AbortSignal): Promise<FailureAnalysisData> {
    if (isFixtureMode) {
      await waitForFixture(signal)
      return fixtureFailures
    }
    const run = await getRunEnvelope(runId, signal)
    if (run.evidence_mode === 'validation_only') {
      return {
        evidence_mode: 'validation_only',
        run_id: run.failure_analysis.run_id,
        status: 'not_performed',
        reason: run.failure_analysis.reason,
        minimum_slice_size: 1,
        slices: [],
        examples: [],
      }
    }
    return {
      evidence_mode: 'verified',
      run_id: run.failure_analysis.run_id,
      status: 'complete',
      minimum_slice_size: run.failure_analysis.minimum_slice_size,
      slices: run.failure_analysis.slices.map((slice) => ({
        slice_id: slice.slice_id,
        display_name: slice.display_name,
        description: slice.description,
        query_count: slice.query_count,
        baseline_ndcg_at_10: slice.baseline_graded_ndcg_at_10,
        candidate_ndcg_at_10: slice.candidate_graded_ndcg_at_10,
        delta: slice.delta,
        low_sample: slice.low_sample,
      })),
      examples: run.failure_analysis.examples.map((example) => {
        const outcome = example.delta > 0 ? 'win' : example.delta < 0 ? 'loss' : 'tie'
        const confusionType = example.category === 'complement_exact_confusion'
          ? 'complement_promotion'
          : example.category === 'lexical_preferred'
            ? 'lexical_ambiguity'
            : 'none'
        return {
          example_id: example.example_id,
          query: {
            ...example.query,
            descriptor: example.selection_rule,
            outcome,
          },
          outcome,
          confusion_type: confusionType,
          delta: example.delta,
          summary: example.notes ?? example.selection_rule,
          interpretation: example.interpretation ?? 'No causal interpretation was established for this selected example.',
          next_experiment: example.next_experiment ?? 'Review this query family in a training-only follow-up before changing the release.',
        }
      }),
    }
  },

  async getRun(runId = config.runId, signal?: AbortSignal): Promise<PublicRunSummary> {
    if (isFixtureMode) {
      await waitForFixture(signal)
      if (runId !== fixtureRun.run_id) {
        throw new ApiClientError('This experiment run does not exist.', 404, 'run_not_found')
      }
      return fixtureRun
    }
    const envelope = await getRunEnvelope(runId, signal)
    if (envelope.evidence_mode === 'validation_only') {
      const run = envelope.run
      return {
        evidence_mode: 'validation_only',
        run_id: run.run_id,
        status: 'validation_only',
        configuration_hash: run.config_hash,
        data_hash: run.dataset_manifest_hash,
        split_manifest_hash: null,
        code_commit: run.git_sha,
        image_digest: run.image_digest,
        model_artifact_checksum: run.model_artifact_checksum,
        dataset_source: run.dataset_name,
        dataset_version: run.dataset_version,
        locale: run.locale,
        base_model_id: run.base_model_id,
        base_model_revision: null,
        training_strategy: null,
        hardware_class: run.hardware_class,
        region: run.region,
        duration_seconds: run.duration_seconds,
        cost_usd: run.actual_cost_usd,
        cost_evidence: run.cost_evidence,
        test_access_count: 0,
        limitations: [run.validation_only_notice, ...run.limitations],
        prohibited_claims: run.prohibited_claims,
        reproduction_command: run.reproduction_command,
      }
    }
    const run = envelope.run
    return {
      evidence_mode: 'verified',
      run_id: run.run_id,
      status: 'complete',
      configuration_hash: run.config_hash,
      data_hash: run.dataset_manifest_hash,
      split_manifest_hash: null,
      code_commit: run.git_sha,
      image_digest: run.image_digest,
      model_artifact_checksum: run.model_artifact_checksum,
      dataset_source: run.dataset_name,
      dataset_version: run.dataset_version,
      locale: run.locale,
      base_model_id: run.base_model_id,
      base_model_revision: run.base_model_revision,
      training_strategy: run.training_strategy,
      hardware_class: run.hardware_class,
      region: run.region,
      duration_seconds: run.duration_seconds,
      cost_usd: run.actual_cost_usd,
      cost_evidence: run.cost_evidence,
      test_access_count: run.test_access_count,
      limitations: run.limitations,
      prohibited_claims: run.prohibited_claims,
      reproduction_command: run.reproduction_command,
    }
  },

  async getOverview(signal?: AbortSignal): Promise<OverviewData> {
    if (isFixtureMode) {
      await waitForFixture(signal)
      return fixtureOverview
    }

    const [models, queries, evaluation] = await Promise.all([
      apiClient.getModels(signal),
      apiClient.getQueries('', signal),
      apiClient.getEvaluation(config.runId, signal),
    ])
    const promotedModel = models.find((model) => model.model_id === config.candidateId)
    const strongestBaseline = models.find((model) => model.model_id === config.baselineId)
    const defaultQuery = queries.find((query) => query.query_id === config.queryId) ?? queries[0]
    if (!promotedModel || !defaultQuery) {
      throw new ApiClientError('The public release manifest is incomplete.', 409, 'manifest_not_ready')
    }
    const candidateMetrics = evaluation.models.find((model) => model.model_id === promotedModel.model_id)
    if (evaluation.release_status === 'validation_only') {
      return {
        evidence_mode: 'validation_only',
        evaluation_scope: 'validation',
        release_status: 'validation_only',
        promoted_model: promotedModel,
        strongest_baseline: null,
        evaluation_query_count: evaluation.evaluation_query_count,
        primary_metric_name: evaluation.primary_metric.display_name,
        primary_metric_delta: null,
        primary_metric_interval: null,
        p95_inference_latency_ms: candidateMetrics?.p95_inference_latency_ms ?? null,
        measured_candidate_count: defaultQuery.candidate_count,
        default_query: defaultQuery,
      }
    }
    if (!strongestBaseline || !evaluation.delta?.interval) {
      throw new ApiClientError('The verified release evidence is incomplete.', 409, 'evidence_not_ready')
    }
    return {
      evidence_mode: 'verified',
      evaluation_scope: 'held_out',
      release_status: evaluation.release_status,
      promoted_model: promotedModel,
      strongest_baseline: strongestBaseline,
      evaluation_query_count: evaluation.evaluation_query_count,
      primary_metric_name: evaluation.primary_metric.display_name,
      primary_metric_delta: evaluation.delta.value,
      primary_metric_interval: evaluation.delta.interval,
      p95_inference_latency_ms: candidateMetrics?.p95_inference_latency_ms ?? null,
      measured_candidate_count: defaultQuery.candidate_count,
      default_query: defaultQuery,
    }
  },
}
