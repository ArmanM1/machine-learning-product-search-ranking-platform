import { NavLink, Outlet } from 'react-router-dom'
import { isFixtureMode, publicConfig } from '../api/client'
import { EvidenceBanner } from './EvidenceBanner'

const navItems = [
  { to: '/', label: 'Overview', end: true },
  { to: '/compare', label: 'Compare' },
  { to: '/evaluation', label: 'Evaluation' },
  { to: '/failures', label: 'Failures' },
  { to: `/experiments/${publicConfig.runId}`, label: 'Experiment' },
]

export function AppShell() {
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
