import { useState } from 'react'
import { useParams } from 'react-router'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { useSession } from '@/app/session'
import { useNeed } from '@/api/queries'
import { NeedOrigin } from '@/components/need-origin'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SEVERITY, SUPPORT_STATUS, humanize, when } from '@/lib/labels'

import { SupportDialog } from './support-dialog'

export function RequesterNeedPage() {
  const { needId } = useParams()
  const id = Number(needId)
  const need = useNeed(id)
  const { requesterId } = useSession()
  const [supporting, setSupporting] = useState(false)

  if (!Number.isFinite(id) || (need.error instanceof ApiError && need.error.status === 404)) {
    return <EmptyState title="Need not found" description="This need doesn't exist, or it was merged into another one." />
  }
  if (need.isPending) return <LoadingState rows={4} label="Loading need" />
  if (need.isError) return <ErrorState error={need.error} onRetry={() => void need.refetch()} />

  const n = need.data
  const origin = n.origin
  // A requester sees the updates written to them; CS notes and other people's updates are for the PM view.
  const mine = n.updates.filter((x) => x.kind === 'requester_update' && x.requester_id === requesterId)
  return (
    <div className="space-y-6">
      <PageHeader
        title={n.title}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge status={n.status} kind="need" />
            <span>
              {n.support_count} {n.support_count === 1 ? 'supporter' : 'supporters'} · {n.account_count}{' '}
              {n.account_count === 1 ? 'account' : 'accounts'}
            </span>
          </span>
        }
        actions={<Button onClick={() => setSupporting(true)}>Add my support</Button>}
      />

      <Card className="gap-4 p-4">
        <dl className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1 sm:col-span-2">
            <dt className="text-xs text-muted-foreground">Problem</dt>
            <dd>{n.problem}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">Persona</dt>
            <dd>{humanize(n.persona)}</dd>
          </div>
          <div className="space-y-1">
            <dt className="text-xs text-muted-foreground">Product area</dt>
            <dd>{humanize(n.product_area)}</dd>
          </div>
          <div className="space-y-1 sm:col-span-2">
            <dt className="text-xs text-muted-foreground">Job to be done</dt>
            <dd>{n.job_to_be_done || '—'}</dd>
          </div>
          <div className="space-y-1 sm:col-span-2">
            <dt className="text-xs text-muted-foreground">How this need was created</dt>
            <dd>
              <NeedOrigin origin={origin} />
            </dd>
          </div>
        </dl>
      </Card>

      <section aria-labelledby="requests-heading" className="space-y-3">
        <h2 id="requests-heading" className="font-heading text-lg font-medium">
          Requests
        </h2>
        {n.requests.length === 0 ? (
          <EmptyState title="No requests yet" />
        ) : (
          <ul className="space-y-3">
            {n.requests.map((r) => (
              <li key={r.id}>
                <Card className="gap-1 p-4">
                  <p className="font-medium">{r.title}</p>
                  <p className="text-xs text-muted-foreground">
                    {r.requester_name}
                    {r.account_name ? ` · ${r.account_name}` : ''} · {when(r.created_at)}
                  </p>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="supporters-heading" className="space-y-3">
        <h2 id="supporters-heading" className="font-heading text-lg font-medium">
          Supporters
        </h2>
        {n.supports.length === 0 ? (
          <EmptyState title="No supporters yet" description="Be the first to say this matters to you." />
        ) : (
          <ul className="space-y-3">
            {n.supports.map((s) => (
              <li key={s.id}>
                <Card className="gap-2 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{s.requester_name}</span>
                    {s.account_name && <span className="text-sm text-muted-foreground">{s.account_name}</span>}
                    <Badge variant="outline">{SEVERITY[s.severity] ?? s.severity}</Badge>
                    <Badge variant="secondary">{SUPPORT_STATUS[s.link_status] ?? s.link_status}</Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">{s.why_it_matters}</p>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="updates-heading" className="space-y-3">
        <h2 id="updates-heading" className="font-heading text-lg font-medium">
          Updates
        </h2>
        {mine.length === 0 ? (
          <EmptyState title="No updates yet" description="When the team posts an update on this need, you'll see it here." />
        ) : (
          <ul className="space-y-3">
            {mine.map((u) => (
              <li key={u.id}>
                <Card className="gap-1 p-4">
                  <p>{u.body}</p>
                  <p className="text-xs text-muted-foreground">From the product team · {when(u.approved_at)}</p>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <SupportDialog
        need={supporting ? { id: n.id, title: n.title } : null}
        onOpenChange={setSupporting}
        onAdded={() => {
          setSupporting(false)
          toast.success('Support added')
        }}
      />
    </div>
  )
}
