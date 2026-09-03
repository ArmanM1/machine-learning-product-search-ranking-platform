import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { apiClient } from '../src/api/client'
import { fixtureRun } from '../src/api/fixtures'
import { ExperimentPage } from '../src/pages/ExperimentPage'
import type { PublicRunSummary } from '../src/types/api'

const SHA_A = `sha256:${'a'.repeat(64)}`
const SHA_B = `sha256:${'b'.repeat(64)}`

describe('verified experiment provenance', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders selected training and held-out Processing as separate executions', async () => {
    const run: PublicRunSummary = {
      ...fixtureRun,
      evidence_mode: 'verified',
      status: 'complete',
      training_provenance: {
        trial_selection_id: `trial-selection-${'a'.repeat(20)}`,
        trial_selection_sha256: SHA_A,
        run_id: 'training-run-1',
        run_manifest_sha256: SHA_A,
        selected_model_id: 'candidate-v1',
        selected_model_artifact_checksum: SHA_A,
        config_hash: SHA_A,
        git_sha: 'a'.repeat(40),
        image_digest: SHA_A,
        hardware_class: 'ml.g4dn.xlarge',
        accelerator: 'gpu',
        region: 'us-east-1',
        runtime_seconds: 420,
        estimated_cost_usd: 0.8,
        actual_cost_usd: null,
        cost_evidence: 'Training estimate awaiting reconciliation.',
      },
      evaluation_provenance: {
        candidate_model_id: 'candidate-v1',
        candidate_model_artifact_checksum: SHA_A,
        evaluation_config_hash: SHA_B,
        git_sha: 'a'.repeat(40),
        image_digest: SHA_B,
        hardware_class: 'ml.m5.xlarge',
        region: 'us-east-1',
        clean_execution_count: 2,
        runtime_seconds: 180,
        runtime_basis: 'processing_job_wall_clock_sum',
        estimated_cost_usd: 0.2,
        actual_cost_usd: null,
        cost_evidence: 'Two-job Processing estimate awaiting reconciliation.',
      },
    }
    vi.spyOn(apiClient, 'getRun').mockResolvedValue(run)

    render(<MemoryRouter><ExperimentPage /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: 'Model creation' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Independent Processing' })).toBeInTheDocument()
    expect(screen.getByText('ml.g4dn.xlarge')).toBeInTheDocument()
    expect(screen.getByText('ml.m5.xlarge')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy training image digest' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy evaluation image digest' })).toBeInTheDocument()
    expect(screen.getByText(run.split_manifest_hash)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy split manifest hash' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Hardware and boundary' })).not.toBeInTheDocument()
  })
})
