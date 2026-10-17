"""Pipeline state, held in memory.

The pipeline is a state machine: a run, its stages, and the artifacts each stage
produced. These are plain dataclasses kept in the process-wide
:mod:`app.store`, shared by the Slack listener and the dashboard API, which run
in the same process. Nothing here is written to disk — a restart forgets every
run. What has to outlive the process (the generated prototype and its
diagrams) is committed to GitHub by the PROTOTYPE stage.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now() -> datetime:
    return datetime.now(UTC)


class StageKind(enum.StrEnum):
    """The six pipeline stages, in execution order."""

    INGEST = "INGEST"
    PLAN = "PLAN"
    WBS = "WBS"
    DESIGN = "DESIGN"
    PROTOTYPE = "PROTOTYPE"
    DONE = "DONE"


#: Execution order. The orchestrator walks this list; there is no other ordering.
STAGE_ORDER: list[StageKind] = [
    StageKind.INGEST,
    StageKind.PLAN,
    StageKind.WBS,
    StageKind.DESIGN,
    StageKind.PROTOTYPE,
    StageKind.DONE,
]


class StageStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RunStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ArtifactKind(enum.StrEnum):
    REQUIREMENTS = "REQUIREMENTS"
    PLAN = "PLAN"
    WBS = "WBS"
    DIAGRAM = "DIAGRAM"
    PROTOTYPE_FILES = "PROTOTYPE_FILES"
    SUMMARY = "SUMMARY"


class ApprovalDecision(enum.StrEnum):
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


# eq=False throughout: these are mutable entities compared by identity, and a
# run and its stages refer to each other's ids, not to each other's values.


@dataclass(kw_only=True, eq=False)
class Stage:
    """One step of the pipeline within a run."""

    run_id: uuid.UUID
    kind: StageKind
    position: int
    status: StageStatus = StageStatus.PENDING

    attempt: int = 0
    error: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Token accounting, surfaced in the dashboard and useful as report evidence.
    input_tokens: int = 0
    output_tokens: int = 0

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


@dataclass(kw_only=True, eq=False)
class Artifact:
    """A structured output produced by a stage.

    `data` holds the validated JSON the LLM produced against that stage's schema.
    `text` holds raw text output where that is the natural form (Mermaid source,
    generated file contents).
    """

    run_id: uuid.UUID
    kind: ArtifactKind
    name: str
    stage_id: uuid.UUID | None = None
    version: int = 1

    data: dict | None = None
    text: str | None = None

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)


@dataclass(kw_only=True, eq=False)
class Approval:
    """A human decision on a stage, captured from Slack."""

    run_id: uuid.UUID
    decision: ApprovalDecision
    stage_id: uuid.UUID | None = None
    feedback: str | None = None
    decided_by: str | None = None
    slack_message_ts: str | None = None

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)


class DeviationKind(enum.StrEnum):
    OVERDUE = "OVERDUE"
    DUE_DATE_MOVED = "DUE_DATE_MOVED"
    DEPENDENCY_LATE = "DEPENDENCY_LATE"
    TASK_REMOVED = "TASK_REMOVED"


@dataclass(kw_only=True, eq=False)
class Deviation:
    """A difference between the approved plan and what ClickUp shows now."""

    kind: DeviationKind
    task_id: str
    task_name: str
    message: str
    severity: str = "warning"
    planned_due: datetime | None = None
    actual_due: datetime | None = None

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    detected_at: datetime = field(default_factory=_now)
    resolved_at: datetime | None = None


@dataclass(kw_only=True, eq=False)
class Run:
    """One end-to-end pass from a Slack conversation to a deployed prototype."""

    title: str = "Untitled project"
    status: RunStatus = RunStatus.PENDING
    current_stage: StageKind | None = None
    error: str | None = None

    # Where the conversation lives. thread_ts is None for whole-channel runs.
    slack_channel_id: str | None = None
    slack_thread_ts: str | None = None
    started_by: str | None = None

    # External artifacts produced by later stages.
    clickup_folder_id: str | None = None
    clickup_url: str | None = None
    #: WBS task id -> {"id": ClickUp task id, "planned_due": ms epoch or None},
    #: saved at publish time so the monitor can compare plan against ClickUp.
    clickup_tasks: dict[str, dict] = field(default_factory=dict)
    github_repo_url: str | None = None
    vercel_url: str | None = None

    # ClickUp monitoring, which keeps going after the run is COMPLETE.
    deviations: list[Deviation] = field(default_factory=list)
    last_monitored_at: datetime | None = None
    monitor_error: str | None = None

    stages: list[Stage] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)


@dataclass(kw_only=True, eq=False)
class SlackMessage:
    """A captured Slack message.

    Held independently of runs because messages are captured as they arrive —
    a run is created later and claims the conversation it was started from.
    """

    channel_id: str
    ts: str
    thread_ts: str | None = None
    run_id: uuid.UUID | None = None
    user_id: str | None = None
    user_name: str | None = None
    text: str = ""
    is_bot: bool = False

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)


@dataclass(kw_only=True, eq=False)
class AuditLog:
    """Every LLM call and external API call, for debugging and report evidence."""

    kind: str  # "llm" | "api"
    target: str  # model id, "ClickUp POST /folder/1/list", or a ClickUp folder id
    run_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    ok: bool = True
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    detail: dict | None = None
    error: str | None = None

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=_now)
