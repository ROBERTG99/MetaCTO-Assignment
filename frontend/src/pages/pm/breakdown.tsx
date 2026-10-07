// The priority breakdown: demand, urgency and strategic fit, each with its value, weight, inputs and points.
// Used in the "Explain score" popover (Priorities) and the Priority section of the need page.
import { useId, type ReactNode } from 'react'

import type { Schemas } from '@/api/client'
import { AIBadge } from '@/components/ai-badge'
import { Badge } from '@/components/ui/badge'
import { SEVERITY, money, percent, points, score } from '@/lib/labels'

type Breakdown = Schemas['PriorityBreakdown']

const STRATEGIC_STATUS: Record<string, string> = {
  rated: 'Rated',
  stale: 'Stale',
  pending: 'Pending',
  failed: 'Rating failed',
  not_rated: 'Not rated',
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** One component of the score. Its points element exists only when the component counts toward the total. */
function Component({
  title,
  value,
  weight,
  pts,
  missing,
  children,
}: {
  title: string
  value: number | null
  weight: number | undefined
  pts: number | undefined
  /** What to say instead of points when the component is not part of the score (e.g. "Pending"). */
  missing?: string
  children: ReactNode
}) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="space-y-2 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 id={id} className="font-medium">
          {title}
        </h3>
        {pts !== undefined ? (
          <span className="font-medium tabular-nums">
            <span data-testid="points">{points(pts)} points</span>
          </span>
        ) : (
          <Badge variant="outline">{missing ?? 'Not rated'}</Badge>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Value {score(value)} · weight {percent(weight)}
      </p>
      {children}
    </section>
  )
}

export function BreakdownView({ breakdown: b }: { breakdown: Breakdown }) {
  const { demand, urgency, strategic } = b
  const stratMissing = b.contributions.strategic === undefined
  return (
    <div className="space-y-3 text-sm">
      <Component title="Demand" value={demand.value} weight={b.weights.demand} pts={b.contributions.demand}>
        <ul className="space-y-0.5 text-muted-foreground">
          <li>
            <span className="text-foreground">{plural(demand.accounts, 'account')}</span> · {plural(demand.customers, 'customer')},{' '}
            {plural(demand.prospects, 'prospect')}
          </li>
          <li>
            Revenue behind it: <span className="text-foreground">{money(demand.revenue)}</span> (customers {money(demand.customer_revenue)},
            prospects {money(demand.prospect_revenue)})
          </li>
          {demand.gaps.length > 0 && <li>No ARR or pipeline on record: {demand.gaps.join(', ')}</li>}
        </ul>
      </Component>

      <Component title="Urgency" value={urgency.value} weight={b.weights.urgency} pts={b.contributions.urgency}>
        <ul className="space-y-0.5 text-muted-foreground">
          <li>{urgency.max_severity ? <>Highest severity: <span className="text-foreground">{SEVERITY[urgency.max_severity] ?? urgency.max_severity}</span></> : SEVERITY.unknown}</li>
          <li>
            {urgency.renewal_soon
              ? `A supporting customer renews within 90 days${urgency.renewing_accounts.length ? `: ${urgency.renewing_accounts.join(', ')}` : ''}`
              : 'No supporting customer renews within 90 days'}
          </li>
        </ul>
      </Component>

      <Component
        title="Strategic fit"
        value={strategic.value}
        weight={b.weights.strategic}
        pts={b.contributions.strategic}
        missing={STRATEGIC_STATUS[strategic.status] ?? 'Not rated'}
      >
        {stratMissing && (
          <p className="text-muted-foreground">
            {strategic.status === 'failed' && strategic.error ? `${strategic.error} ` : ''}
            Not part of the score yet, so the other weights are renormalised.
          </p>
        )}
        {strategic.goals.length > 0 && (
          <ul className="space-y-2">
            {strategic.goals.map((g) => (
              <li key={g.goal} className="space-y-1 rounded-md bg-muted/50 p-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-medium">{g.title}</span>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    weight {percent(g.weight)} · rating {g.rating ?? '—'}/3 · contributes {score(g.contribution)}
                  </span>
                </div>
                {g.rating != null && (
                  <AIBadge
                    source={strategic.model}
                    why={g.rationale}
                    detail={strategic.prompt_version ? `prompt ${strategic.prompt_version}` : undefined}
                    testId="goal-badge"
                  />
                )}
                {g.quote && <blockquote className="border-l-2 pl-2 text-xs text-muted-foreground italic">“{g.quote}”</blockquote>}
                {g.quote_dropped && <p className="text-xs text-muted-foreground">The model quoted text that is not in the requests; the quote was dropped.</p>}
              </li>
            ))}
          </ul>
        )}
      </Component>

      <p className="flex items-baseline justify-between border-t pt-2 font-medium">
        <span>Priority (out of 100)</span>
        <span className="tabular-nums">
          <span data-testid="priority-total">{points(b.priority)}</span>
        </span>
      </p>
    </div>
  )
}
