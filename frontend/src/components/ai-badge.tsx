// Every AI-generated value shows its source, its confidence and why (CLAUDE.md rule 6).
import { Info, Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { sourceLabel } from '@/lib/labels'
import { cn } from '@/lib/utils'

type AIBadgeProps = {
  /** Model id or "offline-baseline"; shown as a short label. */
  source: string | null | undefined
  /** 0-1, from the model or the routing score; omitted when there is none. */
  confidence?: number | null
  /** What the number is: a model's confidence, or (offline baseline) an embedding similarity. */
  confidenceLabel?: 'confidence' | 'similarity'
  /** One or two sentences: why the AI produced this value. */
  why?: string | null
  /** Shown under the reason, e.g. the prompt version or the run id. */
  detail?: string | null
  className?: string
  /** Each AI value on a page gets its own id (routing-badge, need-source, ...) so specs can address it. */
  testId?: string
}

export function AIBadge({ source, confidence, confidenceLabel = 'confidence', why, detail, className, testId = 'ai-badge' }: AIBadgeProps) {
  const label = sourceLabel(source)
  const pct =
    confidence == null ? null : confidenceLabel === 'similarity' ? confidence.toFixed(2) : `${Math.round(confidence * 100)}%`
  return (
    <span className={cn('inline-flex items-center gap-1', className)} data-testid={testId}>
      <Badge variant="secondary" className="gap-1 font-normal">
        <Sparkles aria-hidden className="size-3" />
        <span>{label}</span>
        {pct && (
          <span className="text-muted-foreground tabular-nums">
            · <span className="sr-only">{confidenceLabel} </span>
            {confidenceLabel === 'similarity' ? `similarity ${pct}` : pct}
          </span>
        )}
      </Badge>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={`Why? (${label})`}
            className="inline-flex items-center gap-0.5 rounded-sm text-xs text-muted-foreground underline-offset-2 hover:underline focus-visible:outline-2"
          >
            <Info aria-hidden className="size-3" />
            why
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-left">
          <p>{why || 'No reason was recorded for this value.'}</p>
          <p className="mt-1 opacity-70">
            Source: {label}
            {pct ? ` · ${confidenceLabel} ${pct}` : ''}
            {detail ? ` · ${detail}` : ''}
          </p>
        </TooltipContent>
      </Tooltip>
    </span>
  )
}
