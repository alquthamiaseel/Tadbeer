import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { checkClickUpNow, getRun } from '../lib/api.js'
import { usePolling } from '../hooks/usePolling.js'
import {
  DEVIATION_LABEL,
  SEVERITY_BADGE,
  formatDateTime,
  latestArtifact,
  stageLabel,
  statusInfo,
} from '../utils/runStatus.js'
import { CheckCircleIcon, ClockIcon, ChatIcon, CalendarIcon } from '../components/icons.jsx'

const POLL_MS = 2000
const TERMINAL = new Set(['COMPLETE', 'FAILED', 'CANCELLED'])

const PRIORITY_BADGE = {
  MUST: 'bg-red-50 text-red-600',
  SHOULD: 'bg-amber-50 text-amber-600',
  COULD: 'bg-blue-50 text-blue-600',
  WONT: 'bg-slate-100 text-slate-500',
}

const LEVEL_BADGE = {
  low: 'bg-green-50 text-green-600',
  medium: 'bg-amber-50 text-amber-600',
  high: 'bg-red-50 text-red-600',
}

function Card({ title, subtitle, children }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6">
      <h2 className="font-semibold text-slate-900">{title}</h2>
      {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </div>
  )
}

function BulletList({ items }) {
  if (!items || items.length === 0) return <p className="text-sm text-slate-400">None.</p>
  return (
    <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-700">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

function SubHeading({ children }) {
  return <h3 className="mb-2 text-sm font-semibold text-slate-900">{children}</h3>
}

function Pill({ className, children }) {
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${className}`}>
      {children}
    </span>
  )
}

function StageStep({ stage }) {
  const done = stage.status === 'COMPLETE' || stage.status === 'AWAITING_APPROVAL'
  const running = stage.status === 'RUNNING'
  const failed = stage.status === 'FAILED'
  const caption = {
    COMPLETE: 'Done',
    AWAITING_APPROVAL: 'Done · awaiting approval in Slack',
    RUNNING: 'Working…',
    FAILED: 'Failed',
    PENDING: 'Waiting',
    SKIPPED: 'Skipped',
  }[stage.status]

  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        {done && <CheckCircleIcon className="h-5 w-5 shrink-0 text-green-500" />}
        {running && <ClockIcon className="h-5 w-5 shrink-0 animate-pulse text-teal-500" />}
        {failed && <span className="h-5 w-5 shrink-0 rounded-full bg-red-500" />}
        {!done && !running && !failed && (
          <span className="h-5 w-5 shrink-0 rounded-full border-2 border-slate-300" />
        )}
        <span
          className={`text-sm font-medium ${done || running || failed ? 'text-slate-900' : 'text-slate-400'}`}
        >
          {stageLabel(stage.kind)}
        </span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{caption}</p>
      <div className="mt-2 h-1.5 rounded-full bg-slate-100">
        <div
          className={`h-1.5 rounded-full transition-all ${
            failed ? 'bg-red-500' : done ? 'bg-green-500' : 'bg-teal-500'
          } ${running ? 'animate-pulse' : ''}`}
          style={{ width: done || failed ? '100%' : running ? '50%' : '0%' }}
        />
      </div>
    </div>
  )
}

function RequirementsSection({ data }) {
  return (
    <div className="space-y-6">
      <Card title="Project Summary" subtitle={data.project_name}>
        <p className="text-slate-700">{data.goal}</p>
        {data.actors?.length > 0 && (
          <div className="mt-5">
            <SubHeading>Actors</SubHeading>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {data.actors.map((actor) => (
                <div key={actor.name} className="rounded-lg bg-slate-50 p-3">
                  <p className="text-sm font-medium text-slate-900">{actor.name}</p>
                  <p className="text-sm text-slate-500">{actor.description}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      <Card title="Functional Requirements" subtitle={`${data.features?.length || 0} features`}>
        <div className="space-y-3">
          {(data.features || []).map((feature, index) => (
            <div key={index} className="rounded-lg border border-slate-100 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium text-slate-900">{feature.title}</p>
                <div className="flex items-center gap-2">
                  <Pill className="bg-slate-100 text-slate-600">{feature.actor}</Pill>
                  <Pill className={PRIORITY_BADGE[feature.priority] || PRIORITY_BADGE.WONT}>
                    {feature.priority}
                  </Pill>
                </div>
              </div>
              <p className="mt-1 text-sm text-slate-600">{feature.description}</p>
              <p className="mt-2 text-xs italic text-slate-400">Source: {feature.source}</p>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Non-Functional Requirements">
          <BulletList items={data.non_functional} />
        </Card>
        <Card title="Constraints">
          {data.constraints?.length > 0 ? (
            <ul className="space-y-2 text-sm text-slate-700">
              {data.constraints.map((constraint, index) => (
                <li key={index} className="flex items-start gap-2">
                  <Pill className="mt-0.5 shrink-0 bg-slate-100 text-slate-600">
                    {constraint.kind}
                  </Pill>
                  <span>{constraint.description}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">None.</p>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card title="Assumptions">
          <BulletList items={data.assumptions} />
        </Card>
        <Card title="Open Questions">
          <BulletList items={data.open_questions} />
        </Card>
        <Card title="Out of Scope">
          <BulletList items={data.out_of_scope} />
        </Card>
      </div>
    </div>
  )
}

function PlanSection({ data, awaitingApproval }) {
  return (
    <div className="space-y-6">
      <Card
        title="Executive Summary"
        subtitle={`Estimated ${data.estimated_total_days} working days${
          awaitingApproval ? ' · awaiting approval in Slack' : ''
        }`}
      >
        <p className="text-slate-700">{data.executive_summary}</p>
        <div className="mt-5 grid grid-cols-1 gap-6 sm:grid-cols-2">
          <div>
            <SubHeading>In scope</SubHeading>
            <BulletList items={data.in_scope} />
          </div>
          <div>
            <SubHeading>Out of scope</SubHeading>
            <BulletList items={data.out_of_scope} />
          </div>
        </div>
      </Card>

      <Card title="Project Phases" subtitle={`${data.phases?.length || 0} phases`}>
        <div className="space-y-4">
          {(data.phases || []).map((phase, index) => (
            <div key={index} className="rounded-lg border border-slate-100 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium text-slate-900">
                  {index + 1}. {phase.name}
                </p>
                <Pill className="bg-teal-50 text-teal-700">
                  {phase.estimated_duration_days} days
                </Pill>
              </div>
              <p className="mt-1 text-sm text-slate-600">{phase.objective}</p>
              <p className="mb-1.5 mt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Tasks &amp; deliverables
              </p>
              <BulletList items={phase.deliverables} />
            </div>
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Milestones">
          {data.milestones?.length > 0 ? (
            <ul className="space-y-3 text-sm">
              {data.milestones.map((milestone, index) => (
                <li key={index}>
                  <p className="font-medium text-slate-900">
                    {milestone.name}{' '}
                    <span className="font-normal text-slate-400">· {milestone.target_phase}</span>
                  </p>
                  <p className="text-slate-600">{milestone.success_criteria}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">None.</p>
          )}
        </Card>
        <Card title="Risks">
          {data.risks?.length > 0 ? (
            <ul className="space-y-3 text-sm">
              {data.risks.map((risk, index) => (
                <li key={index}>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-slate-900">{risk.title}</p>
                    <Pill className={LEVEL_BADGE[risk.likelihood] || LEVEL_BADGE.medium}>
                      likelihood: {risk.likelihood}
                    </Pill>
                    <Pill className={LEVEL_BADGE[risk.impact] || LEVEL_BADGE.medium}>
                      impact: {risk.impact}
                    </Pill>
                  </div>
                  <p className="text-slate-600">{risk.mitigation}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">None.</p>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Plan Assumptions">
          <BulletList items={data.assumptions} />
        </Card>
        <Card title="Plan Open Questions">
          <BulletList items={data.open_questions} />
        </Card>
      </div>
    </div>
  )
}

function DeviationsSection({ run, onChecked }) {
  const [checking, setChecking] = useState(false)
  const [checkError, setCheckError] = useState(null)
  const open = run.deviations.filter((d) => !d.resolved_at)
  const resolved = run.deviations.filter((d) => d.resolved_at)

  async function checkNow() {
    setChecking(true)
    setCheckError(null)
    try {
      onChecked(await checkClickUpNow(run.id))
    } catch (err) {
      setCheckError(err.message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card
        title="Deviations from plan"
        subtitle={
          run.last_monitored_at
            ? `Last checked ${formatDateTime(run.last_monitored_at)}`
            : 'Not checked yet — the monitor checks ClickUp every few minutes'
        }
      >
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={checkNow}
            disabled={checking}
            className="rounded-lg bg-teal-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-teal-400 disabled:opacity-50"
          >
            {checking ? 'Checking…' : 'Check ClickUp now'}
          </button>
          <a
            href={run.clickup_url}
            target="_blank"
            rel="noreferrer"
            className="text-sm font-medium text-teal-600 hover:text-teal-500"
          >
            Open in ClickUp
          </a>
        </div>
        {(checkError || run.monitor_error) && (
          <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Could not reach ClickUp: {checkError || run.monitor_error}
          </p>
        )}

        <div className="mt-5 space-y-3">
          {open.length === 0 ? (
            <p className="text-sm text-slate-500">
              {run.last_monitored_at ? 'On track — no deviations from the plan.' : 'Nothing to report yet.'}
            </p>
          ) : (
            open.map((d) => <DeviationRow key={d.id} deviation={d} />)
          )}
        </div>
      </Card>

      {resolved.length > 0 && (
        <Card title="Resolved" subtitle={`${resolved.length} earlier deviation(s)`}>
          <div className="space-y-3">
            {resolved.map((d) => (
              <DeviationRow key={d.id} deviation={d} />
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function DeviationRow({ deviation: d }) {
  return (
    <div className={`rounded-lg border border-slate-100 p-4 ${d.resolved_at ? 'opacity-60' : ''}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium text-slate-900">{d.task_name}</p>
        <div className="flex items-center gap-2">
          <Pill className="bg-slate-100 text-slate-600">{DEVIATION_LABEL[d.kind] || d.kind}</Pill>
          {!d.resolved_at && (
            <Pill className={SEVERITY_BADGE[d.severity] || SEVERITY_BADGE.warning}>{d.severity}</Pill>
          )}
        </div>
      </div>
      <p className="mt-1 text-sm text-slate-600">{d.message}</p>
      <p className="mt-2 text-xs text-slate-400">
        Detected {formatDateTime(d.detected_at)}
        {d.resolved_at && ` · resolved ${formatDateTime(d.resolved_at)}`}
      </p>
    </div>
  )
}

function Pending({ children }) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-500">
      {children}
    </div>
  )
}

// Prefer whichever copy of the run saw the more recent ClickUp check.
function newest(a, b) {
  return (a.last_monitored_at || '') > (b.last_monitored_at || '') ? a : b
}

export default function ProjectOverview() {
  const { id } = useParams()
  const [checked, setChecked] = useState(null)
  const { data: polled, error, loading } = usePolling(
    () => getRun(id),
    POLL_MS,
    // A published project is still being monitored after the run completes.
    (result) => !TERMINAL.has(result.status) || Boolean(result.clickup_url),
  )
  const run = checked && polled && checked.id === polled.id ? newest(checked, polled) : polled

  if (loading) return <p className="text-slate-500">Loading…</p>

  if (!run) {
    return (
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Project not found</h1>
        <p className="mt-1 text-slate-500">
          {error?.status === 404
            ? 'This run no longer exists (runs are cleared when the backend restarts). '
            : `${error?.message || ''} `}
          <Link to="/dashboard" className="font-medium text-teal-600 hover:text-teal-500">
            Back to Dashboard
          </Link>
        </p>
      </div>
    )
  }

  const status = statusInfo(run.status)
  const requirements = latestArtifact(run, 'REQUIREMENTS')
  const plan = latestArtifact(run, 'PLAN')
  const stages = [...run.stages].sort((a, b) => a.position - b.position)

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className="text-3xl font-bold text-slate-900">{run.title}</h1>
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${status.badge}`}>
            {status.label}
          </span>
        </div>
        <Link
          to="/dashboard"
          className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
        >
          Back to Dashboard
        </Link>
      </div>

      {run.error && (
        <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {run.error}
        </p>
      )}

      <div className="mt-6 rounded-2xl border border-slate-200 bg-white p-6">
        <h2 className="font-semibold text-slate-900">Pipeline</h2>
        <div className="mt-5 grid grid-cols-2 gap-6 sm:grid-cols-3 lg:grid-cols-6">
          {stages.map((stage) => (
            <StageStep key={stage.id} stage={stage} />
          ))}
        </div>
        <div className="mt-5 flex flex-wrap gap-x-8 gap-y-2 border-t border-slate-100 pt-4 text-sm text-slate-500">
          <span className="flex items-center gap-2">
            <ChatIcon className="h-4 w-4" />
            Slack channel: {run.slack_channel_id || 'Not connected'}
          </span>
          <span className="flex items-center gap-2">
            <CalendarIcon className="h-4 w-4" />
            Started {formatDateTime(run.created_at)}
          </span>
        </div>
      </div>

      <h2 className="mb-4 mt-8 text-xl font-bold text-slate-900">Extracted Requirements</h2>
      {requirements ? (
        <RequirementsSection data={requirements.data} />
      ) : (
        <Pending>
          {run.status === 'FAILED'
            ? 'Requirements could not be extracted.'
            : 'The Requirements Agent is reading the conversation…'}
        </Pending>
      )}

      <h2 className="mb-4 mt-8 text-xl font-bold text-slate-900">Generated Project Plan</h2>
      {plan ? (
        <PlanSection data={plan.data} awaitingApproval={run.status === 'AWAITING_APPROVAL'} />
      ) : (
        <Pending>
          {run.status === 'FAILED'
            ? 'The plan could not be generated.'
            : requirements
              ? 'The Planning Agent is drafting a plan from these requirements…'
              : 'Waiting for the requirements before planning can start.'}
        </Pending>
      )}

      {run.clickup_url && (
        <>
          <h2 className="mb-4 mt-8 text-xl font-bold text-slate-900">ClickUp Monitoring</h2>
          <DeviationsSection run={run} onChecked={setChecked} />
        </>
      )}
    </div>
  )
}
