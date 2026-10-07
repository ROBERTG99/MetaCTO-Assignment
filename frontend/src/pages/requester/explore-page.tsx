import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import { api, unwrap, type Schemas } from '@/api/client'
import { keys } from '@/api/queries'
import { EmptyState, ErrorState, LoadingState } from '@/components/states'
import { PageHeader } from '@/components/page-header'
import { StatusBadge } from '@/components/status-badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { NEED_STATUS, humanize } from '@/lib/labels'

import { useDebounced } from './hooks'
import { SEGMENT } from './constants'
import { NeedMeta } from './need-parts'

const PAGE_SIZE = 20
const ALL = 'all'
const SORTS = { priority: 'Priority', support: 'Most support', recent: 'Recent' } as const
type Sort = keyof typeof SORTS

export function ExplorePage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState(ALL)
  const [area, setArea] = useState(ALL)
  const [segment, setSegment] = useState(ALL)
  const [sort, setSort] = useState<Sort>('priority')
  const [page, setPage] = useState(1)
  const q = useDebounced(search.trim(), 300)

  const params = {
    q: q || undefined,
    status: status === ALL ? undefined : (status as Schemas['NeedStatus']),
    product_area: area === ALL ? undefined : area,
    segment: segment === ALL ? undefined : (segment as Schemas['Segment']),
    sort,
    page,
    page_size: PAGE_SIZE,
  }
  const needs = useQuery({
    queryKey: keys.needs(params),
    queryFn: async () => unwrap(await api.GET('/portal/needs', { params: { query: params } })),
    placeholderData: keepPreviousData,
  })

  // The product areas that exist, taken from the unfiltered list (the API has no separate endpoint).
  const areaSource = useQuery({
    queryKey: keys.needs({ scope: 'product-areas' }),
    queryFn: async () => unwrap(await api.GET('/portal/needs', { params: { query: { page_size: 100 } } })),
    staleTime: 60_000,
  })
  const areas = [...new Set((areaSource.data?.items ?? []).map((n) => n.product_area).filter((a): a is string => !!a))].sort()

  const filter = <T extends string>(set: (v: T) => void) => (v: string) => {
    set(v as T)
    setPage(1)
  }
  const totalPages = needs.data ? Math.max(1, Math.ceil(needs.data.total / needs.data.page_size)) : 1

  return (
    <div className="space-y-6">
      <PageHeader title="Browse needs" description="Every need we are tracking, with how many people and accounts have asked for it." />

      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-56 flex-1 space-y-2">
          <Label htmlFor="needs-search">Search needs</Label>
          <div className="relative">
            <Search aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="needs-search"
              className="pl-8"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              autoComplete="off"
            />
          </div>
        </div>
        <FilterSelect label="Status" value={status} onChange={filter(setStatus)} allLabel="All statuses">
          {Object.entries(NEED_STATUS)
            .filter(([k]) => k !== 'merged')
            .map(([k, label]) => (
              <SelectItem key={k} value={k}>
                {label}
              </SelectItem>
            ))}
        </FilterSelect>
        <FilterSelect label="Product area" value={area} onChange={filter(setArea)} allLabel="All areas">
          {areas.map((a) => (
            <SelectItem key={a} value={a}>
              {humanize(a)}
            </SelectItem>
          ))}
        </FilterSelect>
        <FilterSelect label="Segment" value={segment} onChange={filter(setSegment)} allLabel="All segments">
          {Object.entries(SEGMENT).map(([k, label]) => (
            <SelectItem key={k} value={k}>
              {label}
            </SelectItem>
          ))}
        </FilterSelect>
        <div className="space-y-2">
          <Label htmlFor="needs-sort">Sort</Label>
          <Select value={sort} onValueChange={filter<Sort>(setSort)}>
            <SelectTrigger id="needs-sort" aria-label="Sort" className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(SORTS).map(([k, label]) => (
                <SelectItem key={k} value={k}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {needs.isPending ? (
        <LoadingState rows={4} label="Loading needs" />
      ) : needs.isError ? (
        <ErrorState error={needs.error} onRetry={() => void needs.refetch()} />
      ) : needs.data.items.length === 0 ? (
        <EmptyState title="No needs match" description="Try a different search or clear a filter." />
      ) : (
        <>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {needs.data.total} {needs.data.total === 1 ? 'need' : 'needs'}
          </p>
          <ul aria-label="Needs" className="space-y-3">
            {needs.data.items.map((n) => (
              <li key={n.id}>
                <Card className="gap-2 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <Link to={`/needs/${n.id}`} className="font-medium underline-offset-4 hover:underline">
                      {n.title}
                    </Link>
                    <StatusBadge status={n.status} kind="need" />
                  </div>
                  <p className="text-sm text-muted-foreground">{n.problem}</p>
                  <NeedMeta persona={n.persona} productArea={n.product_area}>
                    <span>
                      <span className="text-foreground">{n.support_count}</span> {n.support_count === 1 ? 'supporter' : 'supporters'}
                    </span>
                    <span>
                      <span className="text-foreground">{n.account_count}</span> {n.account_count === 1 ? 'account' : 'accounts'}
                    </span>
                  </NeedMeta>
                </Card>
              </li>
            ))}
          </ul>
          <nav aria-label="Pagination" className="flex items-center justify-between gap-3">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <span className="text-sm text-muted-foreground">
              Page {needs.data.page} of {totalPages}
            </span>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </nav>
        </>
      )}
    </div>
  )
}

function FilterSelect({
  label,
  value,
  onChange,
  allLabel,
  children,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  allLabel: string
  children: React.ReactNode
}) {
  const id = `filter-${label.toLowerCase().replace(/\s+/g, '-')}`
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} aria-label={label} className="w-44">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>{allLabel}</SelectItem>
          {children}
        </SelectContent>
      </Select>
    </div>
  )
}
