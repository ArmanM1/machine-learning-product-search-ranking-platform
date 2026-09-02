import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../src/App'

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
})
