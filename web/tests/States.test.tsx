import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../src/App'

describe('explicit interface states', () => {
  it.each([
    ['empty', 'Nothing to show yet'],
    ['error', 'Evidence unavailable'],
    ['not-ready', 'Model not ready'],
    ['conflict', 'Evidence version conflict'],
  ])('renders the %s state', async (state, title) => {
    render(<MemoryRouter initialEntries={[`/evaluation?state=${state}`]}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument()
  })

  it('renders an accessible loading state', () => {
    render(<MemoryRouter initialEntries={['/evaluation?state=loading']}><App /></MemoryRouter>)
    const panel = screen.getByRole('heading', { name: /gathering evidence/i }).closest('section')
    expect(panel).toHaveAttribute('aria-busy', 'true')
  })
})
