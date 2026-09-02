export type EvidenceMode = 'fixture' | 'verified' | 'validation_only'

export type RelevanceLabel = 'Exact' | 'Substitute' | 'Complement' | 'Irrelevant'

export type PublicMetricName =
  | 'graded_ndcg@10'
  | 'exact_mrr@10'
  | 'recall_exact_or_substitute@10'
  | 'pairwise_ordinal_accuracy'
  | 'graded_ndcg@5'
  | 'exact_top_1_rate'

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    request_id?: string
  }
}

export interface HealthResponse {
  status: 'ok'
  service_version: string
}

export interface ReadinessResponse {
  status: 'ready'
  model_id: string
  dataset_manifest_hash: string
}

export interface ModelSummary {
  model_id: string
  display_name: string
  kind: 'input_order' | 'seeded_random' | 'bm25' | 'pretrained' | 'fine_tuned' | 'lexical' | 'pretrained_cross_encoder' | 'fine_tuned_cross_encoder'
  base_model_id: string | null
  artifact_checksum: string
  evaluation_report_id: string
  promoted_at: string | null
  limitations_url: string
}

export interface CuratedQuery {
  query_id: string
  query: string
  descriptor: string
  outcome: 'win' | 'loss' | 'tie' | 'unclassified'
  candidate_count: number
}

export interface RankRequest {
  query_id: string
  model_id: string
  top_k: number
}

export interface RankedProduct {
  rank: number
  product_id: string
  title: string
  score: number
  benchmark_label?: RelevanceLabel
}

export interface RankResponse {
  request_id: string
  query_id: string
  query: string
  model_id: string
  model_artifact_checksum: string
  dataset_manifest_hash: string
  candidate_count: number
  top_k: number
  latency_ms: number
  results: RankedProduct[]
}

export interface ComparisonRanking {
  model_id: string
  latency_ms: number
  results: RankedProduct[]
}

export interface ComparisonResponse {
  evidence_mode: EvidenceMode
  query_id: string
  query: string
  candidate_count: number
  baseline: ComparisonRanking
  candidate: ComparisonRanking
}

export interface RankMovement {
  product_id: string
  baseline_rank: number
  candidate_rank: number
  rank_delta: number
}

export interface BenchmarkJudgment {
  product_id: string
  esci_label: RelevanceLabel
  source: 'ground_truth_annotation'
}

export interface CanonicalComparisonResponse {
  request_id: string
  query_id: string
  query: string
  baseline_model_id: string
  candidate_model_id: string
  candidate_count: number
  baseline_latency_ms: number
  candidate_latency_ms: number
  baseline_results: RankedProduct[]
  candidate_results: RankedProduct[]
  rank_movements: RankMovement[]
  benchmark_judgments: BenchmarkJudgment[] | null
}

export interface ConfidenceInterval {
  level: number
  lower: number
  upper: number
  method: string
}

export interface MetricValue {
  metric: string
  display_name: string
  value: number
  interval?: ConfidenceInterval
}

export interface ModelMetricRow {
  model_id: string
  display_name: string
  kind: string
  graded_ndcg_at_10: number
  exact_mrr_at_10: number | null
  recall_exact_or_substitute_at_10: number | null
  pairwise_ordinal_accuracy: number | null
  graded_ndcg_at_5: number | null
  exact_top_1_rate: number | null
  p95_inference_latency_ms: number | null
}

export interface EvaluationData {
  evidence_mode: EvidenceMode
  evaluation_scope: 'fixture' | 'held_out' | 'validation'
  report_id: string
  run_id: string
  release_status: 'passed' | 'failed' | 'pending' | 'fixture' | 'validation_only'
  primary_metric: MetricValue
  strongest_baseline: MetricValue | null
  delta: MetricValue | null
  evaluation_query_count: number
  bootstrap_resamples: number | null
  bootstrap_seed: number | null
  test_access_count: number
  excluded_query_count: number
  exclusion_note: string
  models: ModelMetricRow[]
  secondary_metrics: Array<{
    metric: string
    baseline: number
    candidate: number
    delta: number
  }>
  report_url?: string
}

export interface OverviewData {
  evidence_mode: EvidenceMode
  evaluation_scope: EvaluationData['evaluation_scope']
  release_status: EvaluationData['release_status']
  promoted_model: ModelSummary
  strongest_baseline: ModelSummary | null
  evaluation_query_count: number
  primary_metric_name: string
  primary_metric_delta: number | null
  primary_metric_interval: ConfidenceInterval | null
  p95_inference_latency_ms: number | null
  measured_candidate_count: number
  default_query: CuratedQuery
}

export interface SliceResult {
  slice_id: string
  display_name: string
  description: string
  query_count: number
  baseline_ndcg_at_10: number | null
  candidate_ndcg_at_10: number | null
  delta: number | null
  low_sample: boolean
}

export interface FailureExample {
  example_id: string
  query: CuratedQuery
  outcome: 'win' | 'loss' | 'tie'
  confusion_type: 'exact_vs_substitute' | 'complement_promotion' | 'lexical_ambiguity' | 'none'
  delta: number
  summary: string
  interpretation: string
  next_experiment: string
}

export interface FailureAnalysisData {
  evidence_mode: EvidenceMode
  run_id: string
  status: 'complete' | 'not_performed'
  reason?: string
  slices: SliceResult[]
  examples: FailureExample[]
  minimum_slice_size: number
}

export interface PublicRunSummary {
  evidence_mode: EvidenceMode
  run_id: string
  status: 'complete' | 'failed' | 'pending' | 'fixture' | 'validation_only'
  configuration_hash: string | null
  data_hash: string | null
  split_manifest_hash: string | null
  code_commit: string | null
  image_digest: string | null
  model_artifact_checksum: string | null
  dataset_source: string | null
  dataset_version: string | null
  locale: string | null
  base_model_id: string | null
  base_model_revision: string | null
  training_strategy: string | null
  hardware_class: string | null
  region: string | null
  duration_seconds: number | null
  cost_usd: number | null
  cost_evidence: string
  test_access_count: number
  limitations: string[]
  prohibited_claims: string[]
  reproduction_command: string
}

export interface VerifiedPublicInterval {
  point_estimate: number
  lower: number
  upper: number
  confidence_level: number
}

export interface VerifiedPublicMetricValue {
  metric: PublicMetricName
  display_name: string
  value: number
  interval: VerifiedPublicInterval | null
}

export interface VerifiedPublicModelMetricRow {
  model_id: string
  display_name: string
  kind: 'bm25' | 'pretrained' | 'fine_tuned'
  graded_ndcg_at_10: number
  exact_mrr_at_10: number | null
  recall_exact_or_substitute_at_10: number | null
  pairwise_ordinal_accuracy: number | null
  graded_ndcg_at_5: number | null
  exact_top_1_rate: number | null
  p95_inference_latency_ms: number | null
}

export interface VerifiedPublicEvaluation {
  evidence_mode: 'verified'
  report_id: string
  run_id: string
  candidate_model_id: string
  strongest_baseline_model_id: string
  release_status: 'passed' | 'failed'
  primary_metric: VerifiedPublicMetricValue
  strongest_baseline: VerifiedPublicMetricValue
  delta: VerifiedPublicMetricValue
  held_out_query_count: number
  bootstrap_resamples: number
  bootstrap_seed: number
  test_access_count: number
  excluded_query_count: number
  exclusion_note: string
  models: VerifiedPublicModelMetricRow[]
  secondary_metrics: Array<{
    metric: PublicMetricName
    display_name: string
    baseline: number
    candidate: number
    delta: number
  }>
}

export interface VerifiedPublicSlice {
  slice_id: string
  display_name: string
  description: string
  query_count: number
  excluded_query_count: number
  baseline_graded_ndcg_at_10: number | null
  candidate_graded_ndcg_at_10: number | null
  delta: number | null
  low_sample: boolean
  finding: 'improvement' | 'regression' | 'uncertain' | 'insufficient_data'
}

export interface VerifiedPublicFailureExample {
  example_id: string
  query: Pick<CuratedQuery, 'query_id' | 'query' | 'candidate_count'>
  category: 'win' | 'loss' | 'tie_or_uncertain' | 'lexical_preferred' | 'complement_exact_confusion'
  baseline_metric: number
  candidate_metric: number
  delta: number
  selection_rule: string
  public_product_ids: string[]
  notes: string | null
  interpretation: string | null
  next_experiment: string | null
}

export interface VerifiedPublicFailureAnalysis {
  evidence_mode: 'verified'
  run_id: string
  metric: 'graded_ndcg@10'
  minimum_slice_size: number
  slices: VerifiedPublicSlice[]
  examples: VerifiedPublicFailureExample[]
}

export interface VerifiedPublicRun {
  evidence_mode: 'verified'
  run_id: string
  status: 'complete'
  config_hash: string
  dataset_manifest_hash: string
  git_sha: string
  image_digest: string
  model_artifact_checksum: string
  dataset_name: string
  dataset_version: string
  locale: 'us'
  base_model_id: string
  base_model_revision: string
  training_strategy: string
  hardware_class: string
  region: string
  metrics: {
    candidate_graded_ndcg_at_10: number
    strongest_baseline_graded_ndcg_at_10: number
    candidate_minus_baseline_graded_ndcg_at_10: number
  }
  intervals: {
    candidate_minus_baseline_graded_ndcg_at_10: VerifiedPublicInterval
  }
  duration_seconds: number
  actual_cost_usd: number | null
  cost_evidence: string
  test_access_count: number
  limitations: string[]
  prohibited_claims: string[]
  reproduction_command: string
}

export interface VerifiedPublicEvidenceEnvelope {
  schema_version: '1.0.0'
  evidence_mode: 'verified'
  run: VerifiedPublicRun
  evaluation: VerifiedPublicEvaluation
  failure_analysis: VerifiedPublicFailureAnalysis
}

export interface ValidationPublicRun {
  evidence_mode: 'validation_only'
  run_id: string
  status: 'validation_only'
  selected_model_id: string
  config_hash: string
  dataset_manifest_hash: string
  git_sha: string
  image_digest: string
  model_artifact_checksum: string
  dataset_name: string
  dataset_version: string
  locale: 'us'
  base_model_id: string | null
  hardware_class: string
  region: string
  metrics: { selected_model_graded_ndcg_at_10: number }
  duration_seconds: number
  actual_cost_usd: number | null
  cost_evidence: string
  test_access_count: 0
  held_out_claims_allowed: false
  validation_only_notice: string
  limitations: string[]
  prohibited_claims: string[]
  reproduction_command: string
}

export interface ValidationPublicEvaluation {
  evidence_mode: 'validation_only'
  evidence_id: string
  run_id: string
  status: 'validation_only'
  selected_model_id: string
  primary_metric: VerifiedPublicMetricValue
  validation_query_count: number
  excluded_query_count: number
  test_access_count: 0
  held_out: false
  models: VerifiedPublicModelMetricRow[]
  selection_note: string
}

export interface ValidationPublicFailureAnalysis {
  evidence_mode: 'validation_only'
  run_id: string
  status: 'not_performed'
  reason: string
  slices: []
  examples: []
}

export interface ValidationPublicEvidenceEnvelope {
  schema_version: '1.0.0'
  evidence_mode: 'validation_only'
  run: ValidationPublicRun
  evaluation: ValidationPublicEvaluation
  failure_analysis: ValidationPublicFailureAnalysis
}

export type PublicEvidenceEnvelope = VerifiedPublicEvidenceEnvelope | ValidationPublicEvidenceEnvelope
