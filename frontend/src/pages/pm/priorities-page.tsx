import { Link } from 'react-router'

import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { QUADRANT, points, score } from '@/lib/labels'

import { BreakdownView } from './breakdown'
import { useQuadrant, useRankedNeeds, type QuadrantNeed } from './hooks'
import { QuadrantScatter } from './scatter'

const GROUPS = ['clear_win', 'strategic_bet', 'popular_off_strategy', 'park'] as const
const UNDECIDED = new Set(['open', 'planned', 'in_progress'])

export function PrioritiesPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Priorities"
        description="What is popular (revenue-weighted demand) and what is strategic (fit with company goals) are kept separate; the score behind each ranking is explained."
      />
      <QuadrantSection />
      <RankedSection />
    </div>
  )
}

function QuadrantSection() {
  const quadrant = useQuadrant()
  return (
    <section aria-labelledby="quadrant-heading" className="space-y-6">
      <h2 id="quadrant-heading" className="font-heading text-lg font-medium">
        Popular vs strategic
      </h2>
      {quadrant.isPending ? (
        <LoadingState rows={4} label="Loading quadrant" />
      ) : quadrant.isError ? (
        <ErrorState error={quadrant.error} onRetry={() => void quadrant.refetch()} />
      ) : (
        <QuadrantBody data={quadrant.data} />
      )}
    </section>
  )
}

function QuadrantBody({ data }: { data: NonNullable<ReturnType<typeof useQuadrant>['data']> }) {
  const placed = GROUPS.flatMap((g) => data.quadrants[g] ?? [])
  const cutoffs = { popular: data.cutoffs.popular ?? 0.5, strategic: data.cutoffs.strategic ?? 0.5 }
  return (
    <>
      <Card className="gap-2 p-4">
        <QuadrantScatter needs={placed} cutoffs={cutoffs} />
        <p className="text-xs text-muted-foreground">
          Dashed lines are the cut-offs (demand {score(cutoffs.popular)}, strategic fit {score(cutoffs.strategic)}). Dot size grows with the number of accounts. Click a dot to open the need.
        </p>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        {GROUPS.map((g) => (
          <NeedGroup key={g} title={QUADRANT[g] ?? g} needs={data.quadrants[g] ?? []} />
        ))}
        <NeedGroup
          title="Not rated yet"
          needs={data.not_rated}
          note="Strategic fit is pending: it is rated after a need gains support, and offline mode has no rater, so these needs are ranked on demand and urgency only."
          className="md:col-span-2"
        />
      </div>
    </>
  )
}

function NeedGroup({ title, needs, note, className }: { title: string; needs: QuadrantNeed[]; note?: string; className?: string }) {
  return (
    <Card className={`gap-2 p-4 ${className ?? ''}`}>
      <h3 className="font-medium">
        {title} <span className="font-normal text-muted-foreground">({needs.length})</span>
      </h3>
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      {needs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No needs here.</p>
      ) : (
        <ul className="space-y-1.5">
          {needs.map((n) => (
            <li key={n.id} className="flex flex-wrap items-baseline justify-between gap-x-3">
              <Link to={`/needs/${n.id}`} className="underline-offset-4 hover:underline">
                {n.title}
              </Link>
              <span className="text-xs text-muted-foreground tabular-nums">
                priority {points(n.priority)} · {n.owner}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function RankedSection() {
  const ranked = useRankedNeeds()
  const needs = ranked.data?.items.filter((n) => UNDECIDED.has(n.status)) ?? []
  return (
    <section aria-labelledby="ranked-heading" className="space-y-3">
      <h2 id="ranked-heading" className="font-heading text-lg font-medium">
        Ranked needs
      </h2>
      <p className="text-sm text-muted-foreground">Needs that are open, planned or in progress, highest priority first.</p>
      {ranked.isPending ? (
        <LoadingState rows={5} label="Loading ranked needs" />
      ) : ranked.isError ? (
        <ErrorState error={ranked.error} onRetry={() => void ranked.refetch()} />
      ) : needs.length === 0 ? (
        <EmptyState title="No undecided needs" description="Needs appear here as requests are triaged." />
      ) : (
        <Card className="p-0">
          <Table aria-label="Needs by priority">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead>Need</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Demand</TableHead>
                <TableHead>Strategic fit</TableHead>
                <TableHead>Urgency</TableHead>
                <TableHead>Quadrant</TableHead>
                <TableHead>Owner</TableHead>
                <TableHead>
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {needs.map((n, i) => {
                const b = n.breakdown
                return (
                  <TableRow key={n.id}>
                    <TableCell className="text-muted-foreground tabular-nums">{i + 1}</TableCell>
                    <TableCell className="max-w-72 whitespace-normal">
                      <Link to={`/needs/${n.id}`} className="font-medium underline-offset-4 hover:underline">
                        {n.title}
                      </Link>
                    </TableCell>
                    <TableCell className="tabular-nums">
                      <span data-testid="priority">{points(n.priority_score)}</span>
                    </TableCell>
                    <TableCell className="tabular-nums">{score(b.demand.value)}</TableCell>
                    <TableCell className="tabular-nums">{b.strategic.value == null ? <span className="text-muted-foreground">not rated</span> : score(b.strategic.value)}</TableCell>
                    <TableCell className="tabular-nums">{score(b.urgency.value)}</TableCell>
                    <TableCell>{b.quadrant ? QUADRANT[b.quadrant] : <span className="text-muted-foreground">Not rated</span>}</TableCell>
                    <TableCell>{b.owner}</TableCell>
                    <TableCell>
                      <Popover>
                        <PopoverTrigger asChild>
                          <Button variant="outline" size="sm">
                            Explain score
                          </Button>
                        </PopoverTrigger>
                        <PopoverContent
                          align="end"
                          aria-label={`Score breakdown: ${n.title}`}
                          className="max-h-[80vh] w-[28rem] max-w-[calc(100vw-2rem)] overflow-y-auto"
                        >
                          <p className="font-medium">Score breakdown: {n.title}</p>
                          <BreakdownView breakdown={b} />
                        </PopoverContent>
                      </Popover>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </Card>
      )}
    </section>
  )
}
