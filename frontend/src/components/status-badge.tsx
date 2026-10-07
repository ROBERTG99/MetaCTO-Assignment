import { Badge } from '@/components/ui/badge'
import { NEED_STATUS, REQUEST_STATUS } from '@/lib/labels'

const TONE: Record<string, 'default' | 'secondary' | 'outline' | 'destructive'> = {
  pending: 'outline',
  processing: 'outline',
  processed: 'secondary',
  needs_review: 'destructive',
  open: 'outline',
  planned: 'default',
  in_progress: 'default',
  shipped: 'secondary',
  declined: 'outline',
  merged: 'outline',
}

/** A request's or a need's status, with the shared wording. */
export function StatusBadge({ status, kind, testId }: { status: string; kind: 'request' | 'need'; testId?: string }) {
  const label = (kind === 'request' ? REQUEST_STATUS : NEED_STATUS)[status] ?? status
  return (
    <Badge variant={TONE[status] ?? 'outline'} data-testid={testId}>
      {label}
    </Badge>
  )
}
