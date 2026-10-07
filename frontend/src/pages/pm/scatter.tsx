// Popular (demand D) against strategic (fit S), drawn in SVG: no chart library.
import { useNavigate } from 'react-router'

import { QUADRANT, points, score } from '@/lib/labels'
import { cn } from '@/lib/utils'

import type { QuadrantNeed } from './hooks'

const W = 640
const H = 400
const M = { top: 16, right: 16, bottom: 40, left: 48 }
const PW = W - M.left - M.right
const PH = H - M.top - M.bottom

const x = (d: number) => M.left + d * PW
const y = (s: number) => M.top + (1 - s) * PH

const DOT: Record<string, string> = {
  clear_win: 'fill-primary',
  strategic_bet: 'fill-chart-3',
  popular_off_strategy: 'fill-chart-2',
  park: 'fill-muted-foreground',
}

export function QuadrantScatter({ needs, cutoffs }: { needs: QuadrantNeed[]; cutoffs: { popular: number; strategic: number } }) {
  const navigate = useNavigate()
  const rated = needs.filter((n): n is QuadrantNeed & { strategic: number } => n.strategic != null)
  const cx = x(cutoffs.popular)
  const cy = y(cutoffs.strategic)
  const ticks = [0, 0.25, 0.5, 0.75, 1]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Demand against strategic fit, one dot per rated need" className="h-auto w-full max-w-3xl text-foreground">
      {ticks.map((t) => (
        <g key={t} className="text-muted-foreground">
          <line x1={x(t)} x2={x(t)} y1={M.top} y2={M.top + PH} stroke="currentColor" strokeOpacity={0.12} />
          <line x1={M.left} x2={M.left + PW} y1={y(t)} y2={y(t)} stroke="currentColor" strokeOpacity={0.12} />
          <text x={x(t)} y={M.top + PH + 16} textAnchor="middle" fontSize={11} fill="currentColor">
            {t}
          </text>
          <text x={M.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="currentColor">
            {t}
          </text>
        </g>
      ))}
      <rect x={M.left} y={M.top} width={PW} height={PH} fill="none" stroke="currentColor" strokeOpacity={0.3} />

      {/* Cut-offs from config/priorities.yaml */}
      <line x1={cx} x2={cx} y1={M.top} y2={M.top + PH} stroke="currentColor" strokeOpacity={0.5} strokeDasharray="5 4" />
      <line x1={M.left} x2={M.left + PW} y1={cy} y2={cy} stroke="currentColor" strokeOpacity={0.5} strokeDasharray="5 4" />

      <g fontSize={12} fontWeight={500} className="fill-muted-foreground">
        <text x={M.left + 8} y={M.top + 18}>{QUADRANT.strategic_bet}</text>
        <text x={M.left + PW - 8} y={M.top + 18} textAnchor="end">{QUADRANT.clear_win}</text>
        <text x={M.left + 8} y={M.top + PH - 8}>{QUADRANT.park}</text>
        <text x={M.left + PW - 8} y={M.top + PH - 8} textAnchor="end">{QUADRANT.popular_off_strategy}</text>
      </g>

      <text x={M.left + PW / 2} y={H - 6} textAnchor="middle" fontSize={12} className="fill-foreground">
        Demand D (popular)
      </text>
      <text transform={`translate(12 ${M.top + PH / 2}) rotate(-90)`} textAnchor="middle" fontSize={12} className="fill-foreground">
        Strategic fit S
      </text>

      {rated.length === 0 && (
        <text x={M.left + PW / 2} y={M.top + PH / 2} textAnchor="middle" fontSize={13} className="fill-muted-foreground">
          No need has a strategic-fit rating yet, so there is nothing to plot.
        </text>
      )}

      {rated.map((n) => {
        const go = () => void navigate(`/needs/${n.id}`)
        return (
          <g
            key={n.id}
            role="link"
            tabIndex={0}
            aria-label={n.title}
            onClick={go}
            onKeyDown={(e) => {
              if (e.key === 'Enter') go()
            }}
            className="group cursor-pointer outline-none"
          >
            <title>{`${n.title}\nDemand ${score(n.demand)} · Strategic fit ${score(n.strategic)} · Priority ${points(n.priority)}`}</title>
            <circle
              cx={x(n.demand)}
              cy={y(n.strategic)}
              r={5 + Math.min(n.account_count, 12) * 0.6}
              className={cn(DOT[n.quadrant ?? 'park'], 'stroke-background group-hover:opacity-80 group-focus-visible:stroke-ring')}
              strokeWidth={2}
              fillOpacity={0.85}
            />
          </g>
        )
      })}
    </svg>
  )
}
