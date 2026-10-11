// Live-mode placeholder for screens whose backend data is not implemented yet.

function NotAvailable({ eyebrow, title, description }) {
  return (
    <div className="space-y-6">
      <header>
        <p className="text-sm font-medium" style={{ color: '#7080DA' }}>
          {eyebrow}
        </p>
        <h1 className="mt-1 text-3xl font-bold" style={{ color: '#554188' }}>
          {title}
        </h1>
        <p className="mt-2 text-sm text-gray-500">{description}</p>
      </header>

      <section
        role="status"
        className="rounded-2xl border border-[#E5DBE6] bg-white p-8 text-center shadow-sm"
      >
        <p className="text-lg font-semibold text-gray-700">Not available yet</p>
        <p className="mt-2 text-sm text-gray-500">
          This screen will show results once the backend provides this data.
        </p>
      </section>
    </div>
  )
}

export default NotAvailable
