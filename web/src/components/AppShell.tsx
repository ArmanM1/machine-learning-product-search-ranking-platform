import { useEffect, useRef } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { isFixtureMode, publicConfig } from '../api/client'
import { EvidenceBanner } from './EvidenceBanner'

const repositoryUrl = 'https://github.com/ArmanM1/machine-learning-product-search-ranking-platform'

const evidencePaths = ['/evidence', '/evaluation', '/failures', '/experiment', '/experiments/']

function isEvidencePath(pathname: string) {
  return evidencePaths.some((path) => pathname === path || pathname.startsWith(path))
}

function routeName(pathname: string) {
  if (pathname === '/' || pathname === '/compare') return 'Ranking workspace'
  if (pathname === '/evidence') return 'Evidence overview'
  if (pathname === '/evaluation') return 'Evaluation report'
  if (pathname === '/failures') return 'Failure analysis'
  if (pathname === '/experiment' || pathname.startsWith('/experiments/')) return 'Experiment provenance'
  return 'Page not found'
}

export function AppShell() {
  const location = useLocation()
  const previousPath = useRef(location.pathname)
  const pageName = routeName(location.pathname)
  const evidenceActive = isEvidencePath(location.pathname)

  useEffect(() => {
    document.title = `${pageName} | Rerank`

    if (previousPath.current === location.pathname) return
    previousPath.current = location.pathname

    const main = document.getElementById('main-content')
    if (!main) return

    let frame = 0
    let observer: MutationObserver | undefined
    const focusHeading = () => {
      if (main.querySelector('[aria-busy="true"]')) return false
      const heading = main.querySelector<HTMLElement>('h1')
      if (!heading) return false
      heading.setAttribute('tabindex', '-1')
      heading.focus()
      return true
    }

    frame = window.requestAnimationFrame(() => {
      if (focusHeading()) return
      observer = new MutationObserver(() => {
        if (focusHeading()) observer?.disconnect()
      })
      observer.observe(main, { attributes: true, childList: true, subtree: true })
    })

    return () => {
      window.cancelAnimationFrame(frame)
      observer?.disconnect()
    }
  }, [location.pathname, pageName])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="site-header">
        <div className="header-inner">
          <Link className="brand" to="/" aria-label="Rerank workspace home">
            <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
            <span className="brand-copy">
              <strong>Rerank</strong>
              <small>Product search lab</small>
            </span>
          </Link>

          <nav className="primary-nav" aria-label="Primary navigation">
            <NavLink to="/" end className={({ isActive }) => (isActive || location.pathname === '/compare' ? 'active' : undefined)}>
              Rank
            </NavLink>
            <Link className={evidenceActive ? 'active' : undefined} aria-current={evidenceActive ? 'page' : undefined} to="/evidence">
              Evidence
            </Link>
          </nav>

          <div className={`mode-badge ${isFixtureMode ? 'fixture' : 'verified'}`}>
            <span aria-hidden="true" />
            {isFixtureMode ? 'Fixture data' : 'Verified release'}
          </div>
        </div>

        {evidenceActive ? (
          <nav className="evidence-subnav" aria-label="Evidence navigation">
            <NavLink to="/evidence" end>Overview</NavLink>
            <NavLink to="/evaluation">Evaluation</NavLink>
            <NavLink to="/failures">Failures</NavLink>
            <NavLink to={`/experiments/${publicConfig.runId}`}>Run details</NavLink>
          </nav>
        ) : null}
      </header>

      <EvidenceBanner />

      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {pageName} page loaded
      </p>

      <main id="main-content" tabIndex={-1}>
        <Outlet />
      </main>

      <footer className="site-footer">
        <p><strong>Rerank</strong> compares ranking systems over identical candidate sets.</p>
        <nav className="footer-links" aria-label="Project resources">
          <a href={repositoryUrl}>Source</a>
          <a href={`${repositoryUrl}/blob/main/docs/model-card.md`}>Model card</a>
          <a href={`${repositoryUrl}/blob/main/docs/data-card.md`}>Data card</a>
        </nav>
      </footer>
    </div>
  )
}
