// The decision brief (spec F6, ADR 0012). The PM asks; the worker runs the bounded related-needs agent and one brief
// call; code verifies every claim. Flagged claims stay visible and marked, never hidden, and "How this brief was
// built" shows each agent step and each model call, so the PM can see exactly where every line came from.
import { AlertTriangle, CheckCircle2, ChevronDown, Loader2 } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { AIBadge } from '@/components/ai-badge'
import { ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cost, humanize, sourceLabel, when } from '@/lib/labels'

import { useAskBrief, useBrief, type BriefOut } from './hooks'

type Content = NonNullable<BriefOut['content']>
type Check = Content['checks'][number]

const RELATION: Record<string, string> = { overlaps: 'Overlaps', blocks: 'Blocks', depends_on: 'Depends on' }

export function DecisionBriefPanel({ needId, disabled }: { needId: number; disabled?: boolean }) {
  const brief = useBrief(needId)
  const ask = useAskBrief(needId)
  if (brief.isPending) return <LoadingState rows={2} label="Loading the brief" />
  if (brief.isError) return <ErrorState error={brief.error} onRetry={() => void brief.refetch()} />

  const b = brief.data
  const working = b != null && (b.status === 'pending' || b.status === 'processing')
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => ask.mutate()} disabled={disabled || working || ask.isPending}>
          {b?.status === 'ready' ? 'Brief me again' : 'Brief me'}
        </Button>
        <p className="text-sm text-muted-foreground">
          Reads the backlog for related needs (at most 8 read-only lookups), writes a brief and checks every quote and figure against the data. The decision stays yours.
        </p>
      </div>
      {ask.isError && <ErrorState error={ask.error} />}
      {working && (
        <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="size-4 animate-spin" /> Building the brief…
        </p>
      )}
      {b?.status === 'failed' && (
        <p role="alert" className="text-sm text-destructive">
          The brief failed: {b.error}. You can ask again.
        </p>
      )}
      {b?.content ? (
        <BriefView brief={b} content={b.content} />
      ) : b?.last_ready?.content ? (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">Showing the last ready brief while {b.status === 'failed' ? 'the new one failed' : 'a new one is built'}.</p>
          <BriefView brief={b.last_ready} content={b.last_ready.content} />
        </div>
      ) : null}
    </div>
  )
}

function Flag({ check }: { check: Check | undefined }) {
  if (!check || check.ok) return null
  return (
    <span role="status" className="inline-flex items-center gap-1 text-xs text-amber-700 dark:text-amber-400" data-testid="brief-flag">
      <AlertTriangle aria-hidden className="size-3" /> Unverified: {check.problem}
    </span>
  )
}

function Part({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <h3 className="text-sm font-medium">{title}</h3>
      {children}
    </div>
  )
}

function BriefView({ brief, content }: { brief: BriefOut; content: Content }) {
  const [open, setOpen] = useState(false)
  const howId = useId()
  const checks = new Map(content.checks.map((c) => [c.part, c]))
  const b = content.brief
  const related = content.related
  return (
    <Card role="article" aria-label="Decision brief" className="space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <AIBadge
          source={content.model}
          confidence={b.confidence}
          why={b.confidence_rationale}
          detail={`prompt ${content.prompt_version} · asked by ${brief.requested_by} ${when(brief.finished_at ?? brief.created_at)}`}
          testId="brief-source"
        />
        <p className="flex items-center gap-1 text-sm" data-testid="brief-verification">
          {content.flagged === 0 ? (
            <>
              <CheckCircle2 aria-hidden className="size-4 text-emerald-600" /> All {content.checks.length} claims checked against the data
            </>
          ) : (
            <>
              <AlertTriangle aria-hidden className="size-4 text-amber-600" /> {content.flagged} of {content.checks.length} claims unverified, shown flagged
            </>
          )}
          {content.repaired && <span className="text-muted-foreground"> · after one repair round</span>}
        </p>
      </div>

      <Part title="Summary">
        <p className="text-sm">{b.summary}</p>
        <Flag check={checks.get('summary')} />
      </Part>
      <div className="grid gap-4 sm:grid-cols-2">
        <Part title="Problem">
          <p className="text-sm">{b.problem}</p>
          <Flag check={checks.get('problem')} />
        </Part>
        <Part title="Who is affected">
          <p className="text-sm">{b.who_is_affected}</p>
          <Flag check={checks.get('who_is_affected')} />
        </Part>
      </div>

      <Part title="Business impact">
        <ul className="space-y-2">
          {b.business_impact.map((c, i) => (
            <li key={i} className="space-y-1 text-sm">
              <p>{c.statement}</p>
              <div className="flex flex-wrap gap-1">
                {c.facts.map((f) => (
                  <Badge key={f.key} variant="outline" className="font-normal" data-testid="impact-fact" title="From the data, not the model">
                    {f.label}: {f.display}
                  </Badge>
                ))}
              </div>
              <Flag check={checks.get(`business_impact[${i}]`)} />
            </li>
          ))}
        </ul>
      </Part>

      <Part title="Evidence">
        <ul className="space-y-2">
          {b.evidence.map((e, i) => (
            <li key={i} className="space-y-1">
              <blockquote className="border-l-2 pl-3 text-sm italic">“{e.quote}”</blockquote>
              <p className="text-xs text-muted-foreground">Request #{e.request_id}</p>
              <Flag check={checks.get(`evidence[${i}]`)} />
            </li>
          ))}
        </ul>
      </Part>

      <Part title="Related needs">
        {related.status === 'unavailable' ? (
          <p className="text-sm text-muted-foreground">Related needs were not checked: {related.reason}</p>
        ) : b.related_needs.length === 0 ? (
          <p className="text-sm text-muted-foreground">None found in the backlog.</p>
        ) : (
          <ul className="space-y-2">
            {b.related_needs.map((r, i) => (
              <li key={i} className="space-y-1 text-sm">
                <Badge variant="secondary">{RELATION[r.relation] ?? humanize(r.relation)}</Badge>{' '}
                {checks.get(`related_needs[${i}]`)?.ok === false ? (
                  <span>Need #{r.need_id}</span> // not a verified finding: it may not exist, so no link
                ) : (
                  <Link to={`/needs/${r.need_id}`} className="underline underline-offset-4">
                    {r.need_title || `Need #${r.need_id}`}
                  </Link>
                )}
                <p className="text-muted-foreground">{r.why_it_matters}</p>
                <Flag check={checks.get(`related_needs[${i}]`)} />
              </li>
            ))}
          </ul>
        )}
        {related.status === 'incomplete' && <p className="text-xs text-muted-foreground">{related.reason}</p>}
      </Part>

      <Part title="Options">
        <ul className="grid gap-2 sm:grid-cols-2">
          {b.options.map((o, i) => (
            <li key={i} className="rounded-lg bg-muted/40 p-3 text-sm">
              <p className="font-medium">{o.name}</p>
              <p>{o.description}</p>
              <p className="text-muted-foreground">Tradeoffs: {o.tradeoffs}</p>
              <Flag check={checks.get(`options[${i}]`)} />
            </li>
          ))}
        </ul>
      </Part>

      <Part title="Recommendation">
        <p className="text-sm">{b.recommendation}</p>
        <Flag check={checks.get('recommendation')} />
      </Part>
      <div className="grid gap-4 sm:grid-cols-2">
        <Part title="Risks">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {b.risks.map((r, i) => (
              <li key={i}>
                {r} <Flag check={checks.get(`risks[${i}]`)} />
              </li>
            ))}
          </ul>
        </Part>
        <Part title="Open questions">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {b.open_questions.map((q, i) => (
              <li key={i}>
                {q} <Flag check={checks.get(`open_questions[${i}]`)} />
              </li>
            ))}
          </ul>
        </Part>
      </div>

      <Button variant="outline" size="sm" aria-expanded={open} aria-controls={howId} onClick={() => setOpen((v) => !v)}>
        <ChevronDown aria-hidden className={open ? 'size-4 rotate-180' : 'size-4'} /> How this brief was built
      </Button>
      {open && <HowBuilt id={howId} brief={brief} content={content} />}
    </Card>
  )
}

function HowBuilt({ id, brief, content }: { id: string; brief: BriefOut; content: Content }) {
  const r = content.related
  const total = brief.calls.reduce((sum, c) => sum + c.cost_usd, 0)
  return (
    <section id={id} aria-label="How this brief was built" className="space-y-4 rounded-lg border p-3">
      <div className="space-y-1 text-sm">
        <p>
          <span className="font-medium">1. Related-needs agent</span> ({sourceLabel(r.model)}, prompt {r.prompt_version}): {r.tool_calls} of {r.cap} tool calls,
          read-only tools only. {r.status === 'complete' ? 'Finished on its own.' : r.reason}
        </p>
        <Table aria-label="Agent steps">
          <TableHeader>
            <TableRow>
              <TableHead>#</TableHead>
              <TableHead>Tool</TableHead>
              <TableHead>Arguments</TableHead>
              <TableHead>Result</TableHead>
              <TableHead className="text-right">Size</TableHead>
              <TableHead className="text-right">Latency</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {r.steps.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground">
                  No tool calls.
                </TableCell>
              </TableRow>
            ) : (
              r.steps.map((s) => (
                <TableRow key={s.n}>
                  <TableCell>{s.n}</TableCell>
                  <TableCell className="font-mono text-xs">{s.tool}</TableCell>
                  <TableCell className="max-w-64 truncate font-mono text-xs" title={JSON.stringify(s.args)}>
                    {JSON.stringify(s.args)}
                  </TableCell>
                  <TableCell>
                    {s.status === 'ok' ? 'ok' : <Badge variant="outline">{s.status}</Badge>}
                    {s.note && <span className="ml-1 text-xs text-muted-foreground">{s.note}</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{s.result_chars} chars</TableCell>
                  <TableCell className="text-right tabular-nums">{s.latency_ms} ms</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="space-y-1 text-sm">
        <p className="font-medium">2. What the agent reported, checked in code</p>
        {r.findings.length === 0 ? (
          <p className="text-muted-foreground">Nothing related reported.</p>
        ) : (
          <ul className="space-y-1">
            {r.findings.map((f, i) => (
              <li key={i}>
                {f.verified ? '✓' : '✗'} {RELATION[f.relation] ?? f.relation} {f.need_title ?? `need #${f.need_id}`}, citing request #{f.request_id}: “{f.quote}”
                {f.problem && <span className="text-amber-700 dark:text-amber-400"> ({f.problem}; not passed to the brief)</span>}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="space-y-1 text-sm">
        <p>
          <span className="font-medium">3. Brief</span> ({sourceLabel(content.model)}, prompt {content.prompt_version}), then {content.checks.length} checks
          in code{content.repaired ? ', one repair round' : ''}. Total cost {cost(total)}.
        </p>
        <Table aria-label="Model calls">
          <TableHeader>
            <TableRow>
              <TableHead>Step</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Input</TableHead>
              <TableHead className="text-right">Cache read</TableHead>
              <TableHead className="text-right">Output</TableHead>
              <TableHead className="text-right">Cost</TableHead>
              <TableHead className="text-right">Latency</TableHead>
              <TableHead>Outcome</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {brief.calls.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-mono text-xs">{c.step}</TableCell>
                <TableCell>{sourceLabel(c.model)}</TableCell>
                <TableCell className="text-right tabular-nums">{c.input_tokens + c.cache_write_tokens}</TableCell>
                <TableCell className="text-right tabular-nums">{c.cache_read_tokens}</TableCell>
                <TableCell className="text-right tabular-nums">{c.output_tokens}</TableCell>
                <TableCell className="text-right tabular-nums">{cost(c.cost_usd)}</TableCell>
                <TableCell className="text-right tabular-nums">{c.latency_ms} ms</TableCell>
                <TableCell>{c.outcome}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}
