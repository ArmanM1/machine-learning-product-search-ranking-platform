import { useEffect, useRef } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { isFixtureMode, publicConfig } from '../api/client'
import { EvidenceBanner } from './EvidenceBanner'

const navItems = [
  { to: '/', label: 'Overview', end: true },
  { to: '/compare', label: 'Compare' },
  { to: '/evaluation', label: 'Evaluation' },
  { to: '/failures', label: 'Failures' },
  { to: `/experiments/${publicConfig.runId}`, label: 'Experiment' },
]

function routeName(pathname: string) {
  if (pathname === '/') return 'Evidence overview'
  if (pathname === '/compare') return 'Query comparison'
  if (pathname === '/evaluation') return 'Evaluation report'
  if (pathname === '/failures') return 'Failure analysis'
  if (pathname === '/experiment' || pathname.startsWith('/experiments/')) return 'Experiment provenance'
  return 'Page not found'
}

export function AppShell() {
  const location = useLocation()
  const previousPath = useRef(location.pathname)
  const pageName = routeName(location.pathname)

  useEffect(() => {
    document.title = `${pageName} | Rank / evidence`

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
          <NavLink className="brand" to="/" aria-label="Product Search Ranking home">
            <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
            <span className="brand-copy">
              <strong>Rank / evidence</strong>
              <small>Product search laboratory</small>
            </span>
          </NavLink>
          <nav className="primary-nav" aria-label="Primary navigation">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? 'active' : undefined)}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className={`mode-badge ${isFixtureMode ? 'fixture' : 'verified'}`}>
            <span aria-hidden="true" />
            {isFixtureMode ? 'Fixture mode' : 'Published evidence'}
          </div>
        </div>
      </header>

      <EvidenceBanner />

      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {pageName} page loaded
      </p>

      <main id="main-content" tabIndex={-1}>
        <Outlet />
      </main>

      <footer className="site-footer">
        <div>
          <p className="footer-title">Machine Learning Product Search Ranking Platform</p>
          <p>Reranks supplied candidate lists. It is not a full marketplace search engine.</p>
        </div>
        <div className="footer-meta">
          <span>US English</span>
          <span>Curated queries only</span>
          <span>No shopper data</span>
        </div>
      </footer>
    </div>
  )
}
