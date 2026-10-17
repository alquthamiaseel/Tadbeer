"""REST API consumed by the dashboard.

The dashboard is read-only over pipeline state, with two exceptions: re-running
a stage, and asking for an immediate ClickUp monitoring check. Approvals stay in
Slack, because the approval conversation is the point —
a decision made in the dashboard would leave no trace where the stakeholders are
talking.

Progress is streamed rather than polled by the browser. The stream itself
re-reads the run once a second, which is the right trade here: runs are minutes
long and low-volume, and a pub/sub broker would be a second service to install
and keep alive for a signal this small.

Every read comes from the in-memory store shared with the Slack listener, which
runs in this same process — that is how Slack-started runs reach the dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.auth import require_dashboard_auth
from app.models import Artifact, Deviation, Run, RunStatus, Stage, StageKind
from app.orchestrator import engine
from app.orchestrator.stages.monitor import check_run
from app.store import store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["runs"], dependencies=[Depends(require_dashboard_auth)])

#: How often the event stream re-reads the run. A stage takes tens of seconds,
#: so this is far finer-grained than the thing it is watching.
POLL_SECONDS = 1.0
#: Comment frames keep proxies from closing an idle stream.
HEARTBEAT_SECONDS = 15.0

TERMINAL_RUN_STATUSES = {RunStatus.COMPLETE, RunStatus.FAILED, RunStatus.CANCELLED}


class StageOut(BaseModel):
    id: uuid.UUID
    kind: str
    position: int
    status: str
    attempt: int
    error: str | None
    duration_seconds: float | None
    input_tokens: int
    output_tokens: int


class ArtifactOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    version: int
    data: dict | None
    text: str | None
    created_at: str


class AuditOut(BaseModel):
    id: uuid.UUID
    kind: str
    target: str
    ok: bool
    duration_ms: int
    input_tokens: int
    output_tokens: int
    detail: dict | None
    error: str | None
    created_at: str


class DeviationOut(BaseModel):
    id: uuid.UUID
    kind: str
    severity: str
    task_id: str
    task_name: str
    message: str
    planned_due: str | None
    actual_due: str | None
    detected_at: str
    resolved_at: str | None


class RunSummaryOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    current_stage: str | None
    created_at: str
    clickup_url: str | None
    github_repo_url: str | None
    vercel_url: str | None
    open_deviations: int


class RunDetailOut(RunSummaryOut):
    error: str | None
    slack_channel_id: str | None
    slack_thread_ts: str | None
    last_monitored_at: str | None
    monitor_error: str | None
    deviations: list[DeviationOut]
    stages: list[StageOut]
    artifacts: list[ArtifactOut]


class RerunIn(BaseModel):
    stage: StageKind
    feedback: str | None = None


def _summary(run: Run) -> RunSummaryOut:
    return RunSummaryOut(
        id=run.id,
        title=run.title,
        status=run.status.value,
        current_stage=run.current_stage.value if run.current_stage else None,
        created_at=run.created_at.isoformat(),
        clickup_url=run.clickup_url,
        github_repo_url=run.github_repo_url,
        vercel_url=run.vercel_url,
        open_deviations=sum(1 for d in run.deviations if d.resolved_at is None),
    )


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _deviation_out(deviation: Deviation) -> DeviationOut:
    return DeviationOut(
        id=deviation.id,
        kind=deviation.kind.value,
        severity=deviation.severity,
        task_id=deviation.task_id,
        task_name=deviation.task_name,
        message=deviation.message,
        planned_due=_iso(deviation.planned_due),
        actual_due=_iso(deviation.actual_due),
        detected_at=deviation.detected_at.isoformat(),
        resolved_at=_iso(deviation.resolved_at),
    )


def _stage_out(stage: Stage) -> StageOut:
    return StageOut(
        id=stage.id,
        kind=stage.kind.value,
        position=stage.position,
        status=stage.status.value,
        attempt=stage.attempt,
        error=stage.error,
        duration_seconds=stage.duration_seconds,
        input_tokens=stage.input_tokens,
        output_tokens=stage.output_tokens,
    )


def _artifact_out(artifact: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=artifact.id,
        kind=artifact.kind.value,
        name=artifact.name,
        version=artifact.version,
        data=artifact.data,
        text=artifact.text,
        created_at=artifact.created_at.isoformat(),
    )


def _detail(run: Run) -> RunDetailOut:
    return RunDetailOut(
        **_summary(run).model_dump(),
        error=run.error,
        slack_channel_id=run.slack_channel_id,
        slack_thread_ts=run.slack_thread_ts,
        last_monitored_at=_iso(run.last_monitored_at),
        monitor_error=run.monitor_error,
        deviations=[
            _deviation_out(d)
            for d in sorted(run.deviations, key=lambda d: d.detected_at, reverse=True)
        ],
        stages=[_stage_out(s) for s in sorted(run.stages, key=lambda s: s.position)],
        artifacts=[
            _artifact_out(a)
            for a in sorted(run.artifacts, key=lambda a: (a.kind.value, a.name, a.version))
        ],
    )


def _load(run_id: uuid.UUID) -> Run:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs", response_model=list[RunSummaryOut])
async def list_runs() -> list[RunSummaryOut]:
    return [_summary(run) for run in store.list_runs(limit=100)]


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: uuid.UUID) -> RunDetailOut:
    return _detail(_load(run_id))


@router.post("/runs/{run_id}/monitor", response_model=RunDetailOut)
async def monitor_now(run_id: uuid.UUID) -> RunDetailOut:
    """Check the run's ClickUp project now, rather than waiting for the loop."""
    run = _load(run_id)
    if not await check_run(run):
        raise HTTPException(status_code=400, detail="This run has not been published to ClickUp")
    return _detail(run)


@router.get("/runs/{run_id}/audit", response_model=list[AuditOut])
async def get_audit(run_id: uuid.UUID) -> list[AuditOut]:
    """Every model and external API call this run made."""
    return [
        AuditOut(
            id=row.id,
            kind=row.kind,
            target=row.target,
            ok=row.ok,
            duration_ms=row.duration_ms,
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            detail=row.detail,
            error=row.error,
            created_at=row.created_at.isoformat(),
        )
        for row in store.audit_for(run_id)
    ]


@router.get("/runs/{run_id}/artifacts/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(run_id: uuid.UUID, artifact_id: uuid.UUID) -> ArtifactOut:
    run = store.get_run(run_id)
    artifacts = run.artifacts if run is not None else []
    artifact = next((a for a in artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return _artifact_out(artifact)


@router.get("/stages/{stage_id}", response_model=StageOut)
async def get_stage(stage_id: uuid.UUID) -> StageOut:
    stage = store.get_stage(stage_id)
    if stage is None:
        raise HTTPException(status_code=404, detail="Stage not found")
    return _stage_out(stage)


@router.post("/runs/{run_id}/rerun", response_model=RunDetailOut)
async def rerun(run_id: uuid.UUID, body: RerunIn) -> RunDetailOut:
    """Reset a stage and everything after it, then run forward in the background.

    Returns immediately with the reset state. A run takes minutes; holding the
    HTTP request open for it would only invite a proxy to time it out.
    """
    run = _load(run_id)
    if not any(stage.kind == body.stage for stage in run.stages):
        raise HTTPException(status_code=400, detail=f"{body.stage} is not a stage of this run")

    asyncio.create_task(_rerun_in_background(run_id, body.stage, body.feedback))
    return _detail(run)


async def _rerun_in_background(run_id: uuid.UUID, stage: StageKind, feedback: str | None) -> None:
    """Detached from the request, which has already been answered."""
    try:
        await engine.rerun_stage(run_id, stage, feedback=feedback)
    except Exception:  # noqa: BLE001 - a background task must not die silently
        log.exception("background re-run of %s on run %s failed", stage, run_id)


def _signature(run: Run) -> tuple:
    """What has to change for the dashboard to need a new frame."""
    return (
        run.status,
        run.current_stage,
        run.error,
        run.clickup_url,
        run.github_repo_url,
        run.vercel_url,
        len(run.artifacts),
        run.last_monitored_at,
        run.monitor_error,
        len(run.deviations),
        sum(1 for d in run.deviations if d.resolved_at is None),
        tuple(sorted((s.kind, s.status, s.attempt, s.error) for s in run.stages)),
    )


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: uuid.UUID) -> StreamingResponse:
    """Server-sent events: one frame per actual change, then done."""

    async def frames() -> AsyncIterator[str]:
        previous: tuple | None = None
        since_heartbeat = 0.0
        try:
            while True:
                run = _load(run_id)
                signature = _signature(run)
                if signature != previous:
                    previous = signature
                    since_heartbeat = 0.0
                    payload = _detail(run).model_dump(mode="json")
                    yield f"data: {json.dumps(payload)}\n\n"
                if run.status in TERMINAL_RUN_STATUSES:
                    yield "event: end\ndata: {}\n\n"
                    return

                await asyncio.sleep(POLL_SECONDS)
                since_heartbeat += POLL_SECONDS
                if since_heartbeat >= HEARTBEAT_SECONDS:
                    since_heartbeat = 0.0
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:  # the browser navigated away
            raise
        except HTTPException:
            yield 'event: error\ndata: {"detail": "Run not found"}\n\n'

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Nginx and friends buffer streamed responses into uselessness.
            "X-Accel-Buffering": "no",
        },
    )
