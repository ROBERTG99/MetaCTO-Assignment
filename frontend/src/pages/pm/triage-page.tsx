import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { PageHeader } from '@/components/page-header'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Card } from '@/components/ui/card'
import { Kbd } from '@/components/ui/kbd'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { useDecide, useTriage, useUnlink, type TriageItem } from './hooks'
import { TriageCard } from './triage-item'

type TabKey = 'audit' | 'suggestion' | 'claim' | 'auto_link' | 'review'

const EMPTY: Record<Exclude<TabKey, 'review'>, { title: string; description: string }> = {
  audit: { title: 'No audit sample waiting', description: 'A sample of auto-links is queued here so you can check the AI is not merging things it should not.' },
  suggestion: { title: 'No suggestions waiting', description: 'Requests the AI is unsure about land here. Nothing needs a decision right now.' },
  claim: { title: 'No claim disagreements', description: 'When the AI disagrees with a customer who says a need matches theirs, it shows up here.' },
  auto_link: { title: 'No auto-links in place', description: 'Requests the AI linked on its own appear here, and each can be undone.' },
}

function messageOf(error: unknown) {
  return error instanceof ApiError ? error.message : 'Something went wrong. Try again.'
}

/** Keys j/k/a/r must not fire while typing, with a modifier, or while a dialog or popover is open. */
function shortcutsBlocked(e: KeyboardEvent) {
  if (e.metaKey || e.ctrlKey || e.altKey) return true
  const t = e.target
  if (t instanceof HTMLElement && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName))) return true
  return document.querySelector('[role="dialog"], [role="alertdialog"]') !== null
}

export function TriagePage() {
  const triage = useTriage()
  const decide = useDecide()
  const unlink = useUnlink()
  const [tab, setTab] = useState<TabKey>('audit')
  const [selected, setSelected] = useState<number | null>(null)
  const [undoing, setUndoing] = useState<TriageItem | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const data = triage.data
  const byKind = (kind: TriageItem['kind']) => data?.items.filter((i) => i.kind === kind) ?? []
  const lists: Record<Exclude<TabKey, 'review'>, TriageItem[]> = {
    audit: byKind('audit'),
    suggestion: byKind('suggestion'),
    claim: byKind('claim'),
    auto_link: data?.auto_linked ?? [],
  }
  const current = tab === 'review' ? [] : lists[tab]
  const sel = selected == null || current.length === 0 ? null : Math.min(selected, current.length - 1)
  const busyId = decide.isPending ? decide.variables.item.id : unlink.isPending ? unlink.variables.id : null

  const act = useCallback(
    (item: TriageItem, verb: 'accept' | 'reject') => {
      decide.mutate(
        { item, verb },
        {
          onSuccess: () => {
            if (verb === 'accept' && item.kind === 'suggestion') toast.success(`Linked to ${item.need?.title ?? 'the need'}`)
            else if (verb === 'accept') toast.success(item.kind === 'audit' ? 'Marked correct' : 'Support confirmed')
            else toast.success(item.kind === 'audit' ? 'Marked as a false merge and unlinked' : item.kind === 'claim' ? 'Claim rejected' : 'Kept separate')
          },
          onError: (error) => toast.error(messageOf(error)),
        },
      )
    },
    [decide],
  )

  // Keyboard: j / k move through the active tab, a accepts, r rejects.
  const busy = decide.isPending || unlink.isPending
  const latest = useRef({ current, sel, tab, act, busy })
  useEffect(() => {
    latest.current = { current, sel, tab, act, busy }
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (shortcutsBlocked(e)) return
      const { current: items, sel: at, tab: active, act: decideItem, busy: deciding } = latest.current
      // A held key repeats: never let it decide item after item (audit verdicts can't be undone).
      if ((e.key === 'a' || e.key === 'r') && (e.repeat || deciding)) {
        e.preventDefault()
        return
      }
      if (items.length === 0) return
      if (e.key === 'j') setSelected(at == null ? 0 : Math.min(items.length - 1, at + 1))
      else if (e.key === 'k') setSelected(at == null ? 0 : Math.max(0, at - 1))
      else if ((e.key === 'a' || e.key === 'r') && active !== 'auto_link' && at != null) {
        const item = items[at]
        if (item) decideItem(item, e.key === 'a' ? 'accept' : 'reject')
      } else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Keep the selected card on screen (only when the selection moves, not on every poll).
  useEffect(() => {
    if (selected == null) return
    listRef.current?.querySelector(`[data-triage-index="${selected}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selected, tab])

  const changeTab = (value: string) => {
    setTab(value as TabKey)
    setSelected(null)
  }

  const count = (n: number | undefined) => (n == null ? '' : ` (${n})`)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Triage inbox"
        description="At the locked threshold the gray zone is small, so most of your review work is the audit sample: a slice of the AI's own auto-links to check. Suggestions and claim disagreements are the rest."
        actions={
          <p className="hidden flex-wrap items-center gap-1.5 text-xs text-muted-foreground sm:flex">
            <Kbd>j</Kbd>
            <Kbd>k</Kbd> move · <Kbd>a</Kbd> accept / correct / confirm · <Kbd>r</Kbd> reject / false merge
          </p>
        }
      />

      {triage.isPending ? (
        <LoadingState rows={4} label="Loading triage inbox" />
      ) : triage.isError ? (
        <ErrorState error={triage.error} onRetry={() => void triage.refetch()} />
      ) : (
        <Tabs value={tab} onValueChange={changeTab} className="gap-4">
          <TabsList className="h-auto flex-wrap justify-start">
            <TabsTrigger value="audit">Audit sample{count(lists.audit.length)}</TabsTrigger>
            <TabsTrigger value="suggestion">Suggestions{count(lists.suggestion.length)}</TabsTrigger>
            <TabsTrigger value="claim">Claim disagreements{count(lists.claim.length)}</TabsTrigger>
            <TabsTrigger value="auto_link">Auto-linked{count(triage.data.auto_linked_total)}</TabsTrigger>
            <TabsTrigger value="review">Needs review{count(triage.data.needs_review.length)}</TabsTrigger>
          </TabsList>

          {(Object.keys(EMPTY) as Exclude<TabKey, 'review'>[]).map((key) => (
            <TabsContent key={key} value={key} className="space-y-4">
              {key === 'auto_link' && lists.auto_link.length > 0 && (
                <p className="text-sm text-muted-foreground">Applied by the AI above the calibrated threshold. Read-only: undo one if it is wrong and the request becomes its own need.</p>
              )}
              {lists[key].length === 0 ? (
                <EmptyState title={EMPTY[key].title} description={EMPTY[key].description} />
              ) : (
                <div ref={key === tab ? listRef : undefined} className="space-y-4">
                  {lists[key].map((item, i) => (
                    <TriageCard
                      key={`${item.kind}-${item.id}`}
                      item={item}
                      index={i}
                      selected={key === tab && sel === i}
                      busy={busyId === item.id}
                      onAccept={() => act(item, 'accept')}
                      onReject={() => act(item, 'reject')}
                      onUndo={() => setUndoing(item)}
                    />
                  ))}
                </div>
              )}
            </TabsContent>
          ))}

          <TabsContent value="review" className="space-y-3">
            {triage.data.needs_review.length === 0 ? (
              <EmptyState title="Nothing needs review" description="Every submitted request was processed. If the AI fails on one, it is saved and listed here with the reason." />
            ) : (
              <>
                <p className="text-sm text-muted-foreground">The AI could not process these. They are saved, and nothing was lost.</p>
                <ul aria-label="Requests that need review" className="space-y-3">
                  {triage.data.needs_review.map((r) => (
                    <li key={r.id}>
                      <Card className="gap-1 p-4">
                        <p className="font-medium">{r.title}</p>
                        <p className="text-sm text-muted-foreground">{r.reason ?? 'No reason was recorded.'}</p>
                        <p className="text-xs text-muted-foreground">
                          {r.attempts} {r.attempts === 1 ? 'attempt' : 'attempts'}
                        </p>
                      </Card>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </TabsContent>
        </Tabs>
      )}

      <AlertDialog open={undoing != null} onOpenChange={(open) => !open && setUndoing(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Undo this link?</AlertDialogTitle>
            <AlertDialogDescription>
              {undoing?.request ? `“${undoing.request.title}”` : 'This request'} will be unlinked from {undoing?.need ? `“${undoing.need.title}”` : 'its need'} and become its own need. The undo is recorded in the need's audit trail.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const item = undoing
                if (!item) return
                unlink.mutate(item, {
                  onSuccess: () => toast.success('Unlinked: the request is now its own need'),
                  onError: (error) => toast.error(messageOf(error)),
                })
              }}
            >
              Undo link
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
