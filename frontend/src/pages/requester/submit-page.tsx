import { CheckCircle2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import { useSession } from '@/app/session'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { LoadingState } from '@/components/states'

import { useDebounced, useSimilarNeeds, useSubmitRequest } from './hooks'
import { NeedMeta } from './need-parts'
import { SupportDialog } from './support-dialog'

type Added = { id: number; title: string }

export function SubmitPage() {
  const { requesterId } = useSession()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [supporting, setSupporting] = useState<Added | null>(null)
  const [added, setAdded] = useState<Added | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const submit = useSubmitRequest(requesterId)

  const query = useDebounced(`${title} ${description}`.trim(), 300)
  const similar = useSimilarNeeds(query)
  const showMatches = query.length >= 3 && title.trim().length + description.trim().length >= 3

  const reason = requesterId == null ? 'Choose who you are in "Acting as" (top right) to submit.' : !title.trim() ? 'Give your request a title.' : null

  function reset() {
    setTitle('')
    setDescription('')
  }

  return (
    <div>
      <PageHeader
        title="Submit a request"
        description="Tell us what you need. While you type, we show existing needs that may already cover it, so you can add your support instead of filing a duplicate."
      />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault()
              if (reason) return
              submit.mutate(
                { title: title.trim(), description: description.trim() },
                {
                  onSuccess: () => {
                    toast.success('Request submitted')
                    setSubmitted(true)
                    setAdded(null)
                    reset()
                  },
                },
              )
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="request-title">Title</Label>
              <Input id="request-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} autoComplete="off" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="request-description">Description</Label>
              <Textarea id="request-description" value={description} onChange={(e) => setDescription(e.target.value)} rows={6} />
            </div>
            {submit.isError && (
              <p role="alert" className="text-sm text-destructive">
                {submit.error instanceof ApiError || submit.error instanceof Error ? submit.error.message : 'Could not submit the request.'}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={reason != null || submit.isPending}>
                {submit.isPending ? 'Submitting…' : 'Submit as a new request'}
              </Button>
              {reason && <span className="text-sm text-muted-foreground">{reason}</span>}
            </div>
          </form>

          {added && (
            <Card className="p-4" data-testid="support-confirmation" role="status">
              <div className="flex items-start gap-3">
                <CheckCircle2 aria-hidden className="mt-0.5 size-5 text-muted-foreground" />
                <div className="space-y-1">
                  <p className="font-medium">Support added</p>
                  <p className="text-sm text-muted-foreground">{added.title}</p>
                  <p className="text-sm text-muted-foreground">We check your reason against the need; its status shows on the need page.</p>
                  <Link to={`/needs/${added.id}`} className="inline-block text-sm font-medium underline underline-offset-4">
                    View need
                  </Link>
                </div>
              </div>
            </Card>
          )}

          {submitted && (
            <Card className="p-4" role="status">
              <div className="flex items-start gap-3">
                <CheckCircle2 aria-hidden className="mt-0.5 size-5 text-muted-foreground" />
                <div className="space-y-1">
                  <p className="font-medium">Request submitted</p>
                  <p className="text-sm text-muted-foreground">It is saved. We work out which need it belongs to in the background.</p>
                  <Link to="/my-requests" className="inline-block text-sm font-medium underline underline-offset-4">
                    Track its progress
                  </Link>
                </div>
              </div>
            </Card>
          )}
        </div>

        <section aria-labelledby="matches-heading" className="space-y-3">
          <div className="space-y-1">
            <h2 id="matches-heading" className="font-heading text-base font-medium">
              Is this your need?
            </h2>
            <p className="text-sm text-muted-foreground">Closest existing needs, matched by meaning (embeddings, no model call).</p>
          </div>
          {!showMatches && <p className="text-sm text-muted-foreground">Start typing a title or description to see matching needs.</p>}
          {showMatches && similar.isPending && <LoadingState rows={2} label="Looking for similar needs" />}
          {showMatches && similar.isError && (
            <p role="alert" className="text-sm text-destructive">
              Couldn't look for similar needs{similar.error instanceof ApiError ? `: ${similar.error.message}` : ''}. You can still submit.
            </p>
          )}
          {showMatches && similar.data && similar.data.length === 0 && (
            <p className="text-sm text-muted-foreground">Nothing close yet. Submit it as a new request.</p>
          )}
          {showMatches && similar.data && similar.data.length > 0 && (
            <ul aria-label="Existing needs that may match" className="space-y-3">
              {similar.data.map((n) => (
                <li key={n.need_id}>
                  <Card className="gap-2 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="font-medium">{n.title}</p>
                      <Badge variant="secondary" className="tabular-nums" data-testid={`match-score-${n.need_id}`}>
                        similarity {n.score.toFixed(2)}
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">{n.problem}</p>
                    <NeedMeta persona={n.persona} productArea={n.product_area}>
                      <StatusBadge status={n.status} kind="need" />
                    </NeedMeta>
                    <div>
                      <Button type="button" variant="outline" size="sm" onClick={() => setSupporting({ id: n.need_id, title: n.title })}>
                        This is my need
                      </Button>
                    </div>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <SupportDialog
        need={supporting}
        onOpenChange={(open) => !open && setSupporting(null)}
        onAdded={(need) => {
          setSupporting(null)
          setAdded(need)
          setSubmitted(false)
          reset()
        }}
      />
    </div>
  )
}
