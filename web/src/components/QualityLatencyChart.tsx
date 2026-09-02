import type { ModelMetricRow } from '../types/api'

interface QualityLatencyChartProps {
  models: ModelMetricRow[]
}

const WIDTH = 680
const HEIGHT = 300
const PADDING = { top: 30, right: 38, bottom: 50, left: 64 }

export function QualityLatencyChart({ models }: QualityLatencyChartProps) {
  const measured = models.filter(
    (model): model is ModelMetricRow & { p95_inference_latency_ms: number } => model.p95_inference_latency_ms !== null,
  )
  if (!measured.length) return null

  const maxLatency = Math.max(...measured.map((model) => model.p95_inference_latency_ms), 1) * 1.1
  const minQuality = Math.min(...measured.map((model) => model.graded_ndcg_at_10)) - 0.025
  const maxQuality = Math.max(...measured.map((model) => model.graded_ndcg_at_10)) + 0.025
  const x = (latency: number) => PADDING.left + (latency / maxLatency) * (WIDTH - PADDING.left - PADDING.right)
  const y = (quality: number) => PADDING.top + ((maxQuality - quality) / (maxQuality - minQuality)) * (HEIGHT - PADDING.top - PADDING.bottom)
  const yTicks = [minQuality, (minQuality + maxQuality) / 2, maxQuality]
  const xTicks = [0, maxLatency / 2, maxLatency]

  return (
    <figure className="chart-card" aria-labelledby="quality-latency-title">
      <figcaption>
        <p className="eyebrow">Tradeoff</p>
        <h2 id="quality-latency-title">Quality versus inference latency</h2>
        <p>Upper-left is better: higher graded nDCG@10 with less CPU inference time.</p>
      </figcaption>
      <div className="chart-wrap">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-labelledby="chart-title chart-description">
          <title id="chart-title">Quality versus latency by model</title>
          <desc id="chart-description">A scatter plot comparing p95 latency in milliseconds and graded nDCG at 10 for three model systems.</desc>
          {yTicks.map((tick) => (
            <g key={`y-${tick}`}>
              <line className="chart-grid" x1={PADDING.left} x2={WIDTH - PADDING.right} y1={y(tick)} y2={y(tick)} />
              <text className="chart-tick" x={PADDING.left - 10} y={y(tick) + 4} textAnchor="end">{tick.toFixed(2)}</text>
            </g>
          ))}
          {xTicks.map((tick) => (
            <g key={`x-${tick}`}>
              <line className="chart-grid" x1={x(tick)} x2={x(tick)} y1={PADDING.top} y2={HEIGHT - PADDING.bottom} />
              <text className="chart-tick" x={x(tick)} y={HEIGHT - PADDING.bottom + 22} textAnchor="middle">{Math.round(tick)}</text>
            </g>
          ))}
          <text className="chart-axis-label" x={(PADDING.left + WIDTH - PADDING.right) / 2} y={HEIGHT - 8} textAnchor="middle">Model-inference p95 latency (ms)</text>
          <text className="chart-axis-label" transform={`translate(17 ${(PADDING.top + HEIGHT - PADDING.bottom) / 2}) rotate(-90)`} textAnchor="middle">Graded nDCG@10</text>
          {measured.map((model, index) => (
            <g className={`chart-point point-${index}`} key={model.model_id} transform={`translate(${x(model.p95_inference_latency_ms)} ${y(model.graded_ndcg_at_10)})`}>
              <circle r="7"><title>{model.display_name}: {model.graded_ndcg_at_10.toFixed(3)}, {model.p95_inference_latency_ms.toFixed(1)} ms</title></circle>
              <text x={index === 2 ? -12 : 12} y={index === 2 ? -14 : 4} textAnchor={index === 2 ? 'end' : 'start'}>{model.display_name}</text>
            </g>
          ))}
        </svg>
      </div>
      <ul className="chart-key sr-only">
        {measured.map((model) => (
          <li key={model.model_id}>{model.display_name}: nDCG@10 {model.graded_ndcg_at_10.toFixed(3)}; model-inference p95 {model.p95_inference_latency_ms.toFixed(1)} milliseconds</li>
        ))}
      </ul>
    </figure>
  )
}
