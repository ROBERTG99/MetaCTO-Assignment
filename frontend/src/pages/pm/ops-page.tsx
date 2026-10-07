import type { ReactNode } from 'react'

import type { Schemas } from '@/api/client'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { PageHeader } from '@/components/page-header'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cost, humanize, percent, sourceLabel } from '@/lib/labels'

import { useMetrics } from './hooks'

type Rate = Schemas['RateOut']

function Metric({ title, value, children, badge }: { title: string; value: ReactNode; children?: ReactNode; badge?: ReactNode }) {
  return (
    <Card className="gap-2 p-4">
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-sm text-muted-foreground">{title}</h3>
        {badge}
      </div>
      <p className="font-heading text-2xl font-semibold tabular-nums">{value}</p>
      {children && <div className="space-y-0.5 text-xs text-muted-foreground">{children}</div>}
    </Card>
  )
}

/** "k of n" always sits next to a rate, so 100% on 1 is not oversold; the Wilson interval says how far to trust it. */
function KofN({ k, n, noun }: { k: number; n: number; noun?: string }) {
  return (
    <p>
      {k} of {n}
      {noun ? ` ${noun}` : ''}
    </p>
  )
}

function Interval({ rate }: { rate: Rate }) {
  if (rate.n === 0) return <p>No data yet</p>
  return (
    <p>
      95% interval {percent(rate.low)} to {percent(rate.high)}
    </p>
  )
}

export function OpsPage() {
  const metrics = useMetrics()
  return (
    <div className="space-y-8">
      <PageHeader title="AI Ops" description="What the AI costs, how often the PM agrees with it, and whether it is meeting the success metrics. Every rate shows its sample size." />
      {metrics.isPending ? (
        <LoadingState rows={4} label="Loading metrics" />
      ) : metrics.isError ? (
        <ErrorState error={metrics.error} onRetry={() => void metrics.refetch()} />
      ) : (
        <Body m={metrics.data} />
      )}
    </div>
  )
}

function Body({ m }: { m: Schemas['OpsMetrics'] }) {
  const fm = m.false_merge
  const target =
    fm.within_target === true ? (
      <Badge variant="secondary">Within target</Badge>
    ) : fm.within_target === null ? (
      <Badge variant="outline">No audits yet</Badge>
    ) : (fm.audited.value ?? 0) > fm.target ? (
      <Badge variant="destructive">Over target</Badge>
    ) : (
      // the point estimate is under target but the 95% interval still reaches above it
      <Badge variant="outline">Too few audits to tell</Badge>
    )
  return (
    <>
      <section aria-labelledby="cost-heading" className="space-y-3">
        <h2 id="cost-heading" className="font-heading text-lg font-medium">
          Cost and quality
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric title="Model calls" value={m.totals.calls}>
            <p>Total cost {cost(m.totals.cost_usd)}</p>
          </Metric>
          <Metric title="Cost per processed request" value={cost(m.totals.cost_per_request)}>
            <p>{m.totals.processed_requests} requests processed</p>
          </Metric>
          <Metric title="Needs review" value={percent(m.needs_review.value)}>
            <KofN k={m.needs_review.k} n={m.needs_review.n} noun="finished requests failed to the PM" />
            <Interval rate={m.needs_review} />
          </Metric>
          <Metric title="Suggestion acceptance" value={percent(m.acceptance.value)}>
            <KofN k={m.acceptance.k} n={m.acceptance.n} noun="suggestions accepted" />
            <Interval rate={m.acceptance} />
          </Metric>
          <Metric title="Audited false-merge rate" value={percent(fm.audited.value)} badge={target}>
            <KofN k={fm.audited.k} n={fm.audited.n} noun="audited auto-links wrong" />
            <Interval rate={fm.audited} />
            <p>Target {percent(fm.target)} or lower</p>
            <p>
              {fm.undone} of {fm.auto_links} auto-links undone ({percent(fm.undo_rate)}): a lower bound on false merges
            </p>
          </Metric>
        </div>
      </section>

      <section aria-labelledby="success-heading" className="space-y-3">
        <h2 id="success-heading" className="font-heading text-lg font-medium">
          Success metrics
        </h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Metric title="M1 · Triage effort" value={percent(m.m1.value)}>
            <p>of finished requests no PM had to touch (open suggestions and failures count as touched)</p>
            <KofN k={m.m1.untouched} n={m.m1.processed} noun="untouched" />
            <p>{m.m1.pm_minutes_per_100 == null ? 'PM time per 100 requests: —' : `About ${m.m1.pm_minutes_per_100.toFixed(0)} PM minutes per 100 requests`}</p>
          </Metric>
          <Metric title="M2 · Duplicate rate" value={percent(m.m2.deflection)}>
            <p>deflected at the door</p>
            <KofN k={m.m2.claims} n={m.m2.claims + m.m2.new_requests} noun="submissions were claims on an existing need" />
            <p>
              Leakage {percent(m.m2.leakage)}: {m.m2.relinked_by_pm} of {m.m2.new_need_requests} new-need requests later linked to an existing need by a PM
            </p>
            <p className="text-muted-foreground">{m.m2.note}</p>
          </Metric>
          <Metric title="M3 · Decision-loop latency" value={m.m3.value == null ? 'Not measured yet' : String(m.m3.value)}>
            <p>{m.m3.note}</p>
          </Metric>
        </div>
      </section>

      <section aria-labelledby="calls-heading" className="space-y-3">
        <h2 id="calls-heading" className="font-heading text-lg font-medium">
          Model calls
        </h2>
        {m.runs.length === 0 ? (
          <EmptyState title="No model calls yet" description="Runs appear as the intake workflow processes requests. Offline-baseline rows call no model and cost nothing." />
        ) : (
          <Card className="p-0">
            <Table aria-label="Model calls">
              <TableHeader>
                <TableRow>
                  <TableHead>Step</TableHead>
                  <TableHead>Model</TableHead>
                  <TableHead>Prompt</TableHead>
                  <TableHead className="text-right">Calls</TableHead>
                  <TableHead className="text-right">Failure rate</TableHead>
                  <TableHead className="text-right">Cost</TableHead>
                  <TableHead className="text-right">Cost per call</TableHead>
                  <TableHead className="text-right">p50</TableHead>
                  <TableHead className="text-right">p95</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {m.runs.map((r) => (
                  <TableRow key={`${r.step}-${r.model}-${r.prompt_version}`}>
                    <TableCell className="font-medium">{humanize(r.step)}</TableCell>
                    <TableCell>{sourceLabel(r.model)}</TableCell>
                    <TableCell>{r.prompt_version}</TableCell>
                    <TableCell className="text-right tabular-nums">{r.calls}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {percent(r.failure_rate)} <span className="text-muted-foreground">({r.calls - r.ok} of {r.calls})</span>
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{cost(r.cost_usd)}</TableCell>
                    <TableCell className="text-right tabular-nums">{cost(r.cost_per_call)}</TableCell>
                    <TableCell className="text-right tabular-nums">{Math.round(r.p50_ms)} ms</TableCell>
                    <TableCell className="text-right tabular-nums">{Math.round(r.p95_ms)} ms</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </section>
    </>
  )
}
