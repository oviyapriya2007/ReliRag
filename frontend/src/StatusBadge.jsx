const statusConfig = {
  PASSED: {
    label: 'PASSED',
    color: 'var(--status-passed)',
    symbol: '✓',
  },

  CORRECTED: {
    label: 'CORRECTED',
    color: 'var(--status-corrected)',
    symbol: '↻',
  },

  FAILED_AFTER_CORRECTION: {
    label: 'FAILED_AFTER_CORRECTION',
    color: 'var(--status-failed)',
    symbol: '✕',
  },

  INSUFFICIENT_EVIDENCE: {
    label: 'INSUFFICIENT_EVIDENCE',
    color: 'var(--status-insufficient)',
    symbol: '?',
  },
}

function StatusBadge({ status }) {
  const config = statusConfig[status]

  if (!config) {
    return null
  }

  return (
    <span
      style={{
        color: config.color,
        border: `1px solid ${config.color}`,
        padding: '4px 8px',
        borderRadius: '999px',
        fontSize: '12px',
        fontWeight: '600',
      }}
    >
      {config.symbol} {config.label}
    </span>
  )
}

export default StatusBadge