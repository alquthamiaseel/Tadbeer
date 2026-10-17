"""Validated work-breakdown structure published to ClickUp."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WbsTask(BaseModel):
    id: str = Field(description="Unique stable local id, for example discovery-01")
    phase: str = Field(description="Approved project-plan phase this task belongs to")
    name: str = Field(description="Action-oriented task name")
    description: str = Field(description="Task scope and completion criteria")
    owner_role: str = Field(description="Role responsible for delivery")
    estimate_days: int = Field(ge=1, le=120, description="Estimated working days")
    depends_on: list[str] = Field(description="Earlier local task ids that must finish first")
    constraints: list[str] = Field(description="Constraints relevant to this task")
    due_offset_days: int | None = Field(
        default=None,
        ge=1,
        le=730,
        description="Days from project start for due date, or null if not estimated",
    )


class WorkBreakdownStructure(BaseModel):
    project_summary: str = Field(description="One-sentence delivery approach")
    tasks: list[WbsTask] = Field(
        description="Ordered flat task list; dependencies must refer only to earlier task ids"
    )
