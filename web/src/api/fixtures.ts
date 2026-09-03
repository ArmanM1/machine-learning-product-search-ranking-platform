import type {
  ComparisonResponse,
  CuratedQuery,
  EvaluationData,
  FailureAnalysisData,
  ModelSummary,
  OverviewData,
  PublicRunSummary,
  RankedProduct,
  RelevanceLabel,
} from '../types/api'

const DATASET_HASH = 'sha256:fixture-data-4d195a87ecfaed37'
const MODEL_HASH = 'sha256:fixture-model-b91c5d7a32ec406e'
const BASELINE_HASH = 'sha256:fixture-bm25-6a032aa1df48ed4b'

export const fixtureModels: ModelSummary[] = [
  {
    model_id: 'bm25-v1',
    display_name: 'BM25 lexical baseline',
    kind: 'lexical',
    base_model_id: null,
    artifact_checksum: BASELINE_HASH,
    evaluation_report_id: 'report-demo-fixture',
    promoted_at: null,
    limitations_url: '/experiment#limitations',
  },
  {
    model_id: 'pretrained-v1',
    display_name: 'Unchanged cross-encoder',
    kind: 'pretrained_cross_encoder',
    base_model_id: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
    artifact_checksum: 'sha256:fixture-pretrained-981a57c1e9f9',
    evaluation_report_id: 'report-demo-fixture',
    promoted_at: null,
    limitations_url: '/experiment#limitations',
  },
  {
    model_id: 'candidate-v1',
    display_name: 'Fine-tuned cross-encoder',
    kind: 'fine_tuned_cross_encoder',
    base_model_id: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
    artifact_checksum: MODEL_HASH,
    evaluation_report_id: 'report-demo-fixture',
    promoted_at: null,
    limitations_url: '/experiment#limitations',
  },
]

export const fixtureQueries: CuratedQuery[] = [
  {
    query_id: 'query-fixture-001',
    query: 'quiet keyboard for office',
    descriptor: 'Intent beyond repeated keywords',
    outcome: 'win',
    candidate_count: 10,
  },
  {
    query_id: 'query-fixture-002',
    query: 'running belt no bounce',
    descriptor: 'Attribute-sensitive match',
    outcome: 'win',
    candidate_count: 10,
  },
  {
    query_id: 'query-fixture-003',
    query: 'apple watch band leather',
    descriptor: 'Accessory versus core-product ambiguity',
    outcome: 'loss',
    candidate_count: 10,
  },
  {
    query_id: 'query-fixture-004',
    query: 'travel mug leak proof',
    descriptor: 'Near-tied product attributes',
    outcome: 'tie',
    candidate_count: 10,
  },
]

type ProductSeed = {
  id: string
  title: string
  label: RelevanceLabel
  baselineScore: number
  candidateScore: number
}

const queryProducts: Record<string, ProductSeed[]> = {
  'query-fixture-001': [
    { id: 'kbd-01', title: 'Low-profile silent wireless keyboard, graphite', label: 'Exact', baselineScore: 13.48, candidateScore: 0.921 },
    { id: 'kbd-02', title: 'Compact keyboard with quiet scissor switches', label: 'Exact', baselineScore: 11.72, candidateScore: 0.887 },
    { id: 'kbd-03', title: 'Mechanical gaming keyboard with blue switches', label: 'Substitute', baselineScore: 14.06, candidateScore: 0.274 },
    { id: 'kbd-04', title: 'Silent tactile keyboard switch sample pack', label: 'Complement', baselineScore: 12.91, candidateScore: 0.119 },
    { id: 'kbd-05', title: 'Full-size quiet USB keyboard for shared spaces', label: 'Exact', baselineScore: 10.83, candidateScore: 0.844 },
    { id: 'kbd-06', title: 'Wireless mouse and keyboard office bundle', label: 'Substitute', baselineScore: 10.95, candidateScore: 0.516 },
    { id: 'kbd-07', title: 'Desk mat with sound dampening felt', label: 'Complement', baselineScore: 9.77, candidateScore: 0.168 },
    { id: 'kbd-08', title: 'Ergonomic split keyboard, low-noise keys', label: 'Exact', baselineScore: 9.21, candidateScore: 0.803 },
    { id: 'kbd-09', title: 'Gaming headset with noise-cancelling microphone', label: 'Irrelevant', baselineScore: 7.35, candidateScore: 0.032 },
    { id: 'kbd-10', title: 'Office keyboard dust cover, clear silicone', label: 'Complement', baselineScore: 9.98, candidateScore: 0.094 },
  ],
  'query-fixture-002': [
    { id: 'run-01', title: 'Slim running waist belt with anti-bounce straps', label: 'Exact', baselineScore: 12.4, candidateScore: 0.938 },
    { id: 'run-02', title: 'Adjustable phone belt for distance running', label: 'Exact', baselineScore: 10.8, candidateScore: 0.871 },
    { id: 'run-03', title: 'Hydration vest with two soft flasks', label: 'Substitute', baselineScore: 11.9, candidateScore: 0.462 },
    { id: 'run-04', title: 'Elastic replacement strap for running belt', label: 'Complement', baselineScore: 11.4, candidateScore: 0.214 },
    { id: 'run-05', title: 'Reflective zipper running pouch, low profile', label: 'Exact', baselineScore: 9.8, candidateScore: 0.816 },
    { id: 'run-06', title: 'Water-resistant hiking hip pack', label: 'Substitute', baselineScore: 9.5, candidateScore: 0.407 },
    { id: 'run-07', title: 'Race bib holders, set of four', label: 'Complement', baselineScore: 8.4, candidateScore: 0.127 },
    { id: 'run-08', title: 'Neoprene running phone armband', label: 'Substitute', baselineScore: 9.1, candidateScore: 0.348 },
    { id: 'run-09', title: 'Leather everyday belt', label: 'Irrelevant', baselineScore: 8.8, candidateScore: 0.021 },
    { id: 'run-10', title: 'Compression running socks', label: 'Complement', baselineScore: 7.6, candidateScore: 0.082 },
  ],
  'query-fixture-003': [
    { id: 'watch-01', title: 'Genuine leather watch band compatible with Apple Watch', label: 'Exact', baselineScore: 14.7, candidateScore: 0.893 },
    { id: 'watch-02', title: 'Apple Watch leather charging stand', label: 'Complement', baselineScore: 13.9, candidateScore: 0.901 },
    { id: 'watch-03', title: 'Slim leather band with stainless buckle', label: 'Exact', baselineScore: 12.8, candidateScore: 0.844 },
    { id: 'watch-04', title: 'Silicone sport band for Apple Watch', label: 'Substitute', baselineScore: 13.1, candidateScore: 0.728 },
    { id: 'watch-05', title: 'Leather loop magnetic watch strap', label: 'Exact', baselineScore: 11.6, candidateScore: 0.809 },
    { id: 'watch-06', title: 'Apple Watch protective case, rose gold', label: 'Complement', baselineScore: 12.1, candidateScore: 0.756 },
    { id: 'watch-07', title: 'Two-pack classic leather wrist straps', label: 'Exact', baselineScore: 10.7, candidateScore: 0.782 },
    { id: 'watch-08', title: 'Smartwatch screen cleaning kit', label: 'Complement', baselineScore: 8.9, candidateScore: 0.342 },
    { id: 'watch-09', title: 'Traditional analog leather watch', label: 'Irrelevant', baselineScore: 9.3, candidateScore: 0.261 },
    { id: 'watch-10', title: 'Metal mesh smartwatch band', label: 'Substitute', baselineScore: 10.1, candidateScore: 0.588 },
  ],
  'query-fixture-004': [
    { id: 'mug-01', title: 'Vacuum insulated leak-proof travel mug, 16 oz', label: 'Exact', baselineScore: 13.5, candidateScore: 0.918 },
    { id: 'mug-02', title: 'Stainless commuter mug with locking lid', label: 'Exact', baselineScore: 12.9, candidateScore: 0.899 },
    { id: 'mug-03', title: 'Replacement sealing lid for travel tumbler', label: 'Complement', baselineScore: 12.1, candidateScore: 0.443 },
    { id: 'mug-04', title: 'Ceramic-lined spill-resistant coffee cup', label: 'Exact', baselineScore: 11.8, candidateScore: 0.864 },
    { id: 'mug-05', title: 'Insulated water bottle with straw lid', label: 'Substitute', baselineScore: 11.1, candidateScore: 0.652 },
    { id: 'mug-06', title: 'Compact leak-proof thermos, 12 oz', label: 'Exact', baselineScore: 10.7, candidateScore: 0.842 },
    { id: 'mug-07', title: 'Cup holder adapter for oversized mugs', label: 'Complement', baselineScore: 9.8, candidateScore: 0.227 },
    { id: 'mug-08', title: 'Double-wall glass desk coffee cup', label: 'Substitute', baselineScore: 9.4, candidateScore: 0.498 },
    { id: 'mug-09', title: 'Silicone reusable drinking straws', label: 'Complement', baselineScore: 7.8, candidateScore: 0.143 },
    { id: 'mug-10', title: 'Porcelain tea set for four', label: 'Irrelevant', baselineScore: 6.9, candidateScore: 0.027 },
  ],
}

const bm25OrderByQuery: Record<string, string[]> = {
  'query-fixture-001': ['kbd-03', 'kbd-01', 'kbd-04', 'kbd-02', 'kbd-06', 'kbd-05', 'kbd-10', 'kbd-07', 'kbd-08', 'kbd-09'],
  'query-fixture-002': ['run-01', 'run-03', 'run-04', 'run-02', 'run-05', 'run-06', 'run-08', 'run-09', 'run-07', 'run-10'],
  'query-fixture-003': ['watch-01', 'watch-02', 'watch-04', 'watch-03', 'watch-06', 'watch-05', 'watch-07', 'watch-10', 'watch-09', 'watch-08'],
  'query-fixture-004': ['mug-01', 'mug-02', 'mug-03', 'mug-04', 'mug-05', 'mug-06', 'mug-07', 'mug-08', 'mug-09', 'mug-10'],
}

const pretrainedRankingByQuery: Record<string, Array<readonly [string, number]>> = {
  'query-fixture-001': [
    ['kbd-01', 0.874], ['kbd-02', 0.842], ['kbd-08', 0.731], ['kbd-05', 0.704], ['kbd-06', 0.466],
    ['kbd-03', 0.311], ['kbd-04', 0.188], ['kbd-07', 0.142], ['kbd-10', 0.091], ['kbd-09', 0.026],
  ],
  'query-fixture-002': [
    ['run-01', 0.891], ['run-02', 0.824], ['run-03', 0.566], ['run-05', 0.541], ['run-06', 0.403],
    ['run-08', 0.337], ['run-04', 0.204], ['run-07', 0.119], ['run-10', 0.076], ['run-09', 0.018],
  ],
  'query-fixture-003': [
    ['watch-01', 0.861], ['watch-03', 0.817], ['watch-02', 0.789], ['watch-05', 0.776], ['watch-07', 0.741],
    ['watch-04', 0.664], ['watch-06', 0.612], ['watch-10', 0.501], ['watch-08', 0.294], ['watch-09', 0.223],
  ],
  'query-fixture-004': [
    ['mug-01', 0.887], ['mug-02', 0.862], ['mug-04', 0.819], ['mug-06', 0.783], ['mug-05', 0.601],
    ['mug-03', 0.421], ['mug-08', 0.408], ['mug-07', 0.193], ['mug-09', 0.121], ['mug-10', 0.024],
  ],
}

const candidateOrderByQuery: Record<string, string[]> = {
  'query-fixture-001': ['kbd-01', 'kbd-02', 'kbd-05', 'kbd-08', 'kbd-06', 'kbd-03', 'kbd-07', 'kbd-04', 'kbd-10', 'kbd-09'],
  'query-fixture-002': ['run-01', 'run-02', 'run-05', 'run-03', 'run-06', 'run-08', 'run-04', 'run-07', 'run-10', 'run-09'],
  'query-fixture-003': ['watch-02', 'watch-01', 'watch-03', 'watch-05', 'watch-07', 'watch-06', 'watch-04', 'watch-10', 'watch-08', 'watch-09'],
  'query-fixture-004': ['mug-01', 'mug-02', 'mug-04', 'mug-06', 'mug-05', 'mug-08', 'mug-03', 'mug-07', 'mug-09', 'mug-10'],
}

type FixtureSystem = 'bm25' | 'pretrained' | 'candidate'

function rankedProducts(queryId: string, system: FixtureSystem): RankedProduct[] {
  const products = queryProducts[queryId] ?? queryProducts['query-fixture-001']
  const byId = new Map(products.map((product) => [product.id, product]))
  const pretrainedRanking = pretrainedRankingByQuery[queryId] ?? pretrainedRankingByQuery['query-fixture-001']
  const order = system === 'bm25'
    ? (bm25OrderByQuery[queryId] ?? bm25OrderByQuery['query-fixture-001'])
    : system === 'pretrained'
      ? pretrainedRanking.map(([id]) => id)
      : (candidateOrderByQuery[queryId] ?? candidateOrderByQuery['query-fixture-001'])
  const pretrainedScores = new Map(pretrainedRanking)

  return order.map((id, index) => {
    const product = byId.get(id) ?? products[0]
    return {
      rank: index + 1,
      product_id: product.id,
      title: product.title,
      score: system === 'bm25'
        ? product.baselineScore
        : system === 'pretrained'
          ? (pretrainedScores.get(id) ?? 0)
          : product.candidateScore,
      benchmark_label: product.label,
    }
  })
}

const baselineFixtureByModelId: Record<string, { system: Exclude<FixtureSystem, 'candidate'>; latencyMs: number }> = {
  'bm25-v1': { system: 'bm25', latencyMs: 18.6 },
  'pretrained-v1': { system: 'pretrained', latencyMs: 394.1 },
}

export function makeFixtureComparison(
  queryId: string,
  baselineModelId = 'bm25-v1',
  candidateModelId = 'candidate-v1',
): ComparisonResponse {
  const query = fixtureQueries.find((item) => item.query_id === queryId) ?? fixtureQueries[0]
  const baselineFixture = baselineFixtureByModelId[baselineModelId]
  if (!baselineFixture) {
    throw new Error(`No illustrative fixture evidence is available for baseline ${baselineModelId}.`)
  }
  return {
    evidence_mode: 'fixture',
    query_id: query.query_id,
    query: query.query,
    candidate_count: query.candidate_count,
    baseline: {
      model_id: baselineModelId,
      latency_ms: baselineFixture.latencyMs,
      results: rankedProducts(query.query_id, baselineFixture.system),
    },
    candidate: {
      model_id: candidateModelId,
      latency_ms: 438.2,
      results: rankedProducts(query.query_id, 'candidate'),
    },
  }
}

export const fixtureEvaluation: EvaluationData = {
  evidence_mode: 'fixture',
  evaluation_scope: 'fixture',
  report_id: 'report-demo-fixture',
  run_id: 'run-demo-fixture',
  release_status: 'fixture',
  primary_metric: { metric: 'graded_ndcg@10', display_name: 'Graded nDCG@10', value: 0.672 },
  strongest_baseline: { metric: 'graded_ndcg@10', display_name: 'Unchanged cross-encoder', value: 0.641 },
  delta: {
    metric: 'graded_ndcg@10',
    display_name: 'Candidate − strongest baseline',
    value: 0.031,
    interval: { level: 0.95, lower: 0.012, upper: 0.049, method: 'paired query bootstrap' },
  },
  evaluation_query_count: 1248,
  bootstrap_resamples: 10000,
  bootstrap_seed: 20260902,
  test_access_count: 1,
  excluded_query_count: 7,
  exclusion_note: 'Illustrative exclusion note: query groups without two valid candidates are omitted.',
  models: [
    { model_id: 'bm25-v1', display_name: 'BM25', kind: 'Lexical baseline', graded_ndcg_at_10: 0.593, exact_mrr_at_10: 0.704, recall_exact_or_substitute_at_10: 0.818, pairwise_ordinal_accuracy: 0.741, graded_ndcg_at_5: 0.572, exact_top_1_rate: 0.646, p95_inference_latency_ms: 18.6 },
    { model_id: 'pretrained-v1', display_name: 'Unchanged cross-encoder', kind: 'Pretrained baseline', graded_ndcg_at_10: 0.641, exact_mrr_at_10: 0.758, recall_exact_or_substitute_at_10: 0.849, pairwise_ordinal_accuracy: 0.782, graded_ndcg_at_5: 0.628, exact_top_1_rate: 0.683, p95_inference_latency_ms: 394.1 },
    { model_id: 'candidate-v1', display_name: 'Fine-tuned cross-encoder', kind: 'Candidate', graded_ndcg_at_10: 0.672, exact_mrr_at_10: 0.779, recall_exact_or_substitute_at_10: 0.861, pairwise_ordinal_accuracy: 0.801, graded_ndcg_at_5: 0.659, exact_top_1_rate: 0.711, p95_inference_latency_ms: 468.2 },
  ],
  secondary_metrics: [
    { metric: 'Exact MRR@10', baseline: 0.758, candidate: 0.779, delta: 0.021 },
    { metric: 'Exact-or-substitute recall@10', baseline: 0.849, candidate: 0.861, delta: 0.012 },
    { metric: 'Exact@1', baseline: 0.683, candidate: 0.711, delta: 0.028 },
  ],
  report_url: '/fixtures/evaluation-report.json',
}

export const fixtureOverview: OverviewData = {
  evidence_mode: 'fixture',
  evaluation_scope: 'fixture',
  release_status: 'fixture',
  promoted_model: fixtureModels[2],
  evaluated_candidate: fixtureModels[2],
  strongest_baseline: fixtureModels[1],
  evaluation_query_count: fixtureEvaluation.evaluation_query_count,
  primary_metric_name: 'Graded nDCG@10',
  primary_metric_delta: fixtureEvaluation.delta!.value,
  primary_metric_interval: fixtureEvaluation.delta!.interval!,
  p95_inference_latency_ms: 468.2,
  measured_candidate_count: 40,
  default_query: fixtureQueries[0],
}

export const fixtureFailures: FailureAnalysisData = {
  evidence_mode: 'fixture',
  run_id: 'run-demo-fixture',
  status: 'complete',
  minimum_slice_size: 50,
  slices: [
    { slice_id: 'accessory-intent', display_name: 'Accessory intent', description: 'Queries seeking an item made for another product.', query_count: 42, baseline_ndcg_at_10: 0.662, candidate_ndcg_at_10: 0.638, delta: -0.024, low_sample: true },
    { slice_id: 'short-brand-query', display_name: 'Short brand queries', description: 'One or two terms containing a brand token.', query_count: 118, baseline_ndcg_at_10: 0.704, candidate_ndcg_at_10: 0.696, delta: -0.008, low_sample: false },
    { slice_id: 'near-duplicate', display_name: 'Near-duplicate candidates', description: 'Candidate lists with highly similar titles.', query_count: 96, baseline_ndcg_at_10: 0.681, candidate_ndcg_at_10: 0.683, delta: 0.002, low_sample: false },
    { slice_id: 'attribute-rich', display_name: 'Attribute-rich queries', description: 'Three or more explicit product attributes.', query_count: 307, baseline_ndcg_at_10: 0.621, candidate_ndcg_at_10: 0.657, delta: 0.036, low_sample: false },
    { slice_id: 'ambiguous-short', display_name: 'Ambiguous short queries', description: 'One to three terms with multiple plausible intents.', query_count: 214, baseline_ndcg_at_10: 0.574, candidate_ndcg_at_10: 0.628, delta: 0.054, low_sample: false },
  ],
  examples: [
    {
      example_id: 'example-001',
      query: fixtureQueries[2],
      outcome: 'loss',
      confusion_type: 'complement_promotion',
      delta: -0.117,
      summary: 'A leather charging stand moves above exact replacement bands.',
      interpretation: 'The enriched product text may overweight compatibility and material terms shared by accessories.',
      next_experiment: 'Add accessory-versus-core-product contrast pairs to training-only difficult examples.',
    },
    {
      example_id: 'example-002',
      query: fixtureQueries[0],
      outcome: 'win',
      confusion_type: 'lexical_ambiguity',
      delta: 0.164,
      summary: 'Quiet office keyboards move above switch packs and loud gaming models.',
      interpretation: 'Joint query-product encoding appears to capture the working-environment constraint.',
      next_experiment: 'Measure whether the gain holds for other experiential attributes such as lightweight and soft.',
    },
    {
      example_id: 'example-003',
      query: fixtureQueries[3],
      outcome: 'tie',
      confusion_type: 'none',
      delta: 0.001,
      summary: 'Both systems place the same two leak-proof mugs first.',
      interpretation: 'Strong lexical alignment leaves limited room for the candidate to improve.',
      next_experiment: 'No targeted change; retain as a stability check.',
    },
    {
      example_id: 'example-004',
      query: fixtureQueries[1],
      outcome: 'win',
      confusion_type: 'exact_vs_substitute',
      delta: 0.091,
      summary: 'Anti-bounce waist belts move above hydration vests and replacement straps.',
      interpretation: 'The candidate distinguishes the requested product form from plausible substitutes.',
      next_experiment: 'Test robustness when product form is implied rather than explicitly stated.',
    },
  ],
}

export const fixtureRun: PublicRunSummary = {
  evidence_mode: 'fixture',
  run_id: 'run-demo-fixture',
  status: 'fixture',
  configuration_hash: 'sha256:fixture-config-1f94fcd16f4c87c5',
  data_hash: DATASET_HASH,
  split_manifest_hash: `sha256:${'7'.repeat(64)}`,
  code_commit: 'fixture-commit-not-a-real-sha',
  image_digest: 'sha256:fixture-image-04c87fb58d5aead2',
  model_artifact_checksum: MODEL_HASH,
  dataset_source: 'Amazon Shopping Queries ESCI — Query-Product Ranking task',
  dataset_version: 'Illustrative small-version configuration',
  locale: 'us',
  base_model_id: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
  base_model_revision: 'Revision to be pinned before a real training run',
  training_strategy: 'Illustrative mixed difficult + seeded-random examples',
  hardware_class: null,
  region: 'us-east-1 (planned)',
  duration_seconds: null,
  cost_usd: null,
  cost_evidence: 'No cloud run has been recorded in fixture mode.',
  training_provenance: null,
  evaluation_provenance: null,
  test_access_count: 0,
  limitations: [
    'The platform reranks supplied query-specific candidates; it does not retrieve from a full catalog.',
    'The first release is limited to curated US English examples.',
    'Fixture values demonstrate the interface and are not evaluation or cloud-execution evidence.',
    'Model scores are relative ranking scores, not calibrated probabilities.',
  ],
  prohibited_claims: [
    'No claim of measured ranking improvement until the held-out release gate passes.',
    'No claim of production traffic, shopper impact, or conversion lift.',
    'No claim of AWS training or serving until the named workloads complete.',
    'No claim of Amazon affiliation or an official competition score.',
  ],
  reproduction_command: 'make reproduce RUN_ID=<verified-run-id>',
}
