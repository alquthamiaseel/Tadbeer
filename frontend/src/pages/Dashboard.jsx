import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { listRuns } from '../lib/api.js'
import { usePolling } from '../hooks/usePolling.js'
import { formatDateTime, statusInfo, IN_PROGRESS } from '../utils/runStatus.js'
import StatCard from '../components/StatCard.jsx'
import RunCard from '../components/RunCard.jsx'
import { FolderIcon, CheckCircleIcon, ClockIcon, ListIcon } from '../components/icons.jsx'

const POLL_MS = 4000

function getTimeOfDayGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

function getTodayFormatted() {
  return new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

export default function Dashboard() {
  const { user } = useAuth()
  const { data: runs, error, loading } = usePolling(listRuns, POLL_MS)
  const list = runs || []

  const stats = [
    {
      label: 'Total Runs',
      icon: FolderIcon,
      iconColorClass: 'bg-teal-50 text-teal-600',
      value: list.length,
    },
    {
      label: 'In Progress',
      icon: ListIcon,
      iconColorClass: 'bg-blue-50 text-blue-600',
      value: list.filter((run) => IN_PROGRESS.has(run.status)).length,
    },
    {
      label: 'Awaiting Approval',
      icon: ClockIcon,
      iconColorClass: 'bg-amber-50 text-amber-600',
      value: list.filter((run) => run.status === 'AWAITING_APPROVAL').length,
    },
    {
      label: 'Completed',
      icon: CheckCircleIcon,
      iconColorClass: 'bg-green-50 text-green-600',
      value: list.filter((run) => run.status === 'COMPLETE').length,
    },
  ]

  return (
    <div>
      <h1 className="text-3xl font-bold text-slate-900">
        {getTimeOfDayGreeting()}, {user?.username}
      </h1>
      <p className="mt-1 text-slate-500">{getTodayFormatted()}</p>

      {error && (
        <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error.message}
        </p>
      )}

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <StatCard key={stat.label} {...stat} />
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {loading ? (
            <p className="text-slate-500">Loading runs…</p>
          ) : list.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-slate-200 bg-white p-12 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
                <FolderIcon className="h-7 w-7 text-slate-400" />
              </div>
              <h2 className="text-lg font-semibold text-slate-900">No projects yet</h2>
              <p className="mt-1 text-slate-500">
                In Slack, discuss what you want built in a channel with the Tadbeer bot, then run{' '}
                <span className="font-mono text-teal-600">/pm start</span>.
              </p>
            </div>
          ) : (
            list.map((run) => <RunCard key={run.id} run={run} />)
          )}
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h2 className="mb-4 font-semibold text-slate-900">Recent Activity</h2>
          {list.length === 0 ? (
            <p className="text-sm text-slate-500">No recent activity yet.</p>
          ) : (
            <ul className="space-y-4">
              {list.slice(0, 6).map((run) => (
                <li key={run.id} className="text-sm">
                  <Link
                    to={`/projects/${run.id}`}
                    className="font-medium text-slate-900 hover:text-teal-600"
                  >
                    {run.title}
                  </Link>
                  <p className="text-slate-500">
                    {statusInfo(run.status).label} · {formatDateTime(run.created_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
