"""System design artifacts, expressed as Mermaid diagrams.

Mermaid is stored as source text rather than rendered images. Source survives in
git, renders natively in a GitHub README, and the dashboard renders it in the
browser — so there is no headless browser anywhere in this project.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field


class DiagramKind(enum.StrEnum):
    """The four views. Each answers a different question about the system."""

    USE_CASE = "USE_CASE"
    ARCHITECTURE = "ARCHITECTURE"
    ERD = "ERD"
    SEQUENCE = "SEQUENCE"


#: Mermaid diagram headers each kind is allowed to open with. Checked after
#: generation: a use-case diagram that arrives as an ER diagram is a defect the
#: schema cannot catch, because both are valid Mermaid.
ALLOWED_HEADERS: dict[DiagramKind, tuple[str, ...]] = {
    DiagramKind.USE_CASE: ("flowchart", "graph"),
    DiagramKind.ARCHITECTURE: ("flowchart", "graph", "C4Context", "C4Container"),
    DiagramKind.ERD: ("erDiagram",),
    DiagramKind.SEQUENCE: ("sequenceDiagram",),
}


class Diagram(BaseModel):
    kind: DiagramKind = Field(description="Which of the four required views this is")
    title: str = Field(description="Short human-readable diagram title")
    explanation: str = Field(
        description="Two to four sentences explaining what the diagram shows and why"
    )
    mermaid: str = Field(
        description=(
            "Valid Mermaid source only. No markdown code fences. Every node label must be "
            'wrapped in double quotes, for example A["Log in (SSO)"].'
        )
    )


class SystemDesign(BaseModel):
    """Four diagrams describing the system the plan is going to build."""

    overview: str = Field(description="A paragraph describing the overall system design approach")
    technology_choices: list[str] = Field(
        description="Key technology decisions, each with a one-line justification"
    )
    diagrams: list[Diagram] = Field(
        description=(
            "Exactly four diagrams, one of each kind: USE_CASE, ARCHITECTURE, ERD, SEQUENCE"
        )
    )
