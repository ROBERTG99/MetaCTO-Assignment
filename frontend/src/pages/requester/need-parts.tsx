// Small pieces the requester pages share: how a need is described, and the labels for its filters.
import type { ReactNode } from 'react'

import { humanize } from '@/lib/labels'

/** Persona and product area as one muted line. */
export function NeedMeta({ persona, productArea, children }: { persona: string | null; productArea: string | null; children?: ReactNode }) {
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span>
        Persona: <span className="text-foreground">{humanize(persona)}</span>
      </span>
      <span>
        Area: <span className="text-foreground">{humanize(productArea)}</span>
      </span>
      {children}
    </p>
  )
}
