"""MONITOR — watch the published ClickUp project and log deviations from the plan.

Unlike INGEST / PLAN / WBS this is not a pipeline stage: a stage runs once, but
monitoring has to keep going after the run is COMPLETE. :func:`monitor_loop` runs as a
background task in the API process, next to the Slack listener, and calls
:func:`check_run` for every run that has been published to ClickUp. Like the runs
themselves, deviations live in memory and are lost on restart.

A check compares the plan (planned due dates and dependencies saved at publish time) with
what ClickUp reports now, and reconciles the run's deviation log:

* OVERDUE          — due date has passed and the task is not done
* DUE_DATE_MOVED   — someone changed the due date away from the planned one
* DEPENDENCY_LATE  — a task is waiting on a dependency that is overdue
* TASK_REMOVED     — the task no longer exists in ClickUp

A deviation stays open while it holds and is stamped ``resolved_at`` once it stops holding,
so the dashboard shows both what is wrong now and what was wrong earlier.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.integrations.clickup import ClickUpClient
from app.models import ArtifactKind, AuditLog, Deviation, DeviationKind, Run
from app.orchestrator.base import StageFailed, artifact_data
from app.schemas.wbs import WorkBreakdownStructure
from app.store import store

log = logging.getLogger(__name__)

#: A due date counts as moved only past this tolerance (ClickUp may shift by timezone).
MOVED_TOLERANCE = timedelta(hours=24)
#: Past this long overdue, an OVERDUE deviation is critical rather than a warning.
CRITICAL_AFTER = timedelta(days=3)
DONE_STATUS_TYPES = {"done", "closed"}

Key = tuple[DeviationKind, str]


def _from_ms(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _is_done(task: dict) -> bool:
    status = task.get("status") or {}
    return str(status.get("type", "")).lower() in DONE_STATUS_TYPES


def detect(
    wbs: WorkBreakdownStructure,
    published: dict[str, dict],
    clickup_tasks: dict[str, dict],
    now: datetime,
) -> dict[Key, Deviation]:
    """Return the deviations that hold right now, keyed by (kind, WBS task id)."""
    found: dict[Key, Deviation] = {}
    overdue: set[str] = set()
    live: dict[str, dict] = {}

    for wbs_task in wbs.tasks:
        entry = published.get(wbs_task.id)
        if entry is None:
            continue
        task = clickup_tasks.get(entry["id"])
        planned = _from_ms(entry.get("planned_due"))

        if task is None:
            found[(DeviationKind.TASK_REMOVED, wbs_task.id)] = Deviation(
                kind=DeviationKind.TASK_REMOVED,
                task_id=wbs_task.id,
                task_name=wbs_task.name,
                message="This task no longer exists in ClickUp.",
                severity="critical",
                planned_due=planned,
            )
            continue

        live[wbs_task.id] = task
        if _is_done(task):
            continue

        actual = _from_ms(task.get("due_date"))
        if actual is not None and actual < now:
            days = max((now - actual).days, 0)
            overdue.add(wbs_task.id)
            found[(DeviationKind.OVERDUE, wbs_task.id)] = Deviation(
                kind=DeviationKind.OVERDUE,
                task_id=wbs_task.id,
                task_name=wbs_task.name,
                message=(
                    f"Due {actual:%d %b %Y} and not done"
                    + (f" ({days} day(s) late)." if days else " (due today).")
                ),
                severity="critical" if now - actual >= CRITICAL_AFTER else "warning",
                planned_due=planned,
                actual_due=actual,
            )

        if planned is not None and (actual is None or abs(actual - planned) >= MOVED_TOLERANCE):
            where = f"moved to {actual:%d %b %Y}" if actual else "removed"
            found[(DeviationKind.DUE_DATE_MOVED, wbs_task.id)] = Deviation(
                kind=DeviationKind.DUE_DATE_MOVED,
                task_id=wbs_task.id,
                task_name=wbs_task.name,
                message=f"Planned for {planned:%d %b %Y}; due date was {where} in ClickUp.",
                planned_due=planned,
                actual_due=actual,
            )

    names = {t.id: t.name for t in wbs.tasks}
    for wbs_task in wbs.tasks:
        if wbs_task.id not in live or _is_done(live[wbs_task.id]):
            continue
        late = [dep for dep in wbs_task.depends_on if dep in overdue]
        if late:
            found[(DeviationKind.DEPENDENCY_LATE, wbs_task.id)] = Deviation(
                kind=DeviationKind.DEPENDENCY_LATE,
                task_id=wbs_task.id,
                task_name=wbs_task.name,
                message="Waiting on overdue task(s): " + ", ".join(names[d] for d in late) + ".",
                planned_due=_from_ms(published[wbs_task.id].get("planned_due")),
            )
    return found


def reconcile(run: Run, current: dict[Key, Deviation], now: datetime) -> tuple[int, int]:
    """Fold ``current`` into ``run.deviations``; return (newly opened, newly resolved)."""
    opened = resolved = 0
    open_ones = {(d.kind, d.task_id): d for d in run.deviations if d.resolved_at is None}

    for key, deviation in current.items():
        existing = open_ones.get(key)
        if existing is None:
            deviation.detected_at = now
            run.deviations.append(deviation)
            opened += 1
        else:
            existing.message = deviation.message
            existing.severity = deviation.severity
            existing.actual_due = deviation.actual_due

    for key, existing in open_ones.items():
        if key not in current:
            existing.resolved_at = now
            resolved += 1
    return opened, resolved


def _wbs_of(run: Run) -> WorkBreakdownStructure | None:
    try:
        return WorkBreakdownStructure.model_validate(artifact_data(run, ArtifactKind.WBS))
    except StageFailed:
        return None


async def check_run(run: Run, client: ClickUpClient | None = None) -> bool:
    """Run one monitoring pass over ``run``. Returns False if it was not monitorable."""
    wbs = _wbs_of(run)
    if not (run.clickup_folder_id and run.clickup_tasks and wbs):
        return False

    started = time.perf_counter()
    now = datetime.now(UTC)
    try:
        tasks = await (client or ClickUpClient()).fetch_tasks(run.clickup_folder_id)
    except Exception as exc:  # noqa: BLE001 - a flaky ClickUp must not stop the loop
        run.monitor_error = f"{type(exc).__name__}: {exc}"
        store.add_audit(
            AuditLog(
                run_id=run.id,
                kind="monitor",
                target=run.clickup_folder_id,
                ok=False,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error=run.monitor_error,
            )
        )
        log.warning("monitor check of run %s failed: %s", run.id, run.monitor_error)
        return True

    opened, resolved = reconcile(run, detect(wbs, run.clickup_tasks, tasks, now), now)
    run.monitor_error = None
    run.last_monitored_at = now
    store.add_audit(
        AuditLog(
            run_id=run.id,
            kind="monitor",
            target=run.clickup_folder_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            detail={"tasks": len(tasks), "opened": opened, "resolved": resolved},
        )
    )
    if opened or resolved:
        log.info("run %s monitor: %d new deviation(s), %d resolved", run.id, opened, resolved)
    return True


async def monitor_loop() -> None:
    """Check every published run forever, every ``MONITOR_INTERVAL_SECONDS``."""
    interval = max(settings.monitor_interval_seconds, 30)
    log.info("ClickUp monitor running every %ds", interval)
    while True:
        for run in store.list_runs():
            try:
                await check_run(run)
            except Exception:  # noqa: BLE001 - one bad run must not stop the loop
                log.exception("monitor check of run %s raised", run.id)
        await asyncio.sleep(interval)
