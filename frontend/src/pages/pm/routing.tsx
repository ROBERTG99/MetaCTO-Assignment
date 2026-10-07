// How a routing score was made: the parts that add up to it, and where it sits against the thresholds.
import { Check, X } from 'lucide-react'

import type { Schemas } from '@/api/client'
import { score } from '@/lib/labels'

type Routing = Schemas['RoutingParts']

/** A track from 0 to 1 with the suggest and auto thresholds and the score marked. */
function ScoreTrack({ value, suggest, auto }: { value: number | null; suggest: number | null; auto: number | null }) {
  const pos = (v: number) => `${Math.min(1, Math.max(0, v)) * 100}%`
  return (
    <div className="relative my-2 h-2 rounded-full bg-muted" aria-hidden>
      {suggest != null && <span className="absolute -top-1 h-4 w-px bg-muted-foreground/60" style={{ left: pos(suggest) }} />}
      {auto != null && <span className="absolute -top-1 h-4 w-px bg-muted-foreground/60" style={{ left: pos(auto) }} />}
      {value != null && <span className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-background" style={{ left: pos(value) }} />}
    </div>
  )
}

function Tick({ ok, label }: { ok: boolean | null; label: string }) {
  if (ok == null) return null
  const Icon = ok ? Check : X
  return (
    <span className="inline-flex items-center gap-0.5">
      <Icon aria-hidden className="size-3" />
      {label} {ok ? 'matches' : 'differs'}
    </span>
  )
}

export function RoutingBreakdown({ routing }: { routing: Routing }) {
  const thresholds = (
    <p className="text-xs text-muted-foreground">
      Suggest from {score(routing.suggest_threshold)} · auto-link from {score(routing.auto_threshold)}
    </p>
  )
  if (routing.mode === 'baseline') {
    return (
      <div className="space-y-1 text-sm" data-testid="routing-parts">
        <p>
          Embedding similarity <span className="font-medium tabular-nums">{score(routing.similarity)}</span>
          <span className="text-muted-foreground"> (offline baseline: the score is the similarity)</span>
        </p>
        <ScoreTrack value={routing.score} suggest={routing.suggest_threshold} auto={routing.auto_threshold} />
        {thresholds}
      </div>
    )
  }
  return (
    <div className="space-y-1 text-sm" data-testid="routing-parts">
      <p className="tabular-nums">
        <span className="text-muted-foreground">Label ({routing.label ?? '—'})</span> {score(routing.label_points)}
        <span className="text-muted-foreground"> + similarity </span>
        {score(routing.similarity_points)}
        <span className="text-muted-foreground"> + fields </span>
        {score(routing.field_points)}
        <span className="text-muted-foreground"> = </span>
        <span className="font-medium">{score(routing.score)}</span>
      </p>
      <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
        <Tick ok={routing.area_match} label="Product area" />
        <Tick ok={routing.persona_match} label="Persona" />
        {routing.similarity != null && <span>Embedding similarity {score(routing.similarity)}</span>}
      </p>
      <ScoreTrack value={routing.score} suggest={routing.suggest_threshold} auto={routing.auto_threshold} />
      {thresholds}
    </div>
  )
}
