import { Link } from 'react-router-dom'
import { ArrowRightIcon } from '../components/Icons'

export function NotFoundPage() {
  return (
    <div className="page-container not-found-page">
      <p className="not-found-code">404</p>
      <p className="eyebrow">Unknown route</p>
      <h1>This evidence path does not exist.</h1>
      <p>No substitute page was shown. Return to the ranking workspace or open the evidence record.</p>
      <div>
        <Link className="button primary" to="/">Return to workspace <ArrowRightIcon /></Link>
        <Link className="text-link" to="/evidence">Open evidence</Link>
      </div>
    </div>
  )
}
