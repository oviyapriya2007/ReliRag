import { useEffect, useRef, useState } from 'react'
import {
  deleteDocument,
  getDocuments,
  uploadDocument,
} from '../../api/client'

function Documents() {
  const [documents, setDocuments] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)
  const [documentToDelete, setDocumentToDelete] = useState(null)
  const [busy, setBusy] = useState(false)

  const fileInputRef = useRef(null)

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

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

  const handleFileChange = (event) => {
    handleFileSelection(event.target.files[0])
    event.target.value = ''
  }

  const handleDragOver = (event) => {
    event.preventDefault()
  }

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

  const handleDeleteClick = (document) => {
    setDocumentToDelete(document)
  }

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
    <div className="mx-auto w-full max-w-6xl space-y-7">
      {/* Page Header */}
      <header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-[#51416B]">
            <span className="h-2 w-2 rounded-full bg-[#DB88A4]" />
            Knowledge Base
          </div>

          <h1 className="text-3xl font-bold tracking-tight text-[#29243A]">
            Documents
          </h1>

          <p className="mt-2 text-sm text-[#817789]">
            Manage the documents that power your RAG knowledge base.
          </p>
        </div>

        <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[#C8D9EB] bg-[#DCE8F5] px-4 py-2 text-sm font-medium text-[#51416B]">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg border border-[#D5E3EF] bg-white text-[#738FBD]">
            ▤
          </span>
          {documents.length} {documents.length === 1 ? 'document' : 'documents'}
        </div>
      </header>

      {/* Upload Section */}
      <section className="overflow-hidden rounded-2xl border border-[#D8CDE5] bg-[#FCFAFD] shadow-sm">
        <div className="border-b border-[#D8CDE5] bg-[#EAE0F0] px-5 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#D4C4E0] bg-white text-xl text-[#51416B]">
              ↑
            </div>

            <div>
              <h2 className="text-base font-semibold text-[#29243A]">
                Upload Document
              </h2>
              <p className="mt-0.5 text-xs text-[#665A75]">
                Add a PDF to your searchable knowledge base.
              </p>
            </div>
          </div>
        </div>

        <div className="bg-[#F8F5FA] p-5 sm:p-6">
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
            aria-label="Choose or drop a PDF file to upload"
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                handleUploadClick()
              }
            }}
            className="group cursor-pointer rounded-2xl border-2 border-dashed border-[#91B3D1] bg-[#DCE8F5] px-4 py-9 text-center transition-colors duration-200 hover:border-[#738FBD] hover:bg-[#D2E0F1] sm:py-11"
          >
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-[#C8D9EB] bg-white text-2xl text-[#51416B] shadow-sm transition-transform duration-200 group-hover:-translate-y-0.5">
              ⇧
            </div>

            <p className="mt-4 text-base font-semibold text-[#29243A]">
              Drop your PDF here
            </p>

            <p className="mt-1.5 text-sm text-[#51485B]">
              or{' '}
              <span className="font-semibold text-[#51416B] underline decoration-[#DB88A4] underline-offset-4">
                click to browse
              </span>
            </p>

            <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-[#C8D9EB] bg-white px-3 py-1.5 text-xs text-[#665A75]">
              <span className="font-semibold text-[#738FBD]">PDF</span>
              <span>Maximum file size enforced by the backend</span>
            </div>
          </div>

          {/* Selected File Details */}
          {selectedFile && (
            <div className="mt-4 rounded-xl border border-[#D8C4E3] bg-[#EAE0F0] p-4 sm:p-5">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 items-start gap-3">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[#D4C4E0] bg-white text-xl text-[#51416B]">
                    ▤
                  </div>

                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-wider text-[#665A75]">
                      Selected file
                    </p>

                    <p className="mt-1 break-all text-sm font-semibold text-[#29243A]">
                      {selectedFile.name}
                    </p>

                    <p className="mt-1 text-xs text-[#665A75]">
                      {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
                    </p>
                  </div>
                </div>

                <div className="flex shrink-0 flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handleUpload}
                    disabled={busy}
                    className="rounded-lg bg-[#51416B] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#29243A] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busy ? 'Uploading and indexing…' : 'Upload PDF'}
                  </button>

                  <button
                    type="button"
                    onClick={() => setSelectedFile(null)}
                    disabled={busy}
                    className="rounded-lg border border-[#D4C4E0] bg-white px-4 py-2.5 text-sm font-semibold text-[#51416B] transition-colors hover:bg-[#F6DDE6] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>

              {busy && (
                <>
                  <div
                    className="pipeline-progress-track mt-4"
                    role="progressbar"
                    aria-label="Document upload and indexing in progress"
                    aria-valuetext="Uploading and indexing"
                  >
                    <div
                      className="pipeline-progress-fill"
                      style={{ width: '100%' }}
                    />
                  </div>

                  <p className="mt-2 text-xs text-[#665A75]">
                    Uploading your PDF and processing it. Please wait…
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </section>

      {/* Documents Table */}
      <section className="overflow-hidden rounded-2xl border border-[#D8CDE5] bg-[#FCFAFD] shadow-sm">
        <div className="flex flex-col justify-between gap-3 border-b border-[#D8CDE5] bg-[#EAE0F0] px-5 py-4 sm:flex-row sm:items-center sm:px-6">
          <div>
            <h2 className="text-base font-semibold text-[#29243A]">
              Your Documents
            </h2>

            <p className="mt-1 text-xs text-[#665A75]">
              Documents available in your knowledge base.
            </p>
          </div>

          <span className="w-fit rounded-lg border border-[#D4C4E0] bg-white px-3 py-1.5 text-xs font-semibold text-[#51416B]">
            {documents.length} {documents.length === 1 ? 'item' : 'items'}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="bg-[#DCE8F5] text-[#29243A]">
              <tr>
                <th scope="col" className="px-5 py-3.5 font-semibold sm:px-6">
                  Document
                </th>
                <th scope="col" className="whitespace-nowrap px-5 py-3.5 font-semibold">
                  Document ID
                </th>
                <th scope="col" className="px-5 py-3.5 font-semibold">
                  Pages
                </th>
                <th scope="col" className="px-5 py-3.5 font-semibold">
                  Chunks
                </th>
                <th scope="col" className="whitespace-nowrap px-5 py-3.5 font-semibold">
                  Upload Date
                </th>
                <th scope="col" className="px-5 py-3.5 font-semibold">
                  Actions
                </th>
              </tr>
            </thead>

            <tbody className="divide-y divide-[#E5DBE6]">
              {documents.map((document, index) => (
                <tr
                  key={document.id}
                  className={`transition-colors hover:bg-[#F6DDE6] ${
                    index % 2 === 0 ? 'bg-white' : 'bg-[#F5F0F8]'
                  }`}
                >
                  <td className="px-5 py-4 sm:px-6">
                    <div className="flex items-center gap-3">
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border text-lg ${
                          index % 3 === 0
                            ? 'border-[#C8D9EB] bg-[#DCE8F5] text-[#51416B]'
                            : index % 3 === 1
                              ? 'border-[#D8C4E3] bg-[#EAE0F0] text-[#51416B]'
                              : 'border-[#F0D0DD] bg-[#F6DDE6] text-[#A84665]'
                        }`}
                      >
                        ▤
                      </div>

                      <span className="max-w-xs break-all font-medium text-[#29243A]">
                        {document.name}
                      </span>
                    </div>
                  </td>

                  {/* Live document ID from the backend */}
                  <td className="whitespace-nowrap px-5 py-4">
                    <span className="inline-flex items-center rounded-lg border border-[#D8C4E3] bg-[#EAE0F0] px-2.5 py-1 font-mono text-xs font-semibold text-[#51416B]">
                      {document.id}
                    </span>
                  </td>

                  <td className="px-5 py-4 text-[#51485B]">
                    {document.pages ?? '—'}
                  </td>

                  <td className="px-5 py-4">
                    <span className="inline-flex min-w-10 items-center justify-center rounded-lg border border-[#C8D9EB] bg-[#DCE8F5] px-2.5 py-1 font-semibold text-[#51416B]">
                      {document.chunks ?? '—'}
                    </span>
                  </td>

                  <td className="whitespace-nowrap px-5 py-4 text-[#665A75]">
                    {document.created_at
                      ? new Date(document.created_at).toLocaleDateString()
                      : '—'}
                  </td>

                  <td className="px-5 py-4">
                    <button
                      type="button"
                      onClick={() => handleDeleteClick(document)}
                      disabled={busy}
                      className="rounded-lg border border-[#EBC5D3] bg-[#F6DDE6] px-3 py-2 text-xs font-semibold text-[#A84665] transition-colors hover:bg-[#F0C9D8] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}

              {documents.length === 0 && (
                <tr>
                  <td colSpan={6} className="bg-[#F5F0F8] px-5 py-14 text-center">
                    <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-[#C8D9EB] bg-[#DCE8F5] text-2xl text-[#51416B]">
                      ▤
                    </div>

                    <p className="mt-4 text-sm font-semibold text-[#29243A]">
                      No documents available
                    </p>

                    <p className="mt-1 text-xs text-[#665A75]">
                      Upload a PDF to start building your knowledge base.
                    </p>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {documents.length > 0 && (
          <div className="border-t border-[#D8CDE5] bg-[#EAE0F0] px-5 py-3 text-xs text-[#665A75] sm:px-6">
            Your uploaded documents are available for retrieval and evaluation.
          </div>
        )}
      </section>

      {/* Delete Confirmation Dialog */}
      {documentToDelete && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#29243A]/50 p-4 backdrop-blur-[3px]"
          onClick={() => {
            if (!busy) setDocumentToDelete(null)
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-dialog-title"
            className="w-full max-w-md rounded-2xl border border-[#D8CDE5] bg-[#FCFAFD] p-6 shadow-xl sm:p-7"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-[#EBC5D3] bg-[#F6DDE6] text-xl text-[#BD4357]">
              !
            </div>

            <h2
              id="delete-dialog-title"
              className="mt-4 text-xl font-bold text-[#29243A]"
            >
              Delete document?
            </h2>

            <p className="mt-3 break-words text-sm leading-6 text-[#51485B]">
              Are you sure you want to remove{' '}
              <strong className="font-semibold text-[#29243A]">
                {documentToDelete.name}
              </strong>
              ?
            </p>

            <p className="mt-2 text-xs leading-5 text-[#665A75]">
              The document and all its indexed chunks will be permanently
              deleted. This action cannot be undone.
            </p>

            <div className="mt-6 flex flex-col-reverse justify-end gap-2 sm:flex-row">
              <button
                type="button"
                onClick={() => setDocumentToDelete(null)}
                disabled={busy}
                className="rounded-lg border border-[#D4C4E0] bg-white px-4 py-2.5 text-sm font-semibold text-[#51416B] transition-colors hover:bg-[#EAE0F0] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Cancel
              </button>

              <button
                type="button"
                onClick={confirmDelete}
                disabled={busy}
                className="rounded-lg bg-[#BD4357] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#A93449] disabled:cursor-not-allowed disabled:opacity-50"
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