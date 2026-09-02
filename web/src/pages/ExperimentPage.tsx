import { useParams } from 'react-router-dom'
import { apiClient, publicConfig } from '../api/client'
import { useApiResource } from '../api/useApiResource'
import { CopyField } from '../components/CopyField'
import { InfoIcon } from '../components/Icons'
import { PageIntro } from '../components/PageIntro'
import { StatusPanel } from '../components/StatusPanel'

function humanDuration(seconds: number | null) {
  if (seconds === null) return 'Not recorded'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`
}

export function ExperimentPage() {
  const { runId = publicConfig.runId } = useParams()
  const resource = useApiResource((signal) => apiClient.getRun(runId, signal), `run:${runId}`)

  if (resource.status !== 'success') {
    return <div className="page-container status-page"><StatusPanel state={resource} subject={resource.status === 'error' && resource.error.status === 404 ? '404 · Experiment' : 'Experiment details'} retry={resource.retry} /></div>
  }

  const run = resource.data
  const modeLabel = run.evidence_mode === 'fixture'
    ? 'Illustrative fixture · no executed run'
    : run.evidence_mode === 'validation_only'
      ? 'Validation-only baseline run · held-out untouched'
      : 'Verified public run'

  return (
    <div className="page-container experiment-page">
      <PageIntro
        eyebrow="Experiment details"
        title="Follow the result back to its source."
        description={run.evidence_mode === 'validation_only'
          ? 'Immutable identifiers connect this validation-only baseline evidence to data, configuration, code, image, hardware, and model artifacts.'
          : 'Immutable identifiers connect the public decision to data, configuration, code, image, hardware, and model artifacts.'}
        meta={<><span>{modeLabel}</span><span>Run {run.run_id}</span><span>US English</span></>}
      />

      <section className="provenance-section" aria-labelledby="provenance-title">
        <header className="section-heading split">
          <div>
            <p className="eyebrow">Provenance</p>
            <h2 id="provenance-title">Immutable chain of evidence.</h2>
          </div>
          <p>Checksums are displayed in full so a reviewer can compare the interface with the machine-readable manifest.</p>
        </header>
        <dl className="provenance-list">
          <div><dt>Dataset hash</dt><dd><CopyField label="dataset hash" value={run.data_hash} /></dd></div>
          <div><dt>Split manifest</dt><dd><CopyField label="split manifest hash" value={run.split_manifest_hash} /></dd></div>
          <div><dt>Training configuration</dt><dd><CopyField label="configuration hash" value={run.configuration_hash} /></dd></div>
          <div><dt>Code commit</dt><dd><CopyField label="code commit" value={run.code_commit} /></dd></div>
          <div><dt>Container image</dt><dd><CopyField label="image digest" value={run.image_digest} /></dd></div>
          <div><dt>Model artifact</dt><dd><CopyField label="model artifact checksum" value={run.model_artifact_checksum} /></dd></div>
        </dl>
      </section>

      <section className="experiment-grid" aria-label="Experiment configuration and execution evidence">
        <article className="detail-card">
          <p className="eyebrow">Data</p>
          <h2>Source and split</h2>
          <dl>
            <div><dt>Dataset</dt><dd>{run.dataset_source ?? 'Not published'}</dd></div>
            <div><dt>Version</dt><dd>{run.dataset_version ?? 'Not published'}</dd></div>
            <div><dt>Locale</dt><dd>{run.locale ?? 'Not published'}</dd></div>
            <div><dt>Held-out accesses</dt><dd>{run.test_access_count}</dd></div>
          </dl>
        </article>
        <article className="detail-card">
          <p className="eyebrow">Model</p>
          <h2>Exact starting point</h2>
          <dl>
            <div><dt>Base model</dt><dd>{run.base_model_id ?? 'Not published'}</dd></div>
            <div><dt>Revision</dt><dd>{run.base_model_revision ?? 'Not published'}</dd></div>
            <div><dt>Training strategy</dt><dd>{run.training_strategy ?? 'Not published'}</dd></div>
          </dl>
        </article>
        <article className="detail-card">
          <p className="eyebrow">Execution</p>
          <h2>Hardware and boundary</h2>
          <dl>
            <div><dt>Hardware</dt><dd>{run.hardware_class ?? 'Not recorded'}</dd></div>
            <div><dt>Region</dt><dd>{run.region ?? 'Not recorded'}</dd></div>
            <div><dt>Duration</dt><dd>{humanDuration(run.duration_seconds)}</dd></div>
            <div><dt>Cost</dt><dd>{run.cost_usd == null ? 'Not recorded' : `$${run.cost_usd.toFixed(2)} USD`}</dd></div>
          </dl>
          <p className="cost-note"><InfoIcon /> {run.cost_evidence}</p>
        </article>
      </section>

      <section className="reproduction-card" aria-labelledby="reproduction-title">
        <div>
          <p className="eyebrow">Clean-checkout entry point</p>
          <h2 id="reproduction-title">Reproduce the selected run.</h2>
          <p>{run.evidence_mode === 'validation_only'
            ? 'The published command recreates the validation-only baseline path without authorizing held-out access.'
            : 'The exact verified command resolves the versioned configuration and validates every required hash before evaluation.'}</p>
        </div>
        <CopyField label="reproduction command" value={run.reproduction_command} />
      </section>

      <section className="boundaries-grid" id="limitations">
        <article>
          <p className="eyebrow">Known limitations</p>
          <h2>Where this result stops.</h2>
          <ul>{run.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
        </article>
        <article className="prohibited">
          <p className="eyebrow">Prohibited claims</p>
          <h2>What the evidence cannot say.</h2>
          <ul>{run.prohibited_claims.map((claim) => <li key={claim}>{claim}</li>)}</ul>
        </article>
      </section>
    </div>
  )
}
