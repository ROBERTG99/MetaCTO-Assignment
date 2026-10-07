// Shared queries (TanStack Query). Keys are arrays starting with the resource name.
import { useQuery } from '@tanstack/react-query'

import { api, unwrap } from '@/api/client'

export function useRequesters() {
  return useQuery({ queryKey: ['requesters'], queryFn: async () => unwrap(await api.GET('/requesters')) })
}
