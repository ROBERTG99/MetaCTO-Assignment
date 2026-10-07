import { useLocation } from 'react-router'

import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/** Placeholder for pages the golden-path specs describe but that aren't built yet (frontend/e2e/). */
export function NotBuilt() {
  const { pathname } = useLocation()
  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle>Not built yet</CardTitle>
        <CardDescription>
          <code>{pathname}</code> is specified by the end-to-end specs in <code>frontend/e2e/</code> and comes next.
        </CardDescription>
      </CardHeader>
    </Card>
  )
}
