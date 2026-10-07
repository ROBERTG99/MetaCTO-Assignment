import { Link } from 'react-router'

import { AIBadge } from '@/components/ai-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SEVERITY, humanize, when } from '@/lib/labels'
import { cn } from '@/lib/utils'

import type { TriageItem } from './hooks'
import { RoutingBreakdown } from './routing'

type NeedRef = NonNullable<TriageItem['need']>

/** Per kind: the labels on the buttons and how the need column is introduced. */
const KIND = {
  suggestion: { accept: 'Accept', reject: 'Reject', badge: 'Suggestion', needHeading: 'Would join this need' },
  audit: { accept: 'Correct', reject: 'False merge', badge: 'Audit sample', needHeading: 'Was linked to this need' },
  claim: { accept: 'Confirm', reject: 'Reject', badge: 'Claim disagreement', needHeading: 'Claimed need' },
  auto_link: { accept: '', reject: '', badge: 'Auto-linked', needHeading: 'Linked to this need' },
} as const

function NeedBlock({ heading, need }: { heading: string; need: NeedRef }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{heading}</p>
      <Link to={`/needs/${need.id}`} className="font-medium underline-offset-4 hover:underline">
        {need.title}
      </Link>
      <p className="text-sm text-muted-foreground">{need.problem}</p>
      <p className="text-xs text-muted-foreground">
        Persona: <span className="text-foreground">{humanize(need.persona)}</span> · Area: <span className="text-foreground">{humanize(need.product_area)}</span>
      </p>
    </div>
  )
}

export function TriageCard({
  item,
  index,
  selected,
  busy,
  onAccept,
  onReject,
  onUndo,
}: {
  item: TriageItem
  index: number
  selected: boolean
  busy: boolean
  onAccept: () => void
  onReject: () => void
  onUndo: () => void
}) {
  const kind = KIND[item.kind]
  const { request, need, support, routing } = item
  const baseline = routing?.mode === 'baseline'
  const headingId = `triage-${item.kind}-${item.id}`
  const title = request?.title ?? (need ? `Support claim: ${need.title}` : 'Support claim')
  return (
    <article
      aria-labelledby={headingId}
      data-request-id={request?.id}
      data-triage-index={index}
      data-selected={selected || undefined}
      aria-current={selected ? 'true' : undefined}
      className={cn('space-y-4 rounded-xl bg-card p-4 text-sm text-card-foreground ring-1 ring-foreground/10', selected && 'ring-2 ring-ring')}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <h3 id={headingId} className="font-heading text-base font-medium">
          {title}
        </h3>
        <div className="flex items-center gap-2">
          <Badge variant="outline">{kind.badge}</Badge>
          <span className="text-xs text-muted-foreground">{when(item.created_at)}</span>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{support && !request ? 'Support' : 'Request'}</p>
          {request && (
            <>
              <p>{request.description}</p>
              <p className="text-xs text-muted-foreground">
                {request.requester_name ?? 'Unknown requester'}
                {request.account_name ? ` · ${request.account_name}` : ''} · {when(request.created_at)}
              </p>
              {request.need_statement && (
                <p className="text-xs text-muted-foreground">
                  Extracted need: <span className="text-foreground">{request.need_statement}</span>
                </p>
              )}
            </>
          )}
          {support && (
            <div className="space-y-1">
              <p>{support.why_it_matters}</p>
              <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <Badge variant="secondary">{SEVERITY[support.severity] ?? support.severity}</Badge>
                {support.reason && <span>Disputed because: <span className="text-foreground">{support.reason}</span></span>}
              </p>
            </div>
          )}
        </div>
        <div className="space-y-3">
          {need && <NeedBlock heading={kind.needHeading} need={need} />}
          {item.alternative_need && <NeedBlock heading="The model would pick instead" need={item.alternative_need} />}
        </div>
      </div>

      <div className="space-y-2 rounded-lg bg-muted/40 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <AIBadge
            source={item.source?.model ?? (baseline ? 'offline-baseline' : null)}
            confidence={baseline ? routing?.similarity : item.model_confidence}
            confidenceLabel={baseline ? 'similarity' : 'confidence'}
            why={item.rationale}
            detail={item.source?.prompt_version ? `prompt ${item.source.prompt_version}` : null}
            testId="routing-badge"
          />
          {item.routing_score != null && !baseline && (
            <span className="text-xs text-muted-foreground">routing score {item.routing_score.toFixed(2)}</span>
          )}
        </div>
        {routing && <RoutingBreakdown routing={routing} />}
        {item.rationale && <p className="text-muted-foreground">{item.rationale}</p>}
        {item.quotes.length > 0 && (
          <ul aria-label="Quotes" className="space-y-1">
            {item.quotes.map((q) => (
              <li key={q}>
                <blockquote className="border-l-2 pl-2 text-xs text-muted-foreground italic">“{q}”</blockquote>
              </li>
            ))}
          </ul>
        )}
      </div>

      <footer className="flex flex-wrap items-center gap-2">
        {item.kind === 'auto_link' ? (
          <Button variant="outline" size="sm" disabled={busy} onClick={onUndo}>
            Undo
          </Button>
        ) : (
          <>
            <Button size="sm" disabled={busy} onClick={onAccept}>
              {kind.accept}
            </Button>
            <Button variant="outline" size="sm" disabled={busy} onClick={onReject}>
              {kind.reject}
            </Button>
          </>
        )}
      </footer>
    </article>
  )
}
