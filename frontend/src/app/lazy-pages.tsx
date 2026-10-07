import { lazy, Suspense, type ComponentType } from 'react'

import { LoadingState } from '@/components/states'

// Code split by role: the requester portal and the PM workspace are separate chunks, loaded on first use.
const requester = () => import('@/pages/requester')
const pm = () => import('@/pages/pm')

function page<M>(load: () => Promise<M>, pick: (m: M) => ComponentType) {
  const Lazy = lazy(async () => ({ default: pick(await load()) }))
  return function Page() {
    return (
      <Suspense fallback={<LoadingState label="Loading page" />}>
        <Lazy />
      </Suspense>
    )
  }
}

export const SubmitPage = page(requester, (m) => m.SubmitPage)
export const MyRequestsPage = page(requester, (m) => m.MyRequestsPage)
export const ExplorePage = page(requester, (m) => m.ExplorePage)
export const RequesterNeedPage = page(requester, (m) => m.RequesterNeedPage)
export const TriagePage = page(pm, (m) => m.TriagePage)
export const PrioritiesPage = page(pm, (m) => m.PrioritiesPage)
export const PmNeedPage = page(pm, (m) => m.PmNeedPage)
export const OpsPage = page(pm, (m) => m.OpsPage)
