import { useMemo } from 'react'
import type { ComparisonRanking, RelevanceLabel } from '../types/api'

interface ProductRankingProps {
  response: ComparisonRanking
  comparison?: ComparisonRanking
  title: string
  subtitle: string
  showJudgments: boolean
  showMovement?: boolean
}

const labelDescriptions: Record<RelevanceLabel, string> = {
  Exact: 'Directly satisfies the query',
  Substitute: 'Plausible alternative',
  Complement: 'Useful alongside the intended product',
  Irrelevant: 'Does not satisfy the query',
}

function Movement({ current, previous }: { current: number; previous?: number }) {
  if (!previous || previous === current) {
    return <span className="movement same" aria-label="No rank change">—</span>
  }
  const movement = previous - current
  const direction = movement > 0 ? 'up' : 'down'
  return (
    <span
      className={`movement ${direction}`}
      aria-label={`Moved ${Math.abs(movement)} ${direction === 'up' ? 'up' : 'down'} from rank ${previous}`}
    >
      <span aria-hidden="true">{direction === 'up' ? '↑' : '↓'}</span> {movement > 0 ? '+' : '−'}{Math.abs(movement)}
    </span>
  )
}

export function ProductRanking({
  response,
  comparison,
  title,
  subtitle,
  showJudgments,
  showMovement = false,
}: ProductRankingProps) {
  const comparisonRanks = useMemo(
    () => new Map(comparison?.results.map((product) => [product.product_id, product.rank]) ?? []),
    [comparison],
  )

  return (
    <section className="ranking-column" aria-label={`${title} ranking`}>
      <header className="ranking-header">
        <div>
          <p className="eyebrow">{subtitle}</p>
          <h2>{title}</h2>
        </div>
        <div className="latency-block">
          <strong>{response.latency_ms.toFixed(1)}</strong>
          <span>ms / request</span>
        </div>
      </header>
      <ol className="product-list">
        {response.results.map((product) => (
          <li className="product-card" key={product.product_id}>
            <span className="rank-number" aria-label={`Rank ${product.rank}`}>{String(product.rank).padStart(2, '0')}</span>
            <div className="product-copy">
              <h3>{product.title}</h3>
              <div className="product-meta">
                <span>Score {product.score >= 1 ? product.score.toFixed(2) : product.score.toFixed(3)}</span>
                {showJudgments && product.benchmark_label ? (
                  <span
                    className={`judgment-badge ${product.benchmark_label.toLocaleLowerCase()}`}
                    title={labelDescriptions[product.benchmark_label]}
                  >
                    {product.benchmark_label}
                  </span>
                ) : null}
              </div>
            </div>
            {showMovement ? (
              <Movement current={product.rank} previous={comparisonRanks.get(product.product_id)} />
            ) : <span className="reference-label">ref.</span>}
          </li>
        ))}
      </ol>
    </section>
  )
}

export function JudgmentLegend() {
  return (
    <section className="judgment-legend" aria-labelledby="judgment-legend-title">
      <div>
        <p className="eyebrow">Benchmark annotation</p>
        <h2 id="judgment-legend-title">How relevance is labeled</h2>
      </div>
      <dl>
        {(Object.entries(labelDescriptions) as Array<[RelevanceLabel, string]>).map(([label, description]) => (
          <div key={label}>
            <dt><span className={`judgment-dot ${label.toLocaleLowerCase()}`} aria-hidden="true" />{label}</dt>
            <dd>{description}</dd>
          </div>
        ))}
      </dl>
      <p className="legend-note">Labels come from benchmark judgments and never enter model input.</p>
    </section>
  )
}
