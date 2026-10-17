"""PROTOTYPE — generate a static prototype, commit it, and deploy it live.

The stage does three things in order, and the order matters: generate, then
GitHub, then Vercel. GitHub comes first because a committed prototype is a
recoverable artifact — if Vercel fails, the code still exists and the run can be
re-run from the deployment step rather than regenerating from scratch.
"""

from __future__ import annotations

import json
import logging

from app.integrations.github import GitHubClient, slugify
from app.integrations.vercel import VercelClient
from app.llm.client import generate_structured
from app.models import ArtifactKind, StageKind
from app.orchestrator.base import (
    ProducedArtifact,
    StageContext,
    StageFailed,
    StageResult,
    artifact_data,
)
from app.schemas.design import Diagram
from app.schemas.prototype import ENTRY_POINT, Prototype, problems

log = logging.getLogger(__name__)

SYSTEM = f"""\
You build low-fidelity clickable prototypes as plain static websites.

Output a complete set of files for a static site. Hard rules, because these
files are deployed exactly as written with no build step:

* Plain HTML only. No React, no Next.js, no build tooling, no npm.
* Style with Tailwind from the CDN:
  <script src="https://cdn.tailwindcss.com"></script>
* No other external resources — no fonts, no images from the internet, no
  analytics. Use inline SVG and CSS for any visuals.
* {ENTRY_POINT} is the landing page and must exist.
* One further .html page per major feature, linked from the landing page with
  ordinary <a href="..."> links so the prototype is clickable.
* Every page carries the same simple header and navigation.
* Use realistic placeholder content drawn from the project, never lorem ipsum.
* Any interactivity is a small inline <script> — no data is persisted.

This is a low-fidelity prototype: it shows layout, flow and content, and it
fakes everything else. Keep each page short enough to read in one screen.
"""

USER_TEMPLATE = """\
Build a clickable low-fidelity prototype of this system.

<plan>
{plan}
</plan>

<requirements>
{requirements}
</requirements>

<design>
{design}
</design>
"""

FEEDBACK_TEMPLATE = """\

The project manager asked for changes to the prototype:

<feedback>
{feedback}
</feedback>
"""

REPAIR_TEMPLATE = """\

Your previous file set could not be deployed:

{problems}

Produce the file set again with those problems fixed.
"""


class PrototypeStage:
    kind = StageKind.PROTOTYPE

    async def run(self, ctx: StageContext) -> StageResult:
        plan = artifact_data(ctx.run, ArtifactKind.PLAN)
        requirements = artifact_data(ctx.run, ArtifactKind.REQUIREMENTS)
        diagrams = _diagrams(ctx.run)

        prompt = USER_TEMPLATE.format(
            plan=json.dumps(plan, indent=2),
            requirements=json.dumps(requirements, indent=2),
            design=_design_brief(diagrams),
        )
        if ctx.feedback:
            prompt += FEEDBACK_TEMPLATE.format(feedback=ctx.feedback)

        prototype, input_tokens, output_tokens = await self._generate(prompt)

        files = prototype.file_map()
        files["README.md"] = readme(ctx.run.title, prototype, diagrams)

        repo_name, repo_url = await GitHubClient().publish(
            repo_name=slugify(ctx.run.title),
            description=prototype.tagline,
            files=files,
            message=f"Generated prototype for {ctx.run.title}",
        )
        live_url = await VercelClient().deploy(name=repo_name, files=files)

        return StageResult(
            artifacts=[
                ProducedArtifact(
                    kind=ArtifactKind.PROTOTYPE_FILES,
                    name=prototype.app_name,
                    data={
                        "app_name": prototype.app_name,
                        "tagline": prototype.tagline,
                        "screens": [screen.model_dump() for screen in prototype.screens],
                        "notes": prototype.notes,
                        "files": files,
                        "repo_url": repo_url,
                        "live_url": live_url,
                    },
                )
            ],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            run_updates={"github_repo_url": repo_url, "vercel_url": live_url},
            summary=f"{len(prototype.screens)} screens deployed to {live_url}",
        )

    async def _generate(self, prompt: str) -> tuple[Prototype, int, int]:
        """Generate a file set, repairing once if it would not be safe to deploy."""
        input_tokens = output_tokens = 0
        found: list[str] = []

        for attempt in range(2):
            result = await generate_structured(
                output_model=Prototype,
                system=SYSTEM,
                user=prompt
                if attempt == 0
                else prompt + REPAIR_TEMPLATE.format(problems="\n".join(f"* {p}" for p in found)),
                # Whole HTML pages: this is the largest generation in the pipeline.
                max_output_tokens=32_000,
            )
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens

            found = problems(result.data)
            if not found:
                return result.data, input_tokens, output_tokens
            log.warning("prototype rejected (attempt %d): %s", attempt + 1, "; ".join(found))

        raise StageFailed(
            "The generated prototype could not be made deployable:\n"
            + "\n".join(f"* {problem}" for problem in found)
        )


def _diagrams(run) -> list[Diagram]:
    """The latest version of each design diagram, if DESIGN has run."""
    by_name: dict[str, object] = {}
    for artifact in run.artifacts:
        if artifact.kind != ArtifactKind.DIAGRAM or not artifact.text:
            continue
        existing = by_name.get(artifact.name)
        if existing is None or artifact.version > existing.version:
            by_name[artifact.name] = artifact
    return [
        Diagram(
            kind=(artifact.data or {}).get("kind", "ARCHITECTURE"),
            title=artifact.name,
            explanation=(artifact.data or {}).get("explanation", ""),
            mermaid=artifact.text or "",
        )
        for artifact in by_name.values()
    ]


def _design_brief(diagrams: list[Diagram]) -> str:
    if not diagrams:
        return "No diagrams were produced; work from the plan alone."
    return "\n\n".join(f"{d.kind.value}: {d.explanation}" for d in diagrams)


def readme(title: str, prototype: Prototype, diagrams: list[Diagram]) -> str:
    """The repository README, with the design diagrams GitHub renders natively."""
    screens = "\n".join(
        f"- [{screen.name}]({screen.path}) — {screen.purpose}" for screen in prototype.screens
    )
    notes = "\n".join(f"- {note}" for note in prototype.notes) or "- None recorded."
    sections = [
        f"# {prototype.app_name}",
        f"> {prototype.tagline}",
        (
            f"A low-fidelity prototype of **{title}**, generated by an agentic AI project "
            "manager from a stakeholder conversation in Slack."
        ),
        "## Screens",
        screens or "- None recorded.",
        "## What this prototype fakes",
        notes,
    ]
    if diagrams:
        sections.append("## System design")
        for diagram in diagrams:
            sections.append(
                f"### {diagram.title}\n\n{diagram.explanation}\n\n"
                f"```mermaid\n{diagram.mermaid}\n```"
            )
    sections.append(
        "## Running it\n\nEvery file is static. Open `index.html`, or serve the "
        "directory with any static file server."
    )
    return "\n\n".join(sections) + "\n"
