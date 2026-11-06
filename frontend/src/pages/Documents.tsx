// Documents ("/documents") — real GET /api/v1/documents, filtered by
// the backend to the caller's role. Search + department filter, Admin
// upload (multipart) and delete with a confirm dialog.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, getStoredUser, roleLabel, rolesForDepartment, type DocumentRow } from '../api/client'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { TableSkeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'

const DEPARTMENTS = ['RETAIL', 'COMPLIANCE', 'HR']

const DEPT_BADGE: Record<string, string> = {
  RETAIL: 'bg-teal-100 text-teal-800',
  COMPLIANCE: 'bg-amber-100 text-amber-800',
  HR: 'bg-violet-100 text-violet-800',
}

export default function Documents() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const me = getStoredUser()
  const isAdmin = me?.role === 'ADMIN'
  const [docs, setDocs] = useState<DocumentRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [deptFilter, setDeptFilter] = useState('ALL')
  const [deleteTarget, setDeleteTarget] = useState<DocumentRow | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadDept, setUploadDept] = useState('RETAIL')
  const [uploading, setUploading] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await api.documents()
      setDocs(res.data.documents)
    } catch (e) {
      if (e instanceof Error && e.message === 'UNAUTHORIZED') {
        navigate('/login')
        return
      }
      setError(e instanceof Error ? e.message : 'Could not load documents')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return docs.filter(
      (d) =>
        (deptFilter === 'ALL' || d.department === deptFilter) &&
        (q === '' || d.title.toLowerCase().includes(q) || d.document_id.toLowerCase().includes(q)),
    )
  }, [docs, search, deptFilter])

  async function upload(e: React.FormEvent) {
    e.preventDefault()
    if (!file) return
    setUploading(true)
    try {
      await api.uploadDocument(file, uploadTitle.trim() || undefined, uploadDept)
      toast('Document uploaded.', 'success')
      setFile(null)
      setUploadTitle('')
      void load()
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Upload failed.', 'error')
    } finally {
      setUploading(false)
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.deleteDocument(deleteTarget.document_id)
      toast('Document deleted.', 'success')
      setDeleteTarget(null)
      void load()
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Delete failed.', 'error')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <section>
      <h1 className="text-2xl font-bold text-navy-900">Documents</h1>
      <p className="mt-1 text-sm text-slate-600">
        {me
          ? `Showing what ${roleLabel(me.role)} can see (${me.departments.join(', ')}). The list is filtered by the backend — never by the UI alone.`
          : 'Sign in to see documents.'}
      </p>

      {isAdmin && (
        <form
          onSubmit={upload}
          className="mt-5 rounded-xl border bg-white p-5 shadow-sm"
          aria-label="Upload a document"
        >
          <h2 className="text-base font-semibold text-navy-900">Upload a document (Admin only)</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <label className="block text-sm">
              <span className="font-medium text-slate-700">File (PDF)</span>
              <input
                type="file"
                accept=".pdf"
                className="mt-1 block w-full text-sm"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Title (optional)</span>
              <input
                type="text"
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
                placeholder="Leave empty to use the file name"
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium text-slate-700">Department</span>
              <select
                value={uploadDept}
                onChange={(e) => setUploadDept(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
              >
                {DEPARTMENTS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            type="submit"
            disabled={!file || uploading}
            className="mt-3 rounded-lg bg-navy-900 px-4 py-2 text-sm font-semibold text-white hover:bg-navy-800 disabled:opacity-50"
          >
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </form>
      )}

      <div className="mt-5 flex flex-wrap gap-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by title or document ID…"
          className="min-w-56 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
        />
        <select
          value={deptFilter}
          onChange={(e) => setDeptFilter(e.target.value)}
          className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-navy-700 focus:outline-none focus:ring-2 focus:ring-navy-200"
          aria-label="Filter by department"
        >
          <option value="ALL">All departments</option>
          {DEPARTMENTS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-4">
        {loading && <TableSkeleton rows={6} cols={4} />}
        {!loading && error && <ErrorState message={error} onRetry={() => void load()} />}
        {!loading && !error && docs.length === 0 && (
          <EmptyState
            title="No documents"
            message="No documents are visible for your role yet."
          />
        )}
        {!loading && !error && docs.length > 0 && filtered.length === 0 && (
          <EmptyState
            title="No matches"
            message="No documents match your search or filter. Try a different search."
          />
        )}
        {!loading && !error && filtered.length > 0 && (
          <div className="overflow-x-auto rounded-xl border bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-slate-50 text-left">
                  <th className="px-4 py-3 font-semibold text-navy-900">Title</th>
                  <th className="px-4 py-3 font-semibold text-navy-900">Department</th>
                  <th className="px-4 py-3 font-semibold text-navy-900">Sections</th>
                  <th className="px-4 py-3 font-semibold text-navy-900">Visible to</th>
                  <th className="px-4 py-3 font-semibold text-navy-900">Version</th>
                  {isAdmin && <th className="px-4 py-3" aria-label="Actions" />}
                </tr>
              </thead>
              <tbody>
                {filtered.map((d) => (
                  <tr key={d.document_id} className="border-b last:border-0">
                    <td className="px-4 py-3">
                      <p className="font-medium text-navy-900">{d.title}</p>
                      <p className="text-xs text-slate-500">{d.document_id}</p>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${DEPT_BADGE[d.department] ?? 'bg-slate-100 text-slate-700'}`}
                      >
                        {d.department}
                      </span>
                    </td>
                    <td className="px-4 py-3">{d.chunk_count}</td>
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {rolesForDepartment(d.department).map(roleLabel).join(' · ')}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600">{d.version}</td>
                    {isAdmin && (
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => setDeleteTarget(d)}
                          className="rounded-lg border border-red-200 px-2.5 py-1 text-xs font-medium text-red-700 hover:bg-red-50"
                        >
                          Delete
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {deleteTarget && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="Confirm delete">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-navy-900">Delete this document?</h2>
            <p className="mt-2 text-sm text-slate-600">
              “{deleteTarget.title}” will be removed from the knowledge base. This cannot be undone.
              (Built-in synthetic documents cannot be deleted via the API.)
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleting}
                onClick={() => void confirmDelete()}
                className="rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800 disabled:opacity-50"
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
