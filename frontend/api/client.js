const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export { USE_MOCK, API_BASE_URL }
const mockDocuments = [
  {
    id: 'doc-001',
    name: 'Computer Networks.pdf',
    pages: 72,
    chunks: 184,
    created_at: '2026-10-05T10:00:00Z',
  },
  {
    id: 'doc-002',
    name: 'Network Security Fundamentals.pdf',
    pages: 58,
    chunks: 143,
    created_at: '2026-10-04T14:30:00Z',
  },
]

async function getDocuments() {
  if (USE_MOCK) {
    return mockDocuments
  }

  const response = await fetch(`${API_BASE_URL}/documents`)

  if (!response.ok) {
    throw new Error('Failed to fetch documents')
  }

  return response.json()
}

export { getDocuments }