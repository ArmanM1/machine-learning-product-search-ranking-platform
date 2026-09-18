import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { apiClient } from '../src/api/client'
import { fixtureModels, fixtureOverview } from '../src/api/fixtures'
import { OverviewPage } from '../src/pages/OverviewPage'
import type { OverviewData } from '../src/types/api'

vi.mock('../src/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/client')>()
  return {
    ...actual,
    apiClient: {
      ...actual.apiClient,
      getOverview: vi.fn(),
    },
  }
})

function failedOverview(): OverviewData {
  return {
    ...fixtureOverview,
    evidence_mode: 'verified',
    evaluation_scope: 'held_out',
    release_status: 'failed',
    promoted_model: fixtureModels[1],
    evaluated_candidate: fixtureModels[2],
    strongest_baseline: fixtureModels[1],
    primary_metric_delta: -0.01,
    primary_metric_interval: {
      level: 0.95,
      lower: -0.02,
      upper: 0.001,
      method: 'paired query bootstrap',
    },
    operational_evidence: {
      schema_version: '1.0.0',
      status: 'verified',
      release_id: 'release-verified',
      model_id: fixtureModels[1].model_id,
      code_commit: 'a'.repeat(40),
      serving_image_digest: `sha256:${'b'.repeat(64)}`,
      warm: {
        scope: 'deployed_api_gateway_lambda_gate',
        candidate_count: 40,
        warmup_request_count: 10,
        measured_request_count: 200,
        successful_request_count: 200,
        failure_count: 0,
        concurrency: 1,
        end_to_end_latency_ms: { p50: 105, p95: 240, p99: 300 },
        model_latency_ms: { p50: 20, p95: 45, p99: 60 },
        lambda_memory_mb: 4096,
        architecture: 'x86_64',
        region: 'us-east-1',
        reserved_concurrency: 2,
        provisioned_concurrency: 0,
        controlled_cold_sample_included: false,
      },
      controlled_cold_start: {
        measurement_class: 'controlled_on_demand_lambda_cold_start',
        sample_count: 1,
        candidate_count: 40,
        end_to_end_latency_ms: 950,
        init_duration_ms: 700,
        model_load_duration_ms: 600,
        excluded_from_warm_latency: true,
      },
    },
  }
}

describe('overview claim boundaries', () => {
  it('withholds delta and confidence interval when the release gate fails', async () => {
    vi.mocked(apiClient.getOverview).mockResolvedValue(failedOverview())
    render(<MemoryRouter><OverviewPage /></MemoryRouter>)

    expect(await screen.findByText('Baseline retained')).toBeInTheDocument()
    expect(screen.queryByText('−0.010')).not.toBeInTheDocument()
    expect(screen.queryByText(/95% paired interval/i)).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /read the failure report/i })).toHaveAttribute(
      'href',
      '/failures',
    )
  })

  it('shows the deployed warm protocol instead of presenting offline timing as serving latency', async () => {
    vi.mocked(apiClient.getOverview).mockResolvedValue(failedOverview())
    render(<MemoryRouter><OverviewPage /></MemoryRouter>)

    expect(await screen.findByText('Warm API Gateway/Lambda p95')).toBeInTheDocument()
    expect(screen.getByText('240 ms')).toBeInTheDocument()
    expect(
      screen.getByText('40 candidates · 200/200 successful · cold excluded'),
    ).toBeInTheDocument()
    expect(screen.getByText('Serving measurement protocol')).toBeInTheDocument()
    expect(screen.getByText(/Controlled cold start:/)).toBeInTheDocument()
    expect(screen.getByText(/950 ms end to end from one observation/)).toBeInTheDocument()
    expect(screen.queryByText(/offline model timing/i)).not.toBeInTheDocument()
  })

  it.each([
    ['pending', 'Publishing', 'Deployment evidence is publishing.'],
    ['unavailable', 'Unavailable', 'Deployment evidence is temporarily unavailable.'],
  ] as const)('keeps the overview usable while operations evidence is %s', async (
    status,
    value,
    note,
  ) => {
    const overview = failedOverview()
    overview.operational_evidence = status === 'pending'
      ? {
          schema_version: '1.0.0',
          status,
          release_id: 'release-verified',
          model_id: fixtureModels[1].model_id,
          note,
        }
      : {
          schema_version: '1.0.0',
          status,
          release_id: 'unavailable',
          model_id: fixtureModels[1].model_id,
          note,
        }
    vi.mocked(apiClient.getOverview).mockResolvedValue(overview)
    render(<MemoryRouter><OverviewPage /></MemoryRouter>)

    expect(await screen.findByText('Baseline retained')).toBeInTheDocument()
    expect(screen.getByText(value)).toBeInTheDocument()
    expect(screen.getByText(note)).toBeInTheDocument()
    expect(screen.queryByText('Serving measurement protocol')).not.toBeInTheDocument()
  })

  it('retains the explicit illustrative boundary in fixture mode', async () => {
    vi.mocked(apiClient.getOverview).mockResolvedValue(fixtureOverview)
    render(<MemoryRouter><OverviewPage /></MemoryRouter>)

    expect(await screen.findByText('Illustrative offline p95')).toBeInTheDocument()
    expect(screen.getByText(/no cloud-run claim/i)).toBeInTheDocument()
  })
})
