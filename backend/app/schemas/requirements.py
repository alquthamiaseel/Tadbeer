"""The INGEST stage's output contract.

This is the first artifact in the pipeline and every later stage reads it, so
it is deliberately explicit: the model is asked for structured requirements
rather than a summary, and for the things it *could not* determine as well as
the things it could. `open_questions` and `assumptions` are what make the
approval step in Slack meaningful — without them the PM has nothing to react to
except prose that sounds confident whether or not it is.

Field descriptions are part of the prompt: they are sent to the model as the
schema, so they are written as instructions, not as documentation for us.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, Field


class Priority(enum.StrEnum):
    MUST = "MUST"
    SHOULD = "SHOULD"
    COULD = "COULD"
    WONT = "WONT"


class Actor(BaseModel):
    name: str = Field(description="Role name, e.g. 'Student', 'Event organiser', 'Admin'")
    description: str = Field(description="What this person does with the system, in one sentence")


class Feature(BaseModel):
    title: str = Field(description="Short imperative feature name, e.g. 'Book a seat'")
    description: str = Field(description="What the feature does, in one or two sentences")
    actor: str = Field(description="Name of the actor who uses this, matching an entry in actors")
    priority: Priority = Field(
        description=("MoSCoW priority. Use MUST only for features without which the project fails.")
    )
    source: str = Field(
        description=(
            "Short quote or paraphrase from the conversation that this came from. "
            "If it was inferred rather than stated, say 'inferred'."
        )
    )


class Constraint(BaseModel):
    description: str = Field(description="The constraint, stated plainly")
    kind: str = Field(
        description="One of: budget, deadline, technology, regulatory, resource, integration"
    )


class Requirements(BaseModel):
    """Structured requirements extracted from a stakeholder conversation."""

    project_name: str = Field(
        description="A short, specific project name. Not a generic label like 'Web App'."
    )
    goal: str = Field(
        description="The outcome the stakeholders actually want, in one or two sentences"
    )
    actors: list[Actor] = Field(description="Every distinct kind of user mentioned or implied")
    features: list[Feature] = Field(
        description="Functional requirements. Prefer specific features over broad themes."
    )
    non_functional: list[str] = Field(
        description=(
            "Non-functional requirements: performance, security, accessibility, availability, "
            "scale. Include only ones grounded in the conversation."
        )
    )
    constraints: list[Constraint] = Field(
        description="Budget, deadline, technology, regulatory, or resource constraints stated"
    )
    assumptions: list[str] = Field(
        description=(
            "Things you had to assume because the conversation did not say. Be honest and "
            "specific; this is shown to the project manager for confirmation."
        )
    )
    open_questions: list[str] = Field(
        description=(
            "Questions that must be answered before building. Ask about genuine ambiguity, "
            "not things already settled in the conversation."
        )
    )
    out_of_scope: list[str] = Field(
        description="Anything explicitly ruled out. Empty list if nothing was ruled out."
    )
