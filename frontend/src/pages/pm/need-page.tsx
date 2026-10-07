import { useId, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'

import { ApiError } from '@/api/client'
import { useNeed } from '@/api/queries'
import { AIBadge } from '@/components/ai-badge'
import { NeedOrigin } from '@/components/need-origin'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SEGMENT, SEVERITY, SUPPORT_STATUS, humanize, money, score, sourceLabel, when } from '@/lib/labels'

import { DecisionBriefPanel } from './brief'
import { BreakdownView } from './breakdown'
import { ChangeStatusDialog, StakeholderUpdates } from './updates'

function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="font-heading text-lg font-medium">
        {title}
      </h2>
      {children}
    </section>
  )
}

function Field({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'space-y-1 sm:col-span-2' : 'space-y-1'}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

const EVENT: Record<string, string> = { link: 'Link', unlink: 'Unlink', status: 'Status', decision: 'Decision', ai_run: 'AI run' }
const ACTOR: Record<string, string> = { auto: 'auto-link', pm: 'a PM' }
const dateOnly = (d: string | null) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '—')

export function PmNeedPage() {
  const { needId } = useParams()
  const id = Number(needId)
  const need = useNeed(id)

  if (!Number.isFinite(id) || (need.error instanceof ApiError && need.error.status === 404)) {
    return <EmptyState title="Need not found" description="This need doesn't exist, or it was merged into another one." />
  }
  if (need.isPending) return <LoadingState rows={4} label="Loading need" />
  if (need.isError) return <ErrorState error={need.error} onRetry={() => void need.refetch()} />

  const n = need.data
  const merged = n.status === 'merged'
  const origin = n.origin

  return (
    <div className="space-y-6">
      <PageHeader
        title={n.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={n.status} kind="need" />
            <span>
              {n.support_count} {n.support_count === 1 ? 'supporter' : 'supporters'} · {n.account_count} {n.account_count === 1 ? 'account' : 'accounts'} · {n.request_count}{' '}
              {n.request_count === 1 ? 'request' : 'requests'}
            </span>
            {merged && n.merged_into_id != null && (
              <Link to={`/needs/${n.merged_into_id}`} className="underline underline-offset-4">
                Merged into need #{n.merged_into_id}
              </Link>
            )}
          </span>
        }
        actions={<ChangeStatusDialog needId={id} current={n.status} disabled={merged} />}
      />

      <Section title="Decision brief">
        <DecisionBriefPanel needId={id} disabled={merged} />
      </Section>

      <Section title="Stakeholder updates">
        <StakeholderUpdates needId={id} />
      </Section>

      <Section title="Need">
        <Card className="p-4">
          <dl className="grid gap-4 sm:grid-cols-2">
            <Field label="Problem" wide>
              {n.problem}
            </Field>
            <Field label="Persona">{humanize(n.persona)}</Field>
            <Field label="Product area">{humanize(n.product_area)}</Field>
            <Field label="Job to be done" wide>
              {n.job_to_be_done || '—'}
            </Field>
            <Field label="Owner">{n.breakdown.owner}</Field>
            <Field label="How this need was created">
              <NeedOrigin origin={origin} />
            </Field>
          </dl>
        </Card>
      </Section>

      <Section title="Priority">
        <Card className="p-4">
          <BreakdownView breakdown={n.breakdown} />
        </Card>
      </Section>

      <Section title="AI analysis">
        {n.requests.length === 0 ? (
          <EmptyState title="No requests yet" />
        ) : (
          <ul className="space-y-3">
            {n.requests.map((r) => {
              const a = r.analysis
              const link = r.link
              return (
                <li key={r.id}>
                  <Card className="gap-3 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <h3 className="font-medium">{r.title}</h3>
                        <p className="text-xs text-muted-foreground">
                          {r.requester_name}
                          {r.account_name ? ` · ${r.account_name}` : ''} · {when(r.created_at)}
                        </p>
                      </div>
                      <StatusBadge status={r.status} kind="request" />
                    </div>
                    <p className="text-sm text-muted-foreground">{r.description}</p>
                    {a ? (
                      <div className="space-y-2 rounded-lg bg-muted/40 p-3">
                        <AIBadge source={a.source?.model} confidence={a.confidence} why={a.rationale} detail={a.source?.prompt_version ? `prompt ${a.source.prompt_version}` : null} testId="analysis-badge" />
                        <dl className="grid gap-3 text-sm sm:grid-cols-2">
                          <Field label="Need statement" wide>
                            {a.need_statement ?? '—'}
                          </Field>
                          <Field label="Problem">{a.problem ?? '—'}</Field>
                          <Field label="Proposed solution">{a.proposed_solution ?? '—'}</Field>
                          <Field label="Persona">{humanize(a.persona)}</Field>
                          <Field label="Product area">{humanize(a.product_area)}</Field>
                          <Field label="Job to be done">{a.job_to_be_done ?? '—'}</Field>
                          <Field label="Severity signal">{a.severity_signal ? (SEVERITY[a.severity_signal] ?? humanize(a.severity_signal)) : '—'}</Field>
                        </dl>
                      </div>
                    ) : (
                      <p className="text-sm text-muted-foreground">No AI analysis was recorded for this request.</p>
                    )}
                    {link && (
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="text-muted-foreground">
                          {link.routing_score == null && link.actor === 'auto'
                            ? 'Created this need'
                            : `Joined by ${ACTOR[link.actor] ?? link.actor}`}{' '}
                          · {when(link.at)}
                          {link.label ? ` · ${humanize(link.label)}` : ''}
                          {link.routing_score != null ? ` · routing score ${score(link.routing_score)}` : ''}
                        </span>
{(link.source || link.label) && (
                        <AIBadge
                          source={link.source?.model ?? (link.label === 'similar' ? 'offline-baseline' : null)}
                          why={link.rationale}
                          detail={link.source?.prompt_version ? `prompt ${link.source.prompt_version}` : null}
                          testId="link-badge"
                        />
)}
                      </div>
                    )}
                  </Card>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <Section title="Evidence">
        {n.evidence.length === 0 ? (
          <EmptyState title="No evidence yet" description="Verified quotes appear here once the AI links a request or rates strategic fit." />
        ) : (
          <ul className="space-y-3">
            {n.evidence.map((e, i) => (
              <li key={`${e.kind}-${e.request_id}-${e.goal}-${i}`}>
                <Card className="gap-1 p-4">
                  <blockquote className="border-l-2 pl-3 italic">“{e.quote}”</blockquote>
                  <p className="text-xs text-muted-foreground">
                    {e.kind === 'link' ? 'Why it was linked' : 'Strategic fit'}
                    {e.request_id != null ? ` · request #${e.request_id}` : ''}
                    {e.goal ? ` · goal ${humanize(e.goal)}` : ''}
                  </p>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Accounts">
        {n.accounts.length === 0 ? (
          <EmptyState title="No accounts yet" />
        ) : (
          <Card className="p-0">
            <Table aria-label="Accounts behind this need">
              <TableHeader>
                <TableRow>
                  <TableHead>Account</TableHead>
                  <TableHead>Segment</TableHead>
                  <TableHead>ARR</TableHead>
                  <TableHead>Pipeline (prospects)</TableHead>
                  <TableHead>Renewal</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {n.accounts.map((a) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">
                      {a.name} {a.is_prospect && <Badge variant="outline">Prospect</Badge>}
                    </TableCell>
                    <TableCell>{SEGMENT[a.segment] ?? humanize(a.segment)}</TableCell>
                    <TableCell className="tabular-nums">{a.is_prospect ? '—' : money(a.arr)}</TableCell>
                    <TableCell className="tabular-nums">{a.is_prospect ? money(a.pipeline_value) : '—'}</TableCell>
                    <TableCell>{dateOnly(a.renewal_date)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </Section>

      <Section title="Supporters">
        {n.supports.length === 0 ? (
          <EmptyState title="No supporters yet" />
        ) : (
          <Card className="p-0">
            <Table aria-label="Supporters">
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Account</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Why it matters</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {n.supports.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-medium">{s.requester_name}</TableCell>
                    <TableCell>{s.account_name ?? '—'}</TableCell>
                    <TableCell>{SEVERITY[s.severity] ?? s.severity}</TableCell>
                    <TableCell>{SUPPORT_STATUS[s.link_status] ?? s.link_status}</TableCell>
                    <TableCell className="max-w-96 whitespace-normal text-muted-foreground">{s.why_it_matters}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </Section>

      <Section title="AI audit trail">
        {n.audit_trail.length === 0 ? (
          <EmptyState title="No activity yet" />
        ) : (
          <Card className="p-0">
            <Table aria-label="AI audit trail">
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Event</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Summary</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {n.audit_trail.map((ev, i) => (
                  <TableRow key={`${ev.at}-${i}`}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{when(ev.at)}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{EVENT[ev.kind] ?? humanize(ev.kind)}</Badge>
                    </TableCell>
                    <TableCell>{ev.kind === 'ai_run' ? sourceLabel(ev.model ?? ev.actor) : (ACTOR[ev.actor] ?? humanize(ev.actor))}</TableCell>
                    <TableCell className="whitespace-normal">{ev.summary}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}
      </Section>
    </div>
  )
}
