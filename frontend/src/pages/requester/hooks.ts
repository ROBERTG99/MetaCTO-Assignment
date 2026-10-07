// Requester-portal queries and mutations. They reuse the shared `keys` so the PM half sees the same cache.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api, unwrap, type Schemas } from '@/api/client'
import { keys, useRequesters } from '@/api/queries'

import { progress } from './progress'

export type MyRequest = Schemas['MyRequest']
export type Severity = Schemas['Severity']

/** The value, once it has stopped changing for `ms`. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])
  return debounced
}

/** Nearest needs by embedding while the requester types (no model call). */
export function useSimilarNeeds(q: string) {
  return useQuery({
    queryKey: keys.similar(q),
    queryFn: async () => unwrap(await api.GET('/needs/similar', { params: { query: { q } } })),
    enabled: q.length >= 3,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

/** The signed-in requester's requests; polls while any is still being processed. */
export function useMyRequests(requesterId: number | null) {
  return useQuery({
    queryKey: keys.myRequests(requesterId ?? 0),
    queryFn: async () => unwrap(await api.GET('/requests', { params: { query: { requester_id: requesterId ?? 0 } } })),
    enabled: requesterId != null,
    // poll while something fresh is in flight; a request stuck past the timeout stops the polling (progress.ts)
    refetchInterval: (query) => (progress(query.state.data ?? [], Date.now()).poll ? 2000 : false),
  })
}

export function useSubmitRequest(requesterId: number | null) {
  const qc = useQueryClient()
  const requesters = useRequesters()
  return useMutation({
    mutationFn: async (input: { title: string; description: string }) => {
      if (requesterId == null) throw new Error('Choose who you are first.')
      // Customers file through the portal; Brightboard staff (no account) file as internal.
      const person = requesters.data?.find((p) => p.id === requesterId)
      const source = person && person.account_id == null ? 'internal' : 'portal'
      return unwrap(await api.POST('/requests', { body: { requester_id: requesterId, source, ...input } }))
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.myRequests(requesterId ?? 0) })
      void qc.invalidateQueries({ queryKey: keys.needs() })
    },
  })
}

export function useAddSupport(requesterId: number | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: { needId: number; whyItMatters: string; severity: Severity }) => {
      if (requesterId == null) throw new Error('Choose who you are first.')
      return unwrap(
        await api.POST('/needs/{need_id}/support', {
          params: { path: { need_id: input.needId } },
          body: { requester_id: requesterId, why_it_matters: input.whyItMatters, severity: input.severity },
        }),
      )
    },
    onSuccess: (_data, input) => {
      void qc.invalidateQueries({ queryKey: keys.need(input.needId) })
      void qc.invalidateQueries({ queryKey: keys.needs() })
      void qc.invalidateQueries({ queryKey: keys.myRequests(requesterId ?? 0) })
    },
  })
}

/** A need as a requester sees it (/portal): no revenue, accounts, descriptions or internal notes. */
export function usePortalNeed(needId: number, requesterId: number | null) {
  return useQuery({
    queryKey: [...keys.need(needId), 'portal', requesterId] as const,
    queryFn: async () =>
      unwrap(
        await api.GET('/portal/needs/{need_id}', {
          params: { path: { need_id: needId }, query: { requester_id: requesterId ?? undefined } },
        }),
      ),
    enabled: Number.isFinite(needId) && needId > 0,
    // an update a PM approves elsewhere shows up without a reload (same-browser approvals invalidate the key)
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
  })
}

/** The current time, refreshed every 15 s: lets a row turn "stuck" on screen even after polling stopped. */
export function useNow(everyMs = 15_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(id)
  }, [everyMs])
  return now
}
