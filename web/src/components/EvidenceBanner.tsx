import { isFixtureMode } from '../api/client'
import { InfoIcon } from './Icons'

export function EvidenceBanner() {
  if (!isFixtureMode) return null

  return (
    <aside className="evidence-banner" aria-label="Evidence status">
      <InfoIcon />
      <div>
        <strong>Illustrative fixture</strong>
        <span>
          The values on this site demonstrate the finished interface. They are not measured results,
          cloud-run evidence, or portfolio claims.
        </span>
      </div>
    </aside>
  )
}
