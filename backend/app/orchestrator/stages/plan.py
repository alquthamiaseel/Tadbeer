"""PLAN — turn validated requirements into a human-reviewable delivery plan."""

from __future__ import annotations

import json

from app.llm.client import generate_structured
from app.models import ArtifactKind, StageKind
from app.orchestrator.base import ProducedArtifact, StageContext, StageResult, artifact_data
from app.schemas.plan import ProjectPlan

SYSTEM = """\
You are a senior technical project manager. Turn the validated requirements into
a realistic, concise delivery plan that a human project manager can review.

Do not invent commitments. Preserve stated constraints and exclusions. When the
requirements are thin, make uncertainty visible in assumptions and open
questions rather than pretending it is settled. Phases must be sequential and
useful as the basis for a later work-breakdown structure.
"""

USER_TEMPLATE = """\
Create a project plan from these validated requirements.

<requirements>
{requirements}
</requirements>
"""

FEEDBACK_TEMPLATE = """\

The project manager rejected the previous plan and gave this feedback:

<feedback>
{feedback}
</feedback>

Revise the plan to address that feedback. Keep decisions not contradicted by the
feedback, but make the requested changes explicit.
"""


class PlanStage:
    kind = StageKind.PLAN

    async def run(self, ctx: StageContext) -> StageResult:
        requirements = artifact_data(ctx.run, ArtifactKind.REQUIREMENTS)
        prompt = USER_TEMPLATE.format(requirements=json.dumps(requirements, indent=2))
        if ctx.feedback:
            prompt += FEEDBACK_TEMPLATE.format(feedback=ctx.feedback)

        result = await generate_structured(
            output_model=ProjectPlan,
            system=SYSTEM,
            user=prompt,
            max_output_tokens=16_000,
        )
        plan = result.data
        summary = (
            f"{len(plan.phases)} phases, {len(plan.milestones)} milestones, "
            f"{len(plan.risks)} risks; estimated {plan.estimated_total_days} working days"
        )
        return StageResult(
            artifacts=[
                ProducedArtifact(
                    kind=ArtifactKind.PLAN,
                    name="Project plan",
                    data=plan.model_dump(mode="json"),
                )
            ],
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            needs_approval=True,
            summary=summary,
        )
