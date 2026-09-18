import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../src/App'
import { evidenceStatusPresentation } from '../src/components/evidenceStatus'

describe('application shell and ranking workspace', () => {
  it.each([
    [true, 'fixture', 'Fixture data'],
    [false, 'published', 'Published evidence'],
  ] as const)('labels fixture=%s without overstating the evidence', (fixture, className, label) => {
    expect(evidenceStatusPresentation(fixture)).toEqual({ className, label })
  })

  it('opens on the ranking action and labels fixture evidence', async () => {
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: /compare product rankings/i })).toBeInTheDocument()
    expect(screen.getByText(/choose a shopper query, then compare/i)).toBeInTheDocument()
    expect(screen.getAllByText(/illustrative fixture/i).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: 'Rank' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'Evidence' })).toHaveAttribute('href', '/evidence')
    expect(screen.getByRole('link', { name: 'Source' })).toHaveAttribute(
      'href',
      'https://github.com/ArmanM1/machine-learning-product-search-ranking-platform',
    )
  })

  it('renders a helpful 404 without replacing it with nearby content', () => {
    render(<MemoryRouter initialEntries={['/definitely-not-a-route']}><App /></MemoryRouter>)

    expect(screen.getByText('404')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /evidence path does not exist/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /return to workspace/i })).toHaveAttribute('href', '/')
  })

  it('shows paired slice intervals while marking an inadequate interval unavailable', async () => {
    render(<MemoryRouter initialEntries={['/failures']}><App /></MemoryRouter>)

    expect(await screen.findByRole('columnheader', { name: 'Paired CI' })).toBeInTheDocument()
    expect(screen.getByText('[−0.015, +0.004]')).toBeInTheDocument()
    const inadequateRow = screen.getByText('Accessory intent').closest('tr')
    expect(inadequateRow).not.toBeNull()
    expect(within(inadequateRow!).getByText('—')).toBeInTheDocument()
  })
})
