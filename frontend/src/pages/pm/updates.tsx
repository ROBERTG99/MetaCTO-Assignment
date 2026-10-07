// Closing the loop (spec F7): the PM changes a status with a reason; the AI drafts a personal update per
// supporter and a CS note per account; code flags commitments; nothing goes out until the PM approves it.
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Send } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { ApiError, api, unwrap, type Schemas } from '@/api/client'
import { keys } from '@/api/queries'
import { PM_NAME } from '@/app/session-constants'
import { AIBadge } from '@/components/ai-badge'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { NEED_STATUS, sourceLabel, when } from '@/lib/labels'

import { useNeedUpdates } from './hooks'

type Draft = Schemas['DraftOut']
type Change = Schemas['StatusChangeOut']
type SettableStatus = Schemas['StatusChangeIn']['status']
const SETTABLE: SettableStatus[] = ['open', 'planned', 'in_progress', 'shipped', 'declined']

function useInvalidate(needId: number) {
  const qc = useQueryClient()
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: keys.needUpdates(needId) }),
      qc.invalidateQueries({ queryKey: keys.need(needId) }),
      qc.invalidateQueries({ queryKey: keys.needs() }),
      qc.invalidateQueries({ queryKey: keys.quadrant }),
      qc.invalidateQueries({ queryKey: keys.metrics }),
    ])
}

export function ChangeStatusDialog({ needId, current, disabled }: { needId: number; current: string; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<SettableStatus | ''>('')
  const [reason, setReason] = useState('')
  const [date, setDate] = useState('')
  const invalidate = useInvalidate(needId)
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH('/needs/{need_id}/status', {
          params: { path: { need_id: needId } },
          body: { status: status as SettableStatus, reason, target_date: date || null, by: PM_NAME },
        }),
      ),
    onSuccess: (c) => {
      toast.success(`Status set to ${NEED_STATUS[c.to_status] ?? c.to_status}. Drafting updates for supporters…`)
      setOpen(false)
      setStatus('')
      setReason('')
      setDate('')
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not change the status.'),
    onSettled: invalidate,
  })
  const ready = status !== '' && status !== current && reason.trim().length > 0
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)} disabled={disabled}>
        Change status
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change status</DialogTitle>
            <DialogDescription>
              A product decision. The AI drafts an update for every supporter and a note for customer success; nothing is
              sent until you approve each one.
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (ready) save.mutate()
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="new-status">New status</Label>
              <Select value={status} onValueChange={(v) => setStatus(v as SettableStatus)}>
                <SelectTrigger id="new-status" aria-label="New status" className="w-full">
                  <SelectValue placeholder="Choose a status" />
                </SelectTrigger>
                <SelectContent>
                  {SETTABLE.map((s) => (
                    <SelectItem key={s} value={s} disabled={s === current}>
                      {NEED_STATUS[s]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="status-reason">Reason</Label>
              <Textarea
                id="status-reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why this decision? Supporters will hear it in your words."
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="status-date">Target date (optional)</Label>
              <Input id="status-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              <p className="text-xs text-muted-foreground">
                Set a date only if you commit to it. Without one, any date, timeframe or delivery promise in a draft is flagged.
              </p>
            </div>
            <DialogFooter>
              <Button type="submit" disabled={!ready || save.isPending}>
                Save status
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

function Flags({ flags }: { flags: Draft['flags'] }) {
  if (flags.length === 0) return null
  return (
    <div role="status" aria-label="Flagged commitments" className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
      <p className="flex items-center gap-1.5 font-medium">
        <AlertTriangle aria-hidden className="size-4" />
        {flags.length === 1 ? 'A commitment you didn’t make' : `${flags.length} commitments you didn’t make`}
      </p>
      <ul className="list-disc space-y-0.5 pl-5">
        {flags.map((f) => (
          <li key={`${f.start}-${f.phrase}`}>{f.reason}</li>
        ))}
      </ul>
    </div>
  )
}

function DraftCard({ draft, needId }: { draft: Draft; needId: number }) {
  const [text, setText] = useState(draft.body) // the card is keyed by its saved body, so a save resets it
  const invalidate = useInvalidate(needId)
  const qc = useQueryClient()
  const onError = (e: unknown) => toast.error(e instanceof ApiError ? e.message : 'Something went wrong.')
  const save = useMutation({
    mutationFn: async () =>
      unwrap(await api.PATCH('/updates/{update_id}', { params: { path: { update_id: draft.id } }, body: { body: text, by: PM_NAME } })),
    onSuccess: (d) => toast.success(d.flags.length ? 'Saved. Still flagged: fix it before approving.' : 'Saved. No commitments flagged.'),
    onError,
    onSettled: () => qc.invalidateQueries({ queryKey: keys.needUpdates(needId) }),
  })
  const decide = useMutation({
    mutationFn: async (action: 'approve' | 'discard') =>
      unwrap(
        await api.POST(action === 'approve' ? '/updates/{update_id}/approve' : '/updates/{update_id}/discard', {
          params: { path: { update_id: draft.id } },
          body: { by: PM_NAME },
        }),
      ),
    onSuccess: (d) => toast.success(d.status === 'approved' ? `Sent to ${who}` : 'Draft discarded'),
    onError,
    onSettled: invalidate,
  })
  const personal = draft.kind === 'requester_update'
  const who = personal ? (draft.requester_name ?? 'a supporter') : (draft.account_name ?? 'an account')
  const dirty = text.trim() !== draft.body
  const isDraft = draft.status === 'draft'
  // unsaved text first: the flags are those of the saved text until the check runs on save
  const blocked = dirty ? 'Save your changes first: the commitment check runs on save' : draft.flags.length > 0 ? 'Fix the flagged commitments first' : null
  const hintId = `draft-${draft.id}-hint`
  return (
    <Card
      role="article"
      aria-label={personal ? `Update to ${who}` : `CS note for ${who}`}
      className="space-y-3 p-4"
      data-testid={personal ? 'requester-update' : 'cs-note'}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium">{personal ? `To ${who}` : `CS note · ${who}`}</h3>
        <div className="flex items-center gap-2">
          <AIBadge
            source={draft.source?.model}
            why={`Drafted by ${sourceLabel(draft.source?.model)} from your reason${personal ? ` and what ${who.split(' ')[0]} asked for` : ''}. Nothing is sent until you approve it.`}
            detail={draft.edited ? 'edited by you' : draft.source?.prompt_version ? `prompt ${draft.source.prompt_version}` : null}
            testId="draft-badge"
          />
          <Badge variant={draft.status === 'approved' ? 'secondary' : 'outline'}>
            {draft.status === 'approved' ? 'Sent' : draft.status === 'discarded' ? 'Discarded' : draft.status === 'superseded' ? 'Superseded' : 'Draft'}
          </Badge>
        </div>
      </div>
      {isDraft ? (
        <>
          <div className="space-y-1.5">
            <Label htmlFor={`draft-${draft.id}`}>{personal ? `Message to ${who}` : `Note for ${who}`}</Label>
            <Textarea id={`draft-${draft.id}`} value={text} onChange={(e) => setText(e.target.value)} rows={4} />
          </div>
          <Flags flags={draft.flags} />
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
              Save changes
            </Button>
            <Button
              size="sm"
              disabled={blocked !== null || decide.isPending}
              aria-describedby={blocked ? hintId : undefined}
              onClick={() => decide.mutate('approve')}
            >
              <Send aria-hidden className="size-3.5" />
              Approve and send
            </Button>
            <Button variant="ghost" size="sm" disabled={decide.isPending} onClick={() => decide.mutate('discard')}>
              Discard
            </Button>
            {blocked && (
              <span id={hintId} className="text-xs text-muted-foreground">
                {blocked}
              </span>
            )}
          </div>
        </>
      ) : (
        <>
          <p className="whitespace-pre-wrap text-sm">{draft.body}</p>
          <p className="text-xs text-muted-foreground">
            {draft.status === 'approved'
              ? `Approved by ${draft.approved_by} · ${when(draft.approved_at)} · in the outbox`
              : draft.status === 'superseded'
                ? 'Not sent: a later status change replaced this decision'
                : `Discarded · ${when(draft.approved_at)}`}
          </p>
        </>
      )}
    </Card>
  )
}

function ChangeCard({ change, needId }: { change: Change; needId: number }) {
  const invalidate = useInvalidate(needId)
  const redraft = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/needs/{need_id}/status-changes/{change_id}/redraft', {
          params: { path: { need_id: needId, change_id: change.id } },
          body: { by: PM_NAME },
        }),
      ),
    onSuccess: () => toast.success('Drafting again…'),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not start drafting again.'),
    onSettled: invalidate,
  })
  const personal = change.updates.filter((u) => u.kind === 'requester_update')
  const notes = change.updates.filter((u) => u.kind === 'cs_note')
  const sent = personal.filter((u) => u.status === 'approved').length
  return (
    <div className="space-y-3">
      <div className="text-sm">
        <p className="font-medium">
          {NEED_STATUS[change.from_status] ?? change.from_status} → {NEED_STATUS[change.to_status] ?? change.to_status}
          <span className="font-normal text-muted-foreground">
            {' '}
            · {when(change.created_at)} · by {change.by}
            {change.target_date ? ` · target date ${change.target_date}` : ' · no target date'}
          </span>
        </p>
        <p className="text-muted-foreground">Reason: {change.reason}</p>
        {personal.length > 0 && (
          <p className="text-muted-foreground">
            {sent} of {personal.length} supporters notified
          </p>
        )}
      </div>
      {change.drafts_status === 'pending' && <LoadingState rows={2} label="Drafting updates" />}
      {change.drafts_status === 'failed' && (
        <ErrorState
          error={new ApiError(500, 'drafts_failed', change.drafts_error ?? 'Drafting failed.')}
          onRetry={() => redraft.mutate()}
        />
      )}
      {change.drafts_status === 'superseded' && (
        <p className="text-sm text-muted-foreground">Not drafted: a later status change replaced this decision.</p>
      )}
      {change.drafts_status === 'drafted' && change.updates.length === 0 && (
        <EmptyState title="Nobody to notify" description="This need has no supporters or affected accounts yet." />
      )}
      {personal.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-muted-foreground">Personal updates</h3>
          {personal.map((d) => (
            <DraftCard key={`${d.id}:${d.body}`} draft={d} needId={needId} />
          ))}
        </div>
      )}
      {notes.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-muted-foreground">Notes for customer success</h3>
          {notes.map((d) => (
            <DraftCard key={`${d.id}:${d.body}`} draft={d} needId={needId} />
          ))}
        </div>
      )}
    </div>
  )
}

export function StakeholderUpdates({ needId }: { needId: number }) {
  const q = useNeedUpdates(needId)
  if (q.isPending) return <LoadingState rows={2} label="Loading updates" />
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />
  if (q.data.changes.length === 0)
    return (
      <EmptyState
        title="No status changes yet"
        description="When you change this need's status, the AI drafts an update for each supporter here for you to review."
      />
    )
  return (
    <div className="space-y-6">
      {q.data.changes.map((c) => (
        <ChangeCard key={c.id} change={c} needId={needId} />
      ))}
    </div>
  )
}
