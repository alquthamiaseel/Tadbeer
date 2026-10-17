"""The pipeline engine.

Walks a run through the six stages in order. The engine owns everything that is
the same for every stage — timing, status transitions, recording, retries,
approval gates — so a stage only has to produce its artifact.

State lives in the shared in-memory store (:mod:`app.store`), not in a
database, so a process restart forgets every run. Within a process two
properties still hold:

* **Resumable.** :func:`advance` starts from the first stage that is not
  complete, so a failed stage or an exhausted free-tier quota costs the current
  stage and nothing before it.
* **Re-runnable.** Any single stage can be reset and run again with feedback,
  because its inputs are stored artifacts, not values held by a caller.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app import audit
from app.models import (
    STAGE_ORDER,
    Artifact,
    AuditLog,
    Run,
    RunStatus,
    Stage,
    StageKind,
    StageStatus,
)
from app.orchestrator.base import StageContext, StageFailed, StageResult
from app.orchestrator.stages.design import DesignStage
from app.orchestrator.stages.done import DoneStage
from app.orchestrator.stages.ingest import IngestStage
from app.orchestrator.stages.plan import PlanStage
from app.orchestrator.stages.prototype import PrototypeStage
from app.orchestrator.stages.wbs import WbsStage
from app.store import store

log = logging.getLogger(__name__)

#: Which stages pause for a human decision in Slack before the pipeline goes on.
#: PLAN is the one that always matters: everything downstream is derived from it,
#: so it is the cheapest possible place to catch a misunderstanding.
APPROVAL_GATES: set[StageKind] = {StageKind.PLAN}

#: Every stage, in no particular order — STAGE_ORDER decides execution. The
#: engine stops cleanly at a kind that is absent here rather than failing, which
#: is what let the pipeline be built up one stage at a time.
REGISTRY: dict[StageKind, object] = {
    StageKind.INGEST: IngestStage(),
    StageKind.PLAN: PlanStage(),
    StageKind.WBS: WbsStage(),
    StageKind.DESIGN: DesignStage(),
    StageKind.PROTOTYPE: PrototypeStage(),
    StageKind.DONE: DoneStage(),
}


def _now() -> datetime:
    return datetime.now(UTC)


async def create_run(
    *,
    title: str = "Untitled project",
    slack_channel_id: str | None = None,
    slack_thread_ts: str | None = None,
    started_by: str | None = None,
) -> Run:
    """Create a run with all six stages pending."""
    run = Run(
        title=title,
        status=RunStatus.PENDING,
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        started_by=started_by,
    )
    run.stages = [
        Stage(run_id=run.id, kind=kind, position=position)
        for position, kind in enumerate(STAGE_ORDER)
    ]
    store.add_run(run)
    log.info("created run %s (%s)", run.id, title)
    return run


async def load_run(run_id: uuid.UUID) -> Run | None:
    """The live run object. Every caller shares it, so changes are seen at once."""
    return store.get_run(run_id)


def next_stage(run: Run) -> Stage | None:
    """The first stage that still needs to run, or None if the run is finished."""
    for stage in sorted(run.stages, key=lambda s: s.position):
        if stage.status in (StageStatus.COMPLETE, StageStatus.SKIPPED):
            continue
        return stage
    return None


#: Called after each stage settles, with the run and the stage that just ran.
#: Exists so Slack can report progress during a run that takes minutes; the
#: engine stays unaware of Slack, and a caller that does not care passes None.
StageObserver = Callable[[Run, Stage], Awaitable[None]]


async def advance(
    run_id: uuid.UUID,
    *,
    feedback: str | None = None,
    on_stage: StageObserver | None = None,
) -> Run:
    """Run stages until the pipeline finishes, needs a human, or fails.

    Safe to call repeatedly: it always resumes from the first incomplete stage,
    so the same call both starts a fresh run and continues an interrupted one.
    """
    run = await load_run(run_id)
    if run is None:
        raise ValueError(f"no such run: {run_id}")

    while True:
        stage = next_stage(run)

        if stage is None:
            run.status = RunStatus.COMPLETE
            run.current_stage = None
            log.info("run %s complete", run.id)
            return run

        if stage.status == StageStatus.AWAITING_APPROVAL:
            log.info("run %s waiting on approval for %s", run.id, stage.kind)
            return run

        implementation = REGISTRY.get(stage.kind)
        if implementation is None:
            # Not an error: stages are added over the course of the build, and
            # stopping here beats failing a run that got as far as it could.
            log.info("run %s reached unimplemented stage %s; stopping", run.id, stage.kind)
            run.status = RunStatus.RUNNING
            run.current_stage = stage.kind
            return run

        ok = await _run_stage(run, stage, implementation, feedback)
        feedback = None  # applies to the stage it was given for, not the ones after

        if on_stage is not None:
            try:
                await on_stage(run, stage)
            except Exception:  # noqa: BLE001 - reporting must not fail the run
                log.exception("stage observer raised for %s on run %s", stage.kind, run.id)

        if not ok:
            return run
        if stage.status == StageStatus.AWAITING_APPROVAL:
            return run


async def _run_stage(
    run: Run,
    stage: Stage,
    implementation,
    feedback: str | None,
) -> bool:
    """Execute one stage and record everything it produced. True if it advanced."""
    stage.status = StageStatus.RUNNING
    stage.attempt += 1
    stage.started_at = _now()
    stage.error = None
    run.status = RunStatus.RUNNING
    run.current_stage = stage.kind

    log.info("run %s stage %s starting (attempt %d)", run.id, stage.kind, stage.attempt)

    # Everything the stage calls records into this collector, whether or not it
    # knows the engine exists. Recorded below even when the stage fails —
    # a failed stage is exactly when the call log is worth having.
    with audit.collecting() as calls:
        try:
            result: StageResult = await implementation.run(StageContext(run=run, feedback=feedback))
        except StageFailed as exc:
            return await _fail(run, stage, str(exc), calls)
        except Exception as exc:  # noqa: BLE001 - failures land on the run, not just the log
            log.exception("run %s stage %s raised", run.id, stage.kind)
            return await _fail(run, stage, f"{type(exc).__name__}: {exc}", calls)

    _record_audit(run, stage, calls)

    for produced in result.artifacts:
        existing = [a for a in run.artifacts if a.kind == produced.kind and a.name == produced.name]
        run.artifacts.append(
            Artifact(
                run_id=run.id,
                stage_id=stage.id,
                kind=produced.kind,
                name=produced.name,
                # Re-running a stage adds a version rather than overwriting, so
                # the history of what changed after feedback survives.
                version=max((a.version for a in existing), default=0) + 1,
                data=produced.data,
                text=produced.text,
            )
        )

    for field, value in result.run_updates.items():
        setattr(run, field, value)

    stage.input_tokens += result.input_tokens
    stage.output_tokens += result.output_tokens
    stage.completed_at = _now()

    gated = result.needs_approval or stage.kind in APPROVAL_GATES
    stage.status = StageStatus.AWAITING_APPROVAL if gated else StageStatus.COMPLETE
    run.status = RunStatus.AWAITING_APPROVAL if gated else RunStatus.RUNNING

    log.info(
        "run %s stage %s %s in %.1fs (%d/%d tokens)",
        run.id,
        stage.kind,
        stage.status,
        stage.duration_seconds or 0,
        result.input_tokens,
        result.output_tokens,
    )
    return True


def _record_audit(run: Run, stage: Stage, calls: audit.Collector) -> None:
    """Keep one AuditLog entry per call, for the dashboard's audit view."""
    for entry in calls.entries:
        store.add_audit(
            AuditLog(
                run_id=run.id,
                stage_id=stage.id,
                kind=entry.kind,
                target=entry.target,
                ok=entry.ok,
                duration_ms=entry.duration_ms,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                detail=entry.detail,
                error=entry.error,
            )
        )


async def _fail(run: Run, stage: Stage, message: str, calls: audit.Collector) -> bool:
    _record_audit(run, stage, calls)
    # A stage that failed on its third model call still spent the first two. The
    # collector is the only record of that, because the stage never got to
    # return a result — leaving these at zero would understate real usage
    # exactly where someone is looking to find out what went wrong.
    stage.input_tokens += calls.input_tokens
    stage.output_tokens += calls.output_tokens
    stage.status = StageStatus.FAILED
    stage.completed_at = _now()
    stage.error = message
    run.status = RunStatus.FAILED
    run.error = f"{stage.kind}: {message}"
    log.error("run %s stage %s failed: %s", run.id, stage.kind, message)
    return False


async def mark_stage_approved(run_id: uuid.UUID, stage_kind: StageKind) -> Run:
    """Record that a human approved a gated stage, without running anything.

    Separate from :func:`approve` because the caller that has a human waiting —
    a Slack button — wants to answer immediately and let the rest of the
    pipeline continue in the background.
    """
    run = await load_run(run_id)
    if run is None:
        raise ValueError(f"no such run: {run_id}")

    stage = next((s for s in run.stages if s.kind == stage_kind), None)
    if stage is None or stage.status != StageStatus.AWAITING_APPROVAL:
        raise ValueError(f"{stage_kind} is not awaiting approval on run {run_id}")

    stage.status = StageStatus.COMPLETE
    return run


async def approve(
    run_id: uuid.UUID,
    stage_kind: StageKind,
    *,
    on_stage: StageObserver | None = None,
) -> Run:
    """Mark a gated stage approved and carry on."""
    await mark_stage_approved(run_id, stage_kind)
    return await advance(run_id, on_stage=on_stage)


async def request_changes(
    run_id: uuid.UUID,
    stage_kind: StageKind,
    feedback: str,
    *,
    on_stage: StageObserver | None = None,
) -> Run:
    """Send a gated stage back to be redone with the reviewer's feedback."""
    run = await load_run(run_id)
    if run is None:
        raise ValueError(f"no such run: {run_id}")

    stage = next((s for s in run.stages if s.kind == stage_kind), None)
    if stage is None:
        raise ValueError(f"{stage_kind} is not a stage of run {run_id}")

    stage.status = StageStatus.PENDING
    return await advance(run_id, feedback=feedback, on_stage=on_stage)


async def rerun_stage(
    run_id: uuid.UUID,
    stage_kind: StageKind,
    *,
    feedback: str | None = None,
    on_stage: StageObserver | None = None,
) -> Run:
    """Reset a stage and everything after it, then run forward from there.

    Later stages are reset too because they were derived from output that is
    about to change; leaving them complete would leave the run internally
    inconsistent.
    """
    run = await load_run(run_id)
    if run is None:
        raise ValueError(f"no such run: {run_id}")

    target = next((s for s in run.stages if s.kind == stage_kind), None)
    if target is None:
        raise ValueError(f"{stage_kind} is not a stage of run {run_id}")

    for stage in run.stages:
        if stage.position >= target.position:
            stage.status = StageStatus.PENDING
            stage.error = None
            stage.started_at = None
            stage.completed_at = None

    run.error = None
    run.status = RunStatus.PENDING
    return await advance(run_id, feedback=feedback, on_stage=on_stage)
