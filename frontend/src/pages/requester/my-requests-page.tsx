import { Link } from 'react-router'

import { useSession } from '@/app/session'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { when } from '@/lib/labels'

import { useMyRequests, useNow } from './hooks'
import { progress } from './progress'

export function MyRequestsPage() {
  const { requesterId } = useSession()
  const requests = useMyRequests(requesterId)
  const now = useNow()
  const stuck = progress(requests.data ?? [], now).stuck

  return (
    <div>
      <PageHeader title="My requests" description="What you have submitted, where it stands, and the need it was linked to." />
      {requesterId == null ? (
        <EmptyState title="Choose who you are" description={'Pick your name in the "Acting as" switcher (top right) to see your requests.'} />
      ) : requests.isPending ? (
        <LoadingState label="Loading your requests" />
      ) : requests.isError ? (
        <ErrorState error={requests.error} onRetry={() => void requests.refetch()} />
      ) : (
        <Table aria-label="My requests">
          <TableHeader>
            <TableRow>
              <TableHead>Request</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Need</TableHead>
              <TableHead>Submitted</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {requests.data.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} className="py-8 text-center text-muted-foreground">
                  No requests yet. Submit one from "Submit a request".
                </TableCell>
              </TableRow>
            )}
            {requests.data.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="max-w-sm whitespace-normal">
                  <p className="font-medium">{r.title}</p>
                  {r.description && <p className="line-clamp-2 text-xs text-muted-foreground">{r.description}</p>}
                </TableCell>
                <TableCell className="whitespace-normal">
                  <div className="space-y-1">
                    {stuck.has(r.id) ? (
                      <>
                        <Badge variant="destructive" data-testid="request-status">
                          Stuck
                        </Badge>
                        <p className="max-w-xs text-xs text-muted-foreground">
                          This is taking longer than it should. The product team can see it in their queue.{' '}
                          <button type="button" className="underline underline-offset-2" onClick={() => void requests.refetch()}>
                            Check again
                          </button>
                        </p>
                      </>
                    ) : (
                      <StatusBadge status={r.status} kind="request" testId="request-status" />
                    )}
                    {r.needs_review_reason && <p className="max-w-xs text-xs text-muted-foreground">{r.needs_review_reason}</p>}
                  </div>
                </TableCell>
                <TableCell className="max-w-sm whitespace-normal">
                  {r.need ? (
                    <Link to={`/needs/${r.need.id}`} data-testid="need-link" className="underline underline-offset-4">
                      {r.need.title}
                    </Link>
                  ) : (
                    <span className="text-muted-foreground">Not linked yet</span>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap text-muted-foreground">{when(r.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
