"""The contract every pipeline stage implements.

Keeping stages behind one small interface is what lets the engine stay generic:
it knows how to run, time, retry, and record *a stage*, and nothing about what
any particular stage does. Adding a stage means writing one class, not touching
the engine.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from app.models import ArtifactKind, Run, StageKind


@dataclass
class StageContext:
    """Everything a stage is allowed to reach for."""

    run: Run
    #: Feedback from a human who rejected this stage's previous output, if any.
    feedback: str | None = None


@dataclass
class ProducedArtifact:
    kind: ArtifactKind
    name: str
    data: dict | None = None
    text: str | None = None


@dataclass
class StageResult:
    """What a stage hands back to the engine.

    A stage never writes its own status or artifacts — it returns them, and the
    engine records them in one step. That keeps "ran but didn't record" out of
    the set of possible states.
    """

    artifacts: list[ProducedArtifact] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    #: Fields to set on the Run itself, e.g. {"clickup_url": "..."}.
    run_updates: dict[str, object] = field(default_factory=dict)
    #: True if this stage needs a human decision before the pipeline continues.
    needs_approval: bool = False
    #: Human-readable one-liner for the Slack update and the dashboard.
    summary: str = ""


class Stage(Protocol):
    """A single step of the pipeline."""

    kind: StageKind

    async def run(self, ctx: StageContext) -> StageResult: ...


class StageFailed(RuntimeError):
    """A stage could not complete. The message is shown to the user verbatim."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def artifact_data(run: Run, kind: ArtifactKind) -> dict:
    """The most recent artifact of ``kind`` produced for ``run``.

    Stages read their inputs from previously stored artifacts rather than from
    each other, which is what makes a single stage re-runnable in isolation.
    """
    matching = [a for a in run.artifacts if a.kind == kind and a.data is not None]
    if not matching:
        raise StageFailed(
            f"expected a {kind.value} artifact from an earlier stage but none exists; "
            "re-run the earlier stage first",
            retryable=False,
        )
    latest = max(matching, key=lambda a: (a.version, a.created_at))
    return latest.data or {}


def run_id_of(ctx: StageContext) -> uuid.UUID:
    return ctx.run.id
