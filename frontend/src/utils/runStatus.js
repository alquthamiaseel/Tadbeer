export const RUN_STATUS = {
  PENDING: { label: 'Pending', badge: 'bg-slate-100 text-slate-600' },
  RUNNING: { label: 'Running', badge: 'bg-blue-50 text-blue-600' },
  AWAITING_APPROVAL: { label: 'Awaiting approval', badge: 'bg-amber-50 text-amber-600' },
  COMPLETE: { label: 'Complete', badge: 'bg-green-50 text-green-600' },
  FAILED: { label: 'Failed', badge: 'bg-red-50 text-red-600' },
  CANCELLED: { label: 'Cancelled', badge: 'bg-slate-100 text-slate-500' },
}

// Display names for the backend's stage identifiers, in pipeline order.
export const STAGE_LABEL = {
  INGEST: 'Requirements',
  PLAN: 'Planning',
  WBS: 'WBS',
  DESIGN: 'Design',
  PROTOTYPE: 'Prototype',
  DONE: 'Done',
}

// Falls back to a readable form of the identifier if the backend adds a stage.
export function stageLabel(kind) {
  if (!kind) return ''
  return STAGE_LABEL[kind] || kind.charAt(0) + kind.slice(1).toLowerCase().replace(/_/g, ' ')
}

export const IN_PROGRESS = new Set(['PENDING', 'RUNNING'])

export function statusInfo(status) {
  return RUN_STATUS[status] || { label: status, badge: 'bg-slate-100 text-slate-600' }
}

export function latestArtifact(run, kind) {
  const matching = (run?.artifacts || []).filter((artifact) => artifact.kind === kind)
  if (matching.length === 0) return null
  return matching.reduce((best, artifact) => (artifact.version > best.version ? artifact : best))
}

export function formatDateTime(iso) {
  return new Date(iso).toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export const DEVIATION_LABEL = {
  OVERDUE: 'Overdue',
  DUE_DATE_MOVED: 'Due date moved',
  DEPENDENCY_LATE: 'Blocked by late task',
  TASK_REMOVED: 'Removed from ClickUp',
}

export const SEVERITY_BADGE = {
  critical: 'bg-red-50 text-red-600',
  warning: 'bg-amber-50 text-amber-600',
}
