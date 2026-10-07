import { useNavigate } from 'react-router'

import { useRequesters } from '@/api/queries'
import { useSession, type Role } from '@/app/session'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

/** No auth (spec A3): pick a role, and for requesters the person to act as. */
export function RoleSwitcher() {
  const { role, requesterId, setRole, setRequesterId } = useSession()
  const navigate = useNavigate()
  const requesters = useRequesters()
  return (
    <div className="flex items-center gap-2">
      <Select
        value={role}
        onValueChange={(r) => {
          setRole(r as Role)
          navigate(r === 'pm' ? '/triage' : '/submit')
        }}
      >
        <SelectTrigger aria-label="Role" className="w-44" size="sm">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="requester">Requester</SelectItem>
          <SelectItem value="pm">Product manager</SelectItem>
        </SelectContent>
      </Select>
      {role === 'requester' && requesters.isError && (
        <span role="alert" className="flex items-center gap-2 text-sm text-destructive">
          Couldn't load people.
          <button type="button" className="underline underline-offset-2" onClick={() => void requesters.refetch()}>
            Retry
          </button>
        </span>
      )}
      {role === 'requester' && requesters.data?.length === 0 && (
        <span className="text-sm text-muted-foreground">No requesters yet: run make seed.</span>
      )}
      {role === 'requester' && !requesters.isError && requesters.data?.length !== 0 && (
        <Select value={requesterId ? String(requesterId) : ''} onValueChange={(v) => setRequesterId(Number(v))}>
          <SelectTrigger aria-label="Acting as" className="w-56" size="sm">
            <SelectValue placeholder={requesters.isLoading ? 'Loading people…' : 'Choose who you are'} />
          </SelectTrigger>
          <SelectContent>
            {requesters.data?.map((p) => (
              <SelectItem key={p.id} value={String(p.id)}>
                {p.name}
                <span className="text-muted-foreground"> · {p.account_name ?? 'Brightboard staff'}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  )
}
