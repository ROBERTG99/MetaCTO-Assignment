import { Link, NavLink, Outlet } from 'react-router'

import { useSession } from '@/app/session'
import { RoleSwitcher } from '@/components/role-switcher'
import { cn } from '@/lib/utils'

const NAV = {
  requester: [
    { to: '/submit', label: 'Submit a request' },
    { to: '/my-requests', label: 'My requests' },
    { to: '/needs', label: 'Browse needs' },
  ],
  pm: [
    { to: '/triage', label: 'Triage inbox' },
    { to: '/priorities', label: 'Priorities' },
    { to: '/needs', label: 'Browse needs' },
  ],
} as const

export function Layout() {
  const { role } = useSession()
  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3">
          <Link to="/" className="font-heading text-lg font-semibold tracking-tight">
            Distill
          </Link>
          <nav aria-label="Main" className="flex flex-1 flex-wrap gap-1">
            {NAV[role].map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
                    isActive && 'bg-muted font-medium text-foreground',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <RoleSwitcher />
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}
