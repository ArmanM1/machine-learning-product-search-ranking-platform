import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../src/App'

describe('application shell and overview', () => {
  it('renders the shopper problem and labels fixture evidence', async () => {
    render(<MemoryRouter initialEntries={['/']}><App /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: /machine learning product search ranking platform/i })).toBeInTheDocument()
    expect(screen.getByText(/a trained reranker learns which products/i)).toBeInTheDocument()
    expect(screen.getAllByText(/illustrative fixture/i).length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /compare a query/i })).toHaveAttribute('href', '/compare?q=query-fixture-001')
  })

  it('renders a helpful 404 without replacing it with nearby content', () => {
    render(<MemoryRouter initialEntries={['/definitely-not-a-route']}><App /></MemoryRouter>)

    expect(screen.getByText('404')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /evidence path does not exist/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /return to overview/i })).toHaveAttribute('href', '/')
  })
})
