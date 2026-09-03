import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../src/App'
import { makeFixtureComparison } from '../src/api/fixtures'

describe('query comparison', () => {
  it('compares identical candidate groups and toggles benchmark annotations', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/compare?q=query-fixture-001']}><App /></MemoryRouter>)

    expect(await screen.findByRole('heading', { name: /quiet keyboard for office/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /bm25 lexical baseline ranking/i })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: /fine-tuned cross-encoder ranking/i })).toBeInTheDocument()
    expect(screen.getAllByText('Exact').length).toBeGreaterThan(0)
    expect(screen.getAllByLabelText(/moved .* up from rank/i).length).toBeGreaterThan(0)

    await user.click(screen.getByRole('checkbox', { name: /show benchmark labels/i }))
    expect(screen.queryAllByText('Exact')).toHaveLength(1)
  })

  it('filters curated queries without losing keyboard-operable controls', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/compare']}><App /></MemoryRouter>)
    const search = await screen.findByRole('searchbox', { name: /search curated queries/i })

    await user.type(search, 'leather')
    expect(screen.getByRole('button', { name: /apple watch band leather/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /quiet keyboard for office/i })).not.toBeInTheDocument()
  })

  it('keeps distinct order, scores, and latency attached to each reference fixture', async () => {
    const bm25 = makeFixtureComparison('query-fixture-001', 'bm25-v1')
    const pretrained = makeFixtureComparison('query-fixture-001', 'pretrained-v1')

    expect(pretrained.baseline.results.map((product) => product.product_id))
      .not.toEqual(bm25.baseline.results.map((product) => product.product_id))
    expect(pretrained.baseline.results.map((product) => product.score))
      .not.toEqual(bm25.baseline.results.map((product) => product.score))
    expect(pretrained.baseline.latency_ms).not.toBe(bm25.baseline.latency_ms)

    const user = userEvent.setup()
    render(<MemoryRouter initialEntries={['/compare?q=query-fixture-001']}><App /></MemoryRouter>)
    await screen.findByRole('option', { name: /unchanged cross-encoder/i })
    const referenceSelect = screen.getByRole('combobox', { name: /reference system/i })
    await user.selectOptions(referenceSelect, 'pretrained-v1')

    const ranking = await screen.findByRole('region', { name: /unchanged cross-encoder ranking/i })
    expect(within(ranking).getAllByRole('listitem')[0]).toHaveTextContent(/low-profile silent wireless keyboard/i)
    expect(within(ranking).getByText('Score 0.874')).toBeInTheDocument()
    expect(within(ranking).getByText('394.1')).toBeInTheDocument()
  })
})
