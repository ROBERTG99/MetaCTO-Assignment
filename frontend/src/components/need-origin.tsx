import type { Schemas } from '@/api/client'
import { AIBadge } from '@/components/ai-badge'

/** How a need was created, the same on the requester's and the PM's need page (testId "need-source"). */
export function NeedOrigin({ origin }: { origin: Schemas['NeedOrigin'] }) {
  if (origin.source || origin.created_by === 'ai') {
    const version = origin.source?.prompt_version
    return (
      <AIBadge
        source={origin.source?.model ?? null}
        why={origin.rationale}
        detail={version ? `prompt ${version}` : null}
        testId="need-source"
      />
    )
  }
  return (
    <span className="text-sm text-muted-foreground" data-testid="need-source">
      {origin.created_by === 'seed' ? 'Seed data' : 'Created by PM'}
    </span>
  )
}
