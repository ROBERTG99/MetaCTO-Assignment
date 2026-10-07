// Who is using the app. There is no auth (spec A3): a switcher picks the role and, for requesters, the person.
// Kept in localStorage as a convenience; the app works the same when storage is unavailable.
import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'

export type Role = 'requester' | 'pm'
type Session = { role: Role; requesterId: number | null }
type SessionApi = Session & { setRole: (r: Role) => void; setRequesterId: (id: number | null) => void }

const KEY = 'distill.session'
const SessionContext = createContext<SessionApi | null>(null)

function load(): Session {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (raw) {
      const s = JSON.parse(raw) as Partial<Session>
      if (s.role === 'pm' || s.role === 'requester')
        return { role: s.role, requesterId: typeof s.requesterId === 'number' ? s.requesterId : null }
    }
  } catch {
    // storage blocked or corrupt: start fresh
  }
  return { role: 'requester', requesterId: null }
}

function save(s: Session) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    // not persisted; the session still works for this tab
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session>(load)
  const value = useMemo<SessionApi>(() => {
    const update = (change: Partial<Session>) =>
      setSession((prev) => {
        const next = { ...prev, ...change }
        save(next)
        return next
      })
    return {
      ...session,
      setRole: (role) => update({ role }),
      setRequesterId: (requesterId) => update({ requesterId }),
    }
  }, [session])
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionApi {
  const s = useContext(SessionContext)
  if (!s) throw new Error('useSession outside SessionProvider')
  return s
}
