// The three states every page handles (.claude/rules/frontend.md): loading, empty, error. Use these, not ad-hoc text.
import { AlertTriangle, Inbox } from 'lucide-react'
import type { ReactNode } from 'react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

export function LoadingState({ rows = 3, label = 'Loading' }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  )
}

export function EmptyState({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center" data-testid="empty-state">
      <Inbox aria-hidden className="size-6 text-muted-foreground" />
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : 'Something went wrong talking to the API.'
  return (
    <div role="alert" className="flex flex-col items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/5 px-6 py-8 text-center">
      <AlertTriangle aria-hidden className="size-6 text-destructive" />
      <p className="font-medium">Couldn't load this</p>
      <p className="max-w-md text-sm text-muted-foreground">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}
