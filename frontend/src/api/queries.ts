// Shared queries (TanStack Query). Both halves of the UI use these keys, so a mutation in one invalidates
// what the other shows. Page-specific queries and mutations live next to their pages and reuse `keys`.
import { useQuery } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from '@/api/client'

export const keys = {
  requesters: ['requesters'] as const,
  needs: (params?: object) => (params ? (['needs', params] as const) : (['needs'] as const)),
  need: (id: number) => ['need', id] as const,
  needUpdates: (id: number) => ['need-updates', id] as const,
  brief: (id: number) => ['brief', id] as const,
  similar: (q: string) => ['similar', q] as const,
  myRequests: (requesterId: number) => ['my-requests', requesterId] as const,
  triage: ['triage'] as const,
  quadrant: ['quadrant'] as const,
  metrics: ['metrics'] as const,
}

export type NeedDetail = Schemas['NeedDetail']
export type NeedSummary = Schemas['NeedSummary']

export function useRequesters() {
  return useQuery({ queryKey: keys.requesters, queryFn: async () => unwrap(await api.GET('/requesters')) })
}

export function useNeed(needId: number) {
  return useQuery({
    queryKey: keys.need(needId),
    queryFn: async () => unwrap(await api.GET('/needs/{need_id}', { params: { path: { need_id: needId } } })),
    enabled: Number.isFinite(needId) && needId > 0,
  })
}
