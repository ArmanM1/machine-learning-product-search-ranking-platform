import { Link } from 'react-router-dom'
import { ArrowRightIcon } from '../components/Icons'

export function NotFoundPage() {
  return (
    <div className="page-container not-found-page">
      <p className="not-found-code">404</p>
      <p className="eyebrow">Unknown route</p>
      <h1>This evidence path does not exist.</h1>
      <p>No substitute page was shown. Return to the overview or open a curated ranking comparison.</p>
      <div>
        <Link className="button primary" to="/">Return to overview <ArrowRightIcon /></Link>
        <Link className="text-link" to="/compare">Open comparison</Link>
      </div>
    </div>
  )
}
