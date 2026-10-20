import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { API_BASE_URL, USE_MOCK } from '../../api/client'

const navigationItems = [
  {
    to: '/documents',
    label: 'Documents',
    icon: '▤',
    description: 'Knowledge base',
  },
  {
    to: '/ask',
    label: 'Ask',
    icon: '✳',
    description: 'Query your documents',
  },
  {
    to: '/evaluation',
    label: 'Evaluation',
    icon: '✓',
    description: 'Assess answer quality',
  },
  {
    to: '/comparison',
    label: 'Comparison Lab',
    icon: '⇄',
    description: 'Compare RAG results',
  },
  {
    to: '/correction-demo',
    label: 'Correction Demo',
    icon: '⟳',
    description: 'Explore the correction flow',
  },
  {
    to: '/analytics',
    label: 'Analytics',
    icon: '▥',
    description: 'Performance insights',
  },
]

function AppShell() {
  const [backendStatus, setBackendStatus] = useState(
    USE_MOCK ? 'mock' : 'checking'
  )

  // Check the actual backend health endpoint.
  useEffect(() => {
    // The status starts as 'mock' in mock mode, so there is nothing to check.
    if (USE_MOCK) return

    let isMounted = true
    let isChecking = false
    let controller

    const checkBackend = async () => {
      if (isChecking) return

      isChecking = true
      controller = new AbortController()

      const timeoutId = setTimeout(() => {
        controller?.abort()
      }, 5000)

      try {
        const baseUrl = API_BASE_URL.replace(/\/+$/, '')
        const response = await fetch(`${baseUrl}/health`, {
          method: 'GET',
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error('Backend health check failed')
        }

        const data = await response.json()

        if (data?.status !== 'ok') {
          throw new Error('Unexpected backend health response')
        }

        if (isMounted) {
          setBackendStatus('online')
        }
      } catch {
        if (isMounted) {
          setBackendStatus('offline')
        }
      } finally {
        clearTimeout(timeoutId)
        isChecking = false
      }
    }

    checkBackend()

    // Refresh the status every 15 seconds.
    const intervalId = setInterval(checkBackend, 15000)

    return () => {
      isMounted = false
      clearInterval(intervalId)
      controller?.abort()
    }
  }, [])

  const statusConfig = {
    online: {
      label: 'System Online',
      detail: 'Backend connected successfully',
      dot: 'bg-emerald-500',
      badge: 'border-emerald-200 bg-emerald-50 text-emerald-700',
    },
    offline: {
      label: 'System Offline',
      detail: 'Backend unavailable',
      dot: 'bg-rose-500',
      badge: 'border-rose-200 bg-rose-50 text-rose-700',
    },
    checking: {
      label: 'Connecting...',
      detail: 'Checking backend connection',
      dot: 'bg-amber-500 animate-pulse',
      badge: 'border-amber-200 bg-amber-50 text-amber-700',
    },
    mock: {
      label: 'Mock Mode Active',
      detail: 'Using mock responses',
      dot: 'bg-amber-500',
      badge: 'border-amber-200 bg-amber-50 text-amber-700',
    },
  }

  const status = statusConfig[backendStatus]

  return (
    <div className="min-h-screen bg-[var(--color-background)] text-[var(--text)]">
      {/* Pastel-filled sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 flex w-64 flex-col overflow-hidden border-r border-[#D8C9E2] bg-[#E9E1F0]">
        {/* Decorative pastel accents */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-[#DB88A4]/20 blur-2xl"
        />

        <div
          aria-hidden="true"
          className="pointer-events-none absolute -bottom-12 -left-12 h-40 w-40 rounded-full bg-[#A8C3D4]/40 blur-2xl"
        />

        {/* Brand */}
        <div className="relative border-b border-[#D4C5DF] px-5 py-6">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-2xl shadow-md shadow-[#55416F]/20">
              <img
                src="/Attest_Project.jpg"
                alt="Attest logo"
                className="h-full w-full object-contain"
              />
            </div>

            <div className="min-w-0">
              <h1 className="text-xl font-bold tracking-tight text-[#443453]">
                Attest
              </h1>

              <p className="mt-0.5 text-xs text-[#796A87]">
                Reliability Evaluation
              </p>
            </div>
          </div>

          {/* Workspace card */}
          <div className="mt-5 rounded-2xl border border-white/70 bg-white/55 px-3.5 py-3 shadow-sm backdrop-blur-sm">
            <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-[#8976A7]">
              Workspace
            </p>

            <p className="mt-1 text-sm font-semibold text-[#443453]">
              RAG Evaluation Studio
            </p>

            <div className="mt-3 flex gap-1.5">
              <span className="h-1.5 w-8 rounded-full bg-[#55416F]" />
              <span className="h-1.5 w-5 rounded-full bg-[#738FBD]" />
              <span className="h-1.5 w-4 rounded-full bg-[#DB88A4]" />
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav
          aria-label="Main navigation"
          className="relative flex-1 space-y-1 overflow-y-auto px-3 py-5"
        >
          <p className="mb-3 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-[#8976A7]">
            Navigate
          </p>

          {navigationItems.map((item, index) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/evaluation'}
              className={({ isActive }) =>
                [
                  'group flex items-center gap-3 rounded-xl border px-3 py-3 transition-all duration-200',
                  isActive
                    ? 'border-[#55416F] bg-[#55416F] !text-white shadow-md shadow-[#55416F]/15'
                    : 'border-transparent text-[#514461] hover:border-white/80 hover:bg-white/65',
                ].join(' ')
              }
            >
              {({ isActive }) => (
                <>
                  {/* Navigation icon */}
                  <span
                    className={[
                      'flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-lg transition-all duration-200',
                      isActive
                        ? 'bg-white/15 !text-white'
                        : [
                            'text-[#55416F]',
                            index % 3 === 0
                              ? 'bg-[#D5E3EF]'
                              : index % 3 === 1
                                ? 'bg-[#F2DCE5]'
                                : 'bg-[#DCD2E8]',
                            'group-hover:scale-105',
                          ].join(' '),
                    ].join(' ')}
                    aria-hidden="true"
                  >
                    {item.icon}
                  </span>

                  {/* Navigation title and description */}
                  <span className="min-w-0 flex-1">
                    <span
                      className={[
                        'block text-sm font-semibold',
                        isActive ? '!text-white' : 'text-[#514461]',
                      ].join(' ')}
                    >
                      {item.label}
                    </span>

                    <span
                      className={[
                        'mt-0.5 block text-[11px]',
                        isActive
                          ? '!text-white/80'
                          : 'text-[#81738E]',
                      ].join(' ')}
                    >
                      {item.description}
                    </span>
                  </span>

                  {/* Active indicator */}
                  {isActive && (
                    <span
                      className="h-2 w-2 shrink-0 rounded-full bg-[#F2A9C1] ring-2 ring-white/15"
                      aria-hidden="true"
                    />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        {/* Dynamic backend status */}
        <div className="relative border-t border-[#D4C5DF] p-4">
          <div className="rounded-2xl border border-white/80 bg-white/60 p-3.5 shadow-sm backdrop-blur-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-bold text-[#443453]">
                System Status
              </span>

              <span
                className={[
                  'inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-[10px] font-semibold',
                  status.badge,
                ].join(' ')}
                role="status"
                aria-live="polite"
              >
                <span
                  className={[
                    'h-1.5 w-1.5 rounded-full',
                    status.dot,
                  ].join(' ')}
                  aria-hidden="true"
                />

                {status.label}
              </span>
            </div>

            <p className="mt-2 text-[11px] text-[#796A87]">
              {status.detail}
            </p>

            <p className="mt-1 break-all text-[10px] text-[#8976A7]">
              {USE_MOCK ? 'Mock API' : API_BASE_URL}
            </p>
          </div>

          <p className="mt-3 text-center text-[10px] font-medium text-[#8976A7]">
            Attest · Evaluation Workspace
          </p>
        </div>
      </aside>

      {/* Main content — unchanged */}
      <main className="min-h-screen min-w-0 bg-[var(--color-background)] p-4 sm:p-6 lg:ml-64 lg:p-8">
        <div className="mx-auto w-full max-w-[1600px]">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

export default AppShell