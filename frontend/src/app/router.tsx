import { createBrowserRouter, Navigate } from 'react-router'

import { Layout } from '@/app/layout'
import { useSession } from '@/app/session'
import { NotBuilt } from '@/pages/not-built'

function Home() {
  const { role } = useSession()
  return <Navigate to={role === 'pm' ? '/triage' : '/submit'} replace />
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { index: true, element: <Home /> },
      // Specified by frontend/e2e; built next: submit, my-requests, needs, triage, priorities.
      { path: '*', element: <NotBuilt /> },
    ],
  },
])
