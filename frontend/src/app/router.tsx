import { createBrowserRouter, Navigate } from 'react-router'

import { Layout } from '@/app/layout'
import { useSession } from '@/app/session'
import { NotBuilt } from '@/pages/not-built'
import { OpsPage, PmNeedPage, PrioritiesPage, TriagePage } from '@/pages/pm'
import { ExplorePage, MyRequestsPage, RequesterNeedPage, SubmitPage } from '@/pages/requester'

function Home() {
  const { role } = useSession()
  return <Navigate to={role === 'pm' ? '/triage' : '/submit'} replace />
}

/** One URL per need; what it shows depends on who is looking. */
function NeedRoute() {
  const { role } = useSession()
  return role === 'pm' ? <PmNeedPage /> : <RequesterNeedPage />
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { index: true, element: <Home /> },
      // Requester portal (src/pages/requester)
      { path: 'submit', element: <SubmitPage /> },
      { path: 'my-requests', element: <MyRequestsPage /> },
      { path: 'needs', element: <ExplorePage /> }, // shared by both roles
      { path: 'needs/:needId', element: <NeedRoute /> },
      // PM workspace (src/pages/pm)
      { path: 'triage', element: <TriagePage /> },
      { path: 'priorities', element: <PrioritiesPage /> },
      { path: 'ops', element: <OpsPage /> },
      { path: '*', element: <NotBuilt /> },
    ],
  },
])
