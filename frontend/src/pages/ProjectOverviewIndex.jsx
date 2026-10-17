import { Navigate } from 'react-router-dom'
import { listRuns } from '../lib/api.js'
import { usePolling } from '../hooks/usePolling.js'
import { FolderIcon } from '../components/icons.jsx'

export default function ProjectOverviewIndex() {
  const { data: runs, error, loading } = usePolling(listRuns, 4000, (result) => result.length === 0)

  if (runs && runs.length > 0) {
    return <Navigate to={`/projects/${runs[0].id}`} replace />
  }

  return (
    <div>
      <h1 className="text-3xl font-bold text-slate-900">Project Overview</h1>
      <div className="mt-6 flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
          <FolderIcon className="h-7 w-7 text-slate-400" />
        </div>
        <p className="text-slate-500">
          {error
            ? error.message
            : loading
              ? 'Loading…'
              : 'No projects yet. Run /pm start in Slack to create one.'}
        </p>
      </div>
    </div>
  )
}
