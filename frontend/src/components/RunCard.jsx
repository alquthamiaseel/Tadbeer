import { Link } from 'react-router-dom'
import { ArrowRightIcon, ChatIcon } from './icons.jsx'
import { formatDateTime, stageLabel, statusInfo } from '../utils/runStatus.js'

export default function RunCard({ run }) {
  const status = statusInfo(run.status)

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{run.title}</h3>
        <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${status.badge}`}>
          {status.label}
        </span>
      </div>

      <div className="mt-3 space-y-1 text-sm text-slate-500">
        <p>Started {formatDateTime(run.created_at)}</p>
        {run.current_stage && <p>Current stage: {stageLabel(run.current_stage)}</p>}
        <p className="flex items-center gap-2">
          <ChatIcon className="h-4 w-4" />
          Created from Slack
        </p>
        {run.open_deviations > 0 && (
          <p className="font-medium text-red-600">
            {run.open_deviations} deviation{run.open_deviations === 1 ? '' : 's'} from plan
          </p>
        )}
      </div>

      <Link
        to={`/projects/${run.id}`}
        className="mt-5 inline-flex items-center gap-2 rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-400"
      >
        View Requirements &amp; Plan
        <ArrowRightIcon className="h-4 w-4" />
      </Link>
    </div>
  )
}
