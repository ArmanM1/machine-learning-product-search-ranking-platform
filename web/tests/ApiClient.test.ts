import { buildComparisonPath } from '../src/api/client'

describe('API client contract', () => {
  it('sends the benchmark-judgment toggle as an explicit request parameter', () => {
    expect(buildComparisonPath('query / one', 'bm25-v1', 'candidate-v1', false)).toBe(
      '/api/v1/comparisons/query%20%2F%20one?baseline=bm25-v1&candidate=candidate-v1&include_judgments=false',
    )
    expect(buildComparisonPath('query-1', 'bm25-v1', 'candidate-v1', true)).toContain(
      'include_judgments=true',
    )
  })
})
