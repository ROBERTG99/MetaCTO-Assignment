// "Add your support": why it matters + a severity. Used from the Submit page and the need page.
import { useState } from 'react'

import { useSession } from '@/app/session'
import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { SEVERITY } from '@/lib/labels'

import { useAddSupport, type Severity } from './hooks'

const SEVERITIES: Severity[] = ['nice_to_have', 'important', 'blocker']

type Props = {
  need: { id: number; title: string } | null
  onOpenChange: (open: boolean) => void
  /** Called after the support is saved, with the need it was for. */
  onAdded: (need: { id: number; title: string }) => void
}

export function SupportDialog({ need, onOpenChange, onAdded }: Props) {
  return (
    <Dialog open={need != null} onOpenChange={onOpenChange}>
      <DialogContent>{need && <SupportForm key={need.id} need={need} onAdded={onAdded} />}</DialogContent>
    </Dialog>
  )
}

function SupportForm({ need, onAdded }: { need: { id: number; title: string }; onAdded: Props['onAdded'] }) {
  const { requesterId } = useSession()
  const add = useAddSupport(requesterId)
  const [why, setWhy] = useState('')
  const [severity, setSeverity] = useState<Severity>('important')
  const error = add.error instanceof ApiError || add.error instanceof Error ? add.error.message : null
  const reason = requesterId == null ? 'Choose who you are in "Acting as" (top right) first.' : !why.trim() ? 'Say why it matters to you.' : null

  return (
    <form
      className="grid gap-4"
      onSubmit={(e) => {
        e.preventDefault()
        if (reason) return
        add.mutate({ needId: need.id, whyItMatters: why.trim(), severity }, { onSuccess: () => onAdded(need) })
      }}
    >
      <DialogHeader>
        <DialogTitle>Add your support</DialogTitle>
        <DialogDescription>{need.title}</DialogDescription>
      </DialogHeader>
      <div className="space-y-2">
        <Label htmlFor="support-why">Why it matters to you</Label>
        <Textarea id="support-why" required value={why} onChange={(e) => setWhy(e.target.value)} rows={4} />
      </div>
      <div className="space-y-2">
        <Label htmlFor="support-severity">How much does it hurt?</Label>
        <Select value={severity} onValueChange={(v) => setSeverity(v as Severity)}>
          <SelectTrigger id="support-severity" aria-label="Severity" className="w-48">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SEVERITIES.map((s) => (
              <SelectItem key={s} value={s}>
                {SEVERITY[s]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <DialogFooter className="items-center">
        {reason && <span className="text-xs text-muted-foreground sm:mr-auto">{reason}</span>}
        <Button type="submit" disabled={reason != null || add.isPending}>
          {add.isPending ? 'Adding…' : 'Add support'}
        </Button>
      </DialogFooter>
    </form>
  )
}
