"""DESIGN — turn the approved plan into four Mermaid views of the system."""

from __future__ import annotations

import json
import logging

from app.llm.client import generate_structured
from app.mermaid import check, describe, strip_fences
from app.models import ArtifactKind, StageKind
from app.orchestrator.base import (
    ProducedArtifact,
    StageContext,
    StageFailed,
    StageResult,
    artifact_data,
)
from app.schemas.design import ALLOWED_HEADERS, Diagram, DiagramKind, SystemDesign

log = logging.getLogger(__name__)

SYSTEM = """\
You are a software architect. Design the system described by the approved plan
and requirements, and express the design as Mermaid diagrams.

Produce exactly four diagrams, one of each kind:

* USE_CASE — a flowchart of actors and the things each of them can do.
* ARCHITECTURE — a flowchart of the components and how they communicate.
* ERD — an erDiagram of the persistent entities and their relationships.
* SEQUENCE — a sequenceDiagram of the single most important end-to-end flow.

Mermaid rules, which matter because invalid source will not render:

* Emit Mermaid source only. Never wrap it in markdown code fences.
* Start each diagram with its type: `flowchart TD`, `erDiagram`, `sequenceDiagram`.
* Quote every node label: write A["Log in (SSO)"], never A[Log in (SSO)].
* Keep each diagram readable — roughly 6 to 14 nodes, not an exhaustive dump.

Design only what the plan actually calls for. Do not invent subsystems the
requirements never asked for.
"""

USER_TEMPLATE = """\
Design the system for this approved plan.

<plan>
{plan}
</plan>

<requirements>
{requirements}
</requirements>
"""

FEEDBACK_TEMPLATE = """\

The project manager reviewed the previous design and asked for changes:

<feedback>
{feedback}
</feedback>

Revise the design accordingly.
"""

REPAIR_TEMPLATE = """\

Your previous diagrams contained Mermaid syntax errors and would not render:

{problems}

Produce the four diagrams again with those errors fixed. Remember that every
node label must be wrapped in double quotes.
"""


class DesignStage:
    kind = StageKind.DESIGN

    async def run(self, ctx: StageContext) -> StageResult:
        plan = artifact_data(ctx.run, ArtifactKind.PLAN)
        requirements = artifact_data(ctx.run, ArtifactKind.REQUIREMENTS)

        prompt = USER_TEMPLATE.format(
            plan=json.dumps(plan, indent=2),
            requirements=json.dumps(requirements, indent=2),
        )
        if ctx.feedback:
            prompt += FEEDBACK_TEMPLATE.format(feedback=ctx.feedback)

        input_tokens = output_tokens = 0
        design: SystemDesign | None = None
        problems = ""

        # One repair attempt. A second is not worth another call against a
        # per-minute quota: if the model cannot fix its own Mermaid once, the
        # run should fail loudly rather than store diagrams that will not render.
        for attempt in range(2):
            result = await generate_structured(
                output_model=SystemDesign,
                system=SYSTEM,
                user=prompt if attempt == 0 else prompt + REPAIR_TEMPLATE.format(problems=problems),
                max_output_tokens=16_000,
            )
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens

            candidate = _normalise(result.data)
            problems = _problems(candidate)
            if not problems:
                design = candidate
                break
            log.warning("DESIGN produced invalid Mermaid (attempt %d): %s", attempt + 1, problems)

        if design is None:
            raise StageFailed(
                "The generated diagrams contain Mermaid syntax errors that could not be "
                f"repaired:\n{problems}"
            )

        return StageResult(
            artifacts=[
                ProducedArtifact(
                    kind=ArtifactKind.DIAGRAM,
                    name=diagram.title,
                    data={
                        "kind": diagram.kind.value,
                        "title": diagram.title,
                        "explanation": diagram.explanation,
                        "overview": design.overview,
                        "technology_choices": design.technology_choices,
                    },
                    text=diagram.mermaid,
                )
                for diagram in design.diagrams
            ],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            summary=(
                f"{len(design.diagrams)} diagrams: "
                + ", ".join(d.kind.value.lower().replace("_", " ") for d in design.diagrams)
            ),
        )


def _normalise(design: SystemDesign) -> SystemDesign:
    """Strip code fences the model wrapped around otherwise valid source."""
    return design.model_copy(
        update={
            "diagrams": [
                diagram.model_copy(update={"mermaid": strip_fences(diagram.mermaid)})
                for diagram in design.diagrams
            ]
        }
    )


def _problems(design: SystemDesign) -> str:
    """Everything wrong with this design, as one message for the repair prompt."""
    reports: list[str] = []

    produced = {diagram.kind for diagram in design.diagrams}
    missing = [kind.value for kind in DiagramKind if kind not in produced]
    if missing:
        reports.append(f"missing required diagram kinds: {', '.join(missing)}")

    for diagram in design.diagrams:
        found = check(diagram.mermaid, expected_headers=ALLOWED_HEADERS[diagram.kind])
        if found:
            reports.append(f"{diagram.kind.value} ({diagram.title}): {describe(found)}")

    return "\n".join(f"* {report}" for report in reports)


def diagram_markdown(diagrams: list[Diagram]) -> str:
    """The diagrams as a markdown section, for the generated repo's README."""
    blocks = []
    for diagram in diagrams:
        blocks.append(
            f"### {diagram.title}\n\n{diagram.explanation}\n\n```mermaid\n{diagram.mermaid}\n```"
        )
    return "\n\n".join(blocks)
