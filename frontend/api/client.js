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

const mockQueryResponse = {
  query_id: 0,
  status: 'ANSWERED',
  final_answer:
    'Network security protects networks, devices, and data from unauthorized access [1]. It relies on authentication, access control, encryption, and monitoring [2].',
  attempts: [
    {
      attempt_number: 1,
      citations: [1, 2],
      retrieval: [
        {
          rank: 1,
          chunk_id: 1,
          document_id: 'doc-002',
          filename: 'Network Security Fundamentals.pdf',
          page_number: 12,
          similarity: 0.92,
          content:
            'Network security involves policies, practices, and technologies designed to protect computer networks, devices, and data from unauthorized access, misuse, modification, or disruption.',
        },
        {
          rank: 2,
          chunk_id: 2,
          document_id: 'doc-001',
          filename: 'Computer Networks.pdf',
          page_number: 28,
          similarity: 0.84,
          content:
            'Network security mechanisms include authentication, access control, encryption, and monitoring.',
        },
      ],
    },
  ],
}

async function errorMessage(response, fallback) {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join('; ')
  } catch {
    // Non-JSON error body
  }
  return `${fallback} (HTTP ${response.status})`
}

function toUiDocument(document) {
  return {
    id: document.id,
    name: document.filename,
    pages: document.total_pages,
    chunks: document.total_chunks,
    created_at: document.uploaded_at,
  }
}

async function getDocuments() {
  if (USE_MOCK) {
    return mockDocuments
  }

  const response = await fetch(`${API_BASE_URL}/documents`)

  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Failed to fetch documents'))
  }

  return (await response.json()).map(toUiDocument)
}

async function uploadDocument(file) {
  if (USE_MOCK) {
    return { id: `mock-${Date.now()}`, name: file.name, pages: null, chunks: null, created_at: new Date().toISOString() }
  }

  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE_URL}/documents/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Failed to upload document'))
  }

  return toUiDocument(await response.json())
}

async function deleteDocument(documentId) {
  if (USE_MOCK) {
    return { id: documentId, deleted: true }
  }

  const response = await fetch(`${API_BASE_URL}/documents/${documentId}`, {
    method: 'DELETE',
  })

  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Failed to delete document'))
  }

  return response.json()
}

async function runQuery({ question, documentIds }) {
  if (USE_MOCK) {
    await new Promise((resolve) => setTimeout(resolve, 1200))
    return mockQueryResponse
  }

  const response = await fetch(`${API_BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, document_ids: documentIds }),
  })

  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Query failed'))
  }

  return response.json()
}

export { getDocuments, uploadDocument, deleteDocument, runQuery }
