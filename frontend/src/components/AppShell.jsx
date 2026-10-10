import { NavLink, Outlet } from 'react-router-dom'
import { USE_MOCK } from '../../api/client'

function AppShell() {
  return (
    <div className="min-h-screen bg-[var(--color-background)] text-gray-900">
      <aside className="fixed left-0 top-0 h-screen w-64 bg-[var(--color-primary)] text-white">
        <div className="p-6">
          <h1 className="text-2xl font-bold">RELI-RAG</h1>
          <p className="mt-1 text-sm opacity-80">
            RAG Reliability Evaluation
          </p>
        </div>

        <nav className="flex flex-col gap-2 px-4">
    <NavLink
        to="/documents"
        className={({ isActive }) =>
    `   rounded-lg px-4 py-3 transition ${
        isActive
            ? 'bg-white/20 font-semibold'
            : 'hover:bg-white/10'
        }`
    }
    >
  Documents
</NavLink>

  <NavLink
    to="/ask"
    className="rounded-lg px-4 py-3 transition hover:bg-white/10"
  >
    Ask
  </NavLink>

  <NavLink
    to="/evaluation"
    className="rounded-lg px-4 py-3 transition hover:bg-white/10"
  >
    Evaluation
  </NavLink>

  <NavLink
    to="/comparison"
    className="rounded-lg px-4 py-3 transition hover:bg-white/10"
  >
    Comparison Lab
  </NavLink>

  <NavLink
    to="/analytics"
    className="rounded-lg px-4 py-3 transition hover:bg-white/10"
  >
    Analytics
  </NavLink>
</nav>

        <div className="absolute bottom-8 left-6 right-6 text-sm">
        <div className="font-medium">● System Status</div>
        <div className="mt-1 ml-4 opacity-70">{USE_MOCK ? 'Mock API' : 'Live API'}</div>
        </div>
      </aside>

      <main className="ml-64 min-h-screen bg-[var(--color-background)] p-6 text-gray-900">
        <Outlet />
      </main>
    </div>
  )
}

export default AppShell