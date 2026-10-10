import { useEffect, useRef, useState } from 'react'
import { getDocuments } from '../../api/client'

function Documents() {
  const [documents, setDocuments] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)

  const fileInputRef = useRef(null)

  const handleUploadClick = () => {
    fileInputRef.current?.click()
  }

  const handleFileChange = (event) => {
    const file = event.target.files[0]

    if (!file) {
      return
    }

    setSelectedFile(file)

    console.log('Selected file:', file)
  }

  useEffect(() => {
    getDocuments().then(setDocuments)
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

        <p
          className="mt-2"
          style={{ color: '#555555' }}
        >
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
          className="cursor-pointer rounded-2xl border-2 border-dashed p-12 text-center transition hover:bg-[#F0EAF2]"
          style={{
            borderColor: '#7080DA',
            backgroundColor: '#F5F5F4',
          }}
        >
          <div className="mx-auto max-w-md">

            <div className="mb-4 text-4xl">
              📄
            </div>

            <p
              className="text-lg font-semibold"
              style={{ color: '#554188' }}
            >
              Drop your PDF here
            </p>

            <p
              className="mt-2 text-sm"
              style={{ color: '#555555' }}
            >
              or click to browse
            </p>

            <p
              className="mt-4 text-xs"
              style={{ color: '#8A8080' }}
            >
              PDF files only · Maximum file size will be enforced by the backend
            </p>

          </div>
        </div>

        {/* Selected File */}
        {selectedFile && (
          <div
            className="mt-4 rounded-xl border p-4"
            style={{
              borderColor: '#A8C3D4',
              backgroundColor: '#FFFFFF',
            }}
          >
            <p
              className="font-semibold"
              style={{ color: '#554188' }}
            >
              Selected file
            </p>

            <p
              className="mt-1 text-sm"
              style={{ color: '#555555' }}
            >
              {selectedFile.name}
            </p>

            <p
              className="mt-1 text-xs"
              style={{ color: '#888888' }}
            >
              {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        )}
      </section>

      {/* Documents Section */}
      <section>
        <div className="mb-4">

          <h2
            className="text-lg font-semibold"
            style={{ color: '#554188' }}
          >
            Your Documents
          </h2>

          <p
            className="mt-1 text-sm"
            style={{ color: '#777777' }}
          >
            Documents available in your knowledge base.
          </p>

        </div>

        {/* Temporary document area */}
        <div className="space-y-3">

          {documents.map((document) => (
            <div
              key={document.id}
              className="rounded-xl border border-[#E0DDE1] bg-white p-5"
            >

              <h3
                className="font-semibold"
                style={{ color: '#554188' }}
              >
                {document.name}
              </h3>

              <p
                className="mt-2 text-sm"
                style={{ color: '#666666' }}
              >
                {document.pages} pages · {document.chunks} chunks
              </p>

            </div>
          ))}

        </div>
      </section>

    </div>
  )
}

export default Documents