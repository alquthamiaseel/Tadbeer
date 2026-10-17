"""The human-reviewable project plan produced after requirements ingestion."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlanPhase(BaseModel):
    name: str = Field(description="Short phase name, such as Discovery or Implementation")
    objective: str = Field(description="Outcome this phase must achieve")
    deliverables: list[str] = Field(description="Concrete outputs of this phase")
    estimated_duration_days: int = Field(
        ge=1, le=365, description="Realistic elapsed working days for this phase"
    )


class Milestone(BaseModel):
    name: str = Field(description="Short milestone name")
    success_criteria: str = Field(description="Observable condition that makes it complete")
    target_phase: str = Field(description="Name of the phase in which it is due")


class Risk(BaseModel):
    title: str = Field(description="Short risk name")
    likelihood: str = Field(description="One of: low, medium, high")
    impact: str = Field(description="One of: low, medium, high")
    mitigation: str = Field(description="Specific action that reduces this risk")


class ProjectPlan(BaseModel):
    """A deliberately concise plan that a project manager can approve in Slack."""

    executive_summary: str = Field(
        description="Clear two-to-four sentence summary of the project and intended outcome"
    )
    in_scope: list[str] = Field(description="Concrete capabilities included in this project")
    out_of_scope: list[str] = Field(description="Explicit exclusions and deferred work")
    phases: list[PlanPhase] = Field(description="Ordered delivery phases, usually three to six")
    milestones: list[Milestone] = Field(description="Meaningful review or delivery milestones")
    risks: list[Risk] = Field(description="Most important delivery risks and their mitigations")
    assumptions: list[str] = Field(description="Assumptions requiring stakeholder confirmation")
    open_questions: list[str] = Field(
        description="Unresolved questions that could materially change scope, cost, or delivery"
    )
    estimated_total_days: int = Field(
        ge=1, le=730, description="Total estimated elapsed working days across the plan"
    )
