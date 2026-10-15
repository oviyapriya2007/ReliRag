const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export { USE_MOCK, API_BASE_URL }

// Used only when VITE_USE_MOCK=true.
// Keep VITE_USE_MOCK=false for real backend data.
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

    if (typeof body.detail === 'string') {
      return body.detail
    }

    if (Array.isArray(body.detail)) {
      return body.detail.map((item) => item.msg).join('; ')
    }
  } catch {
    // The response body was not JSON.
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
    throw new Error(
      await errorMessage(response, 'Failed to fetch documents'),
    )
  }

  return (await response.json()).map(toUiDocument)
}

async function uploadDocument(file) {
  if (USE_MOCK) {
    return {
      id: `mock-${Date.now()}`,
      name: file.name,
      pages: null,
      chunks: null,
      created_at: new Date().toISOString(),
    }
  }

  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_BASE_URL}/documents/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(
      await errorMessage(response, 'Failed to upload document'),
    )
  }

  return toUiDocument(await response.json())
}

async function deleteDocument(documentId) {
  if (USE_MOCK) {
    return { id: documentId, deleted: true }
  }

  const response = await fetch(
    `${API_BASE_URL}/documents/${documentId}`,
    {
      method: 'DELETE',
    },
  )

  if (!response.ok) {
    throw new Error(
      await errorMessage(response, 'Failed to delete document'),
    )
  }

  return response.json()
}

async function runQuery({
  question,
  documentIds,
  mode = 'basic',
  k = 5,
}) {
  if (USE_MOCK) {
    await new Promise((resolve) => setTimeout(resolve, 1200))
    return mockQueryResponse
  }

  const response = await fetch(`${API_BASE_URL}/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question,
      mode,
      k,
      document_ids: documentIds,
    }),
  })

  if (!response.ok) {
    throw new Error(
      await errorMessage(response, 'Query failed'),
    )
  }

  return response.json()
}

// Fetch a previously executed query and its real evaluation results.
async function getQuery(queryId) {
  if (USE_MOCK) {
    throw new Error(
      'Query history is unavailable in mock mode.',
    )
  }

  const response = await fetch(
    `${API_BASE_URL}/query/${encodeURIComponent(queryId)}`,
  )

  if (!response.ok) {
    throw new Error(
      await errorMessage(response, 'Failed to fetch query'),
    )
  }

  return response.json()
}

// Compare Basic RAG and RELI-RAG using the live backend.
async function compareAnswers({
  question,
  documentIds,
  k = 5,
}) {
  if (USE_MOCK) {
    throw new Error(
      'Live comparison requires mock mode to be disabled.',
    )
  }

  const response = await fetch(`${API_BASE_URL}/compare`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      question,
      k,
      document_ids: documentIds?.length ? documentIds : null,
    }),
  })

  if (!response.ok) {
    throw new Error(
      await errorMessage(response, 'Comparison failed'),
    )
  }

  return response.json()
}

// Fetch real analytics summary from the backend.
async function getAnalyticsSummary({
  benchmarkRunId,
  topDocuments = 5,
} = {}) {
  if (USE_MOCK) {
    throw new Error(
      'Live analytics requires mock mode to be disabled.',
    )
  }

  const params = new URLSearchParams()
  params.set('top_documents', String(topDocuments))

  if (benchmarkRunId?.trim()) {
    params.set('benchmark_run_id', benchmarkRunId.trim())
  }

  const response = await fetch(
    `${API_BASE_URL}/analytics/summary?${params.toString()}`,
  )

  if (!response.ok) {
    throw new Error(
      await errorMessage(response, 'Failed to fetch analytics'),
    )
  }

  return response.json()
}

export {
  getDocuments,
  uploadDocument,
  deleteDocument,
  runQuery,
  getQuery,
  compareAnswers,
  getAnalyticsSummary,
}