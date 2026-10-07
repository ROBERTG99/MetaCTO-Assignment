// PM-workspace queries and mutations. They reuse the shared `keys`, so the requester half sees the same cache.
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { ApiError, api, unwrap, type Schemas } from '@/api/client'
import { keys } from '@/api/queries'
import { PM_NAME } from '@/app/session-constants'

export type TriageItem = Schemas['TriageItem']
export type TriageList = Schemas['TriageList']
export type QuadrantNeed = Schemas['QuadrantNeed']

export const TRIAGE_POLL_MS = 3000

/** The inbox. Polls, because the worker keeps adding suggestions while the PM works. */
export function useTriage() {
  return useQuery({
    queryKey: keys.triage,
    queryFn: async () => unwrap(await api.GET('/triage')),
    refetchInterval: TRIAGE_POLL_MS,
  })
}

/** Everything a link, unlink or decision can change: the inbox, the needs and their scores. */
function invalidateAfterDecision(qc: QueryClient) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: keys.triage }),
    qc.invalidateQueries({ queryKey: ['need'] }), // keys.need(id) for every id
    qc.invalidateQueries({ queryKey: keys.needs() }),
    qc.invalidateQueries({ queryKey: keys.quadrant }),
    qc.invalidateQueries({ queryKey: keys.metrics }),
  ])
}

/** Drop a decided item from the cached inbox right away, so the card disappears before the refetch lands. */
function removeFromInbox(qc: QueryClient, id: number, kind: TriageItem['kind']) {
  qc.setQueryData<TriageList>(keys.triage, (old) =>
    old
      ? {
          ...old,
          items: kind === 'auto_link' ? old.items : old.items.filter((i) => !(i.id === id && i.kind === kind)),
          auto_linked: kind === 'auto_link' ? old.auto_linked.filter((i) => i.id !== id) : old.auto_linked,
        }
      : old,
  )
}

/** Accept (suggestion: link; audit: correct; claim: confirm) or reject (keep separate; false merge; reject). */
export function useDecide() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ item, verb }: { item: TriageItem; verb: 'accept' | 'reject' }) => {
      const params = { path: { suggestion_id: item.id } }
      const body = { by: PM_NAME }
      return verb === 'accept'
        ? unwrap(await api.POST('/triage/{suggestion_id}/accept', { params, body }))
        : unwrap(await api.POST('/triage/{suggestion_id}/reject', { params, body }))
    },
    onSuccess: (_result, { item }) => {
      removeFromInbox(qc, item.id, item.kind)
    },
    // On a 409 (someone already decided) the refetch shows the truth.
    onSettled: () => invalidateAfterDecision(qc),
  })
}

/** Undo an auto-link: the request becomes its own need. */
export function useUnlink() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (item: TriageItem) => {
      if (!item.request) throw new Error('This item has no request to unlink.')
      return unwrap(
        await api.POST('/requests/{request_id}/unlink', {
          params: { path: { request_id: item.request.id } },
          body: { by: PM_NAME },
        }),
      )
    },
    onSuccess: (_result, item) => removeFromInbox(qc, item.id, 'auto_link'),
    onSettled: () => invalidateAfterDecision(qc),
  })
}

export function useQuadrant() {
  return useQuery({ queryKey: keys.quadrant, queryFn: async () => unwrap(await api.GET('/insights/quadrant')) })
}

/** Every need by priority; the page keeps the undecided ones. */
export function useRankedNeeds() {
  const params = { sort: 'priority' as const, page_size: 100 }
  return useQuery({
    queryKey: keys.needs({ ...params, scope: 'ranked' }),
    queryFn: async () => unwrap(await api.GET('/needs', { params: { query: params } })),
  })
}

export function useMetrics() {
  return useQuery({ queryKey: keys.metrics, queryFn: async () => unwrap(await api.GET('/metrics')) })
}

export function useNeedUpdates(needId: number) {
  return useQuery({
    queryKey: keys.needUpdates(needId),
    queryFn: async () =>
      unwrap(await api.GET('/needs/{need_id}/updates', { params: { path: { need_id: needId } } })),
    // poll while the worker is drafting, so drafts appear without a reload
    refetchInterval: (q) => (q.state.data?.changes.some((c) => c.drafts_status === 'pending') ? 1500 : false),
  })
}

export type BriefOut = Schemas['BriefOut']

const BRIEF_POLL_MS = 1500

/** The newest brief for a need, or null when there is none yet. Polls while the worker builds it. */
export function useBrief(needId: number) {
  return useQuery({
    queryKey: keys.brief(needId),
    queryFn: async (): Promise<BriefOut | null> => {
      try {
        return unwrap(await api.GET('/needs/{need_id}/brief', { params: { path: { need_id: needId } } }))
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
    refetchInterval: (q) => (q.state.data && ['pending', 'processing'].includes(q.state.data.status) ? BRIEF_POLL_MS : false),
  })
}

/** Ask for a brief. The server returns one already waiting instead of queueing a second. */
export function useAskBrief(needId: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/needs/{need_id}/brief', { params: { path: { need_id: needId } }, body: { by: PM_NAME } })),
    onSuccess: (brief) => qc.setQueryData(keys.brief(needId), brief),
  })
}
