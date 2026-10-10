import { useEffect, useRef, useState } from 'react'
import { deleteDocument, getDocuments, uploadDocument } from '../../api/client'

function Documents() {
  const [documents, setDocuments] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [documentToDelete, setDocumentToDelete] = useState(null)
  const [busy, setBusy] = useState(false)

  const fileInputRef = useRef(null)

  // Open the file picker
  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  // Validate and select a PDF file
  const handleFileSelection = (file) => {
    if (!file) return

    const isPdf =
      file.type === 'application/pdf' ||
      file.name.toLowerCase().endsWith('.pdf')

    if (!isPdf) {
      alert('Please select a PDF file.')
      return
    }

    setSelectedFile(file)
  }

  // Handle file picker selection
  const handleFileChange = (event) => {
    handleFileSelection(event.target.files[0])
    event.target.value = ''
  }

  // Handle drag over
  const handleDragOver = (event) => {
    event.preventDefault()
  }

  // Handle dropped file
  const handleDrop = (event) => {
    event.preventDefault()
    handleFileSelection(event.dataTransfer.files[0])
  }

  const loadDocuments = () =>
    getDocuments()
      .then(setDocuments)
      .catch((error) => {
        console.error('Failed to load documents:', error)
        alert(`Failed to load documents: ${error.message}`)
      })

  // Upload, extract, chunk and embed the selected PDF
  const handleUpload = async () => {
    if (!selectedFile) {
      alert('Please select a PDF file first.')
      return
    }

    setBusy(true)
    try {
      await uploadDocument(selectedFile)
      setSelectedFile(null)
      await loadDocuments()
    } catch (error) {
      console.error('Upload failed:', error)
      alert(`Upload failed: ${error.message}`)
    } finally {
      setBusy(false)
    }
  }

  // Open delete confirmation
  const handleDeleteClick = (document) => {
    setDocumentToDelete(document)
  }

  // Delete the document and its chunks on the server
  const confirmDelete = async () => {
    if (!documentToDelete) return

    setBusy(true)
    try {
      await deleteDocument(documentToDelete.id)
      setDocuments((currentDocuments) =>
        currentDocuments.filter(
          (document) => document.id !== documentToDelete.id
        )
      )
      setDocumentToDelete(null)
    } catch (error) {
      console.error('Delete failed:', error)
      alert(`Delete failed: ${error.message}`)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    loadDocuments()
  }, [])

  return (
    <div className="mx-auto w-full max-w-6xl space-y-8">

      {/* Page Header */}
      <div>
        <h1
          className="text-3xl font-bold"
          style={{ color: '#554188' }}
        >
          Documents
        </h1>

        <p className="mt-2" style={{ color: '#555555' }}>
          Manage your knowledge documents.
        </p>
      </div>

      {/* Upload Section */}
      <section>
        <h2
          className="mb-3 text-lg font-semibold"
          style={{ color: '#554188' }}
        >
          Upload Document
        </h2>

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={handleFileChange}
        />

        <div
          onClick={handleUploadClick}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              handleUploadClick()
            }
          }}
          className="cursor-pointer rounded-2xl border-2 border-dashed p-12 text-center transition hover:bg-[#F0EAF2]"
          style={{
            borderColor: '#7080DA',
            backgroundColor: '#F5F5F4',
          }}
        >
          <div className="mx-auto max-w-md">
            <div className="mb-4 text-4xl">📄</div>

            <p
              className="text-lg font-semibold"
              style={{ color: '#554188' }}
            >
              Drop your PDF here
            </p>

            <p className="mt-2 text-sm" style={{ color: '#555555' }}>
              or click to browse
            </p>

            <p className="mt-4 text-xs" style={{ color: '#8A8080' }}>
              PDF files only · Maximum file size will be enforced by the backend
            </p>
          </div>
        </div>

        {/* Selected File Details */}
        {selectedFile && (
          <div
            className="mt-4 rounded-xl border p-5"
            style={{
              borderColor: '#A8C3D4',
              backgroundColor: '#FFFFFF',
            }}
          >
            <p className="font-semibold" style={{ color: '#554188' }}>
              Selected file
            </p>

            <p
              className="mt-1 break-all text-sm"
              style={{ color: '#555555' }}
            >
              {selectedFile.name}
            </p>

            <p className="mt-1 text-xs" style={{ color: '#888888' }}>
              {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>

            <button
              type="button"
              onClick={handleUpload}
              disabled={busy}
              className="mt-4 rounded-lg px-5 py-2 font-semibold text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              style={{ backgroundColor: '#554188' }}
            >
              {busy ? 'Uploading and indexing…' : 'Upload PDF'}
            </button>

            <button
              type="button"
              onClick={() => setSelectedFile(null)}
              disabled={busy}
              className="ml-3 mt-4 rounded-lg border px-5 py-2 font-semibold transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
              style={{
                borderColor: '#D5CEDB',
                color: '#554188',
              }}
            >
              Cancel
            </button>
          </div>
        )}
      </section>

      {/* Documents Table */}
      <section>
        <div className="mb-4">
          <h2
            className="text-lg font-semibold"
            style={{ color: '#554188' }}
          >
            Your Documents
          </h2>

          <p className="mt-1 text-sm" style={{ color: '#777777' }}>
            Documents available in your knowledge base.
          </p>
        </div>

        <div
          className="overflow-x-auto rounded-xl border bg-white"
          style={{ borderColor: '#E0DDE1' }}
        >
          <table className="w-full min-w-[650px] text-left text-sm">
            <thead style={{ backgroundColor: '#F0EAF2' }}>
              <tr style={{ color: '#554188' }}>
                <th className="px-5 py-4 font-semibold">Document</th>
                <th className="px-5 py-4 font-semibold">Pages</th>
                <th className="px-5 py-4 font-semibold">Chunks</th>
                <th className="px-5 py-4 font-semibold">Upload Date</th>
                <th className="px-5 py-4 font-semibold">Actions</th>
              </tr>
            </thead>

            <tbody>
              {documents.map((document) => (
                <tr
                  key={document.id}
                  className="border-t"
                  style={{
                    borderColor: '#E0DDE1',
                    color: '#555555',
                  }}
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <span className="text-xl">📄</span>
                      <span className="font-medium" style={{ color: '#554188' }}>
                        {document.name}
                      </span>
                    </div>
                  </td>

                  <td className="px-5 py-4">{document.pages}</td>

                  <td className="px-5 py-4">{document.chunks}</td>

                  <td className="px-5 py-4">
                    {new Date(document.created_at).toLocaleDateString()}
                  </td>

                  <td className="px-5 py-4">
                    <button
                      type="button"
                      onClick={() => handleDeleteClick(document)}
                      className="rounded-lg border px-3 py-2 font-medium transition hover:bg-red-50"
                      style={{
                        borderColor: '#E7B8C2',
                        color: '#B4233D',
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}

              {documents.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-5 py-10 text-center"
                    style={{ color: '#777777' }}
                  >
                    No documents available. Upload a PDF to get started.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Delete Confirmation Dialog */}
      {documentToDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setDocumentToDelete(null)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-dialog-title"
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h2
              id="delete-dialog-title"
              className="text-xl font-bold"
              style={{ color: '#554188' }}
            >
              Delete document?
            </h2>

            <p className="mt-3 text-sm" style={{ color: '#555555' }}>
              Are you sure you want to remove{' '}
              <strong>{documentToDelete.name}</strong>?
            </p>

            <p className="mt-2 text-xs" style={{ color: '#888888' }}>
              The document and all of its indexed chunks will be permanently deleted.
            </p>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setDocumentToDelete(null)}
                className="rounded-lg border px-4 py-2 font-semibold"
                style={{
                  borderColor: '#D5CEDB',
                  color: '#554188',
                }}
              >
                Cancel
              </button>

              <button
                type="button"
                onClick={confirmDelete}
                disabled={busy}
                className="rounded-lg px-4 py-2 font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                style={{ backgroundColor: '#B4233D' }}
              >
                {busy ? 'Deleting…' : 'Confirm Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Documents
