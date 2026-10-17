"""DONE — close the run with a recap of everything it produced.

Deliberately does not call the model. Every fact in the recap is already on the
run, and a generated summary could contradict the artifacts it summarises —
the one place in the pipeline where an LLM would subtract reliability rather
than add capability. It also means a run always finishes, even with the
free-tier quota exhausted.
"""

from __future__ import annotations

from app.models import ArtifactKind, StageKind
from app.orchestrator.base import ProducedArtifact, StageContext, StageResult


class DoneStage:
    kind = StageKind.DONE

    async def run(self, ctx: StageContext) -> StageResult:
        run = ctx.run
        latest = _latest_by_kind(run)

        requirements = (latest.get(ArtifactKind.REQUIREMENTS) or {}).get("data") or {}
        plan = (latest.get(ArtifactKind.PLAN) or {}).get("data") or {}
        wbs = (latest.get(ArtifactKind.WBS) or {}).get("data") or {}
        prototype = (latest.get(ArtifactKind.PROTOTYPE_FILES) or {}).get("data") or {}
        diagrams = [a for a in run.artifacts if a.kind == ArtifactKind.DIAGRAM]

        summary = {
            "title": run.title,
            "goal": requirements.get("goal", ""),
            "executive_summary": plan.get("executive_summary", ""),
            "counts": {
                "features": len(requirements.get("features", [])),
                "phases": len(plan.get("phases", [])),
                "tasks": len(wbs.get("tasks", [])),
                "dependencies": sum(len(t.get("depends_on", [])) for t in wbs.get("tasks", [])),
                "diagrams": len({a.name for a in diagrams}),
                "screens": len(prototype.get("screens", [])),
            },
            "links": {
                "clickup": run.clickup_url,
                "github": run.github_repo_url,
                "prototype": run.vercel_url,
            },
            "open_questions": plan.get("open_questions", []),
            "tokens": {
                "input": sum(stage.input_tokens for stage in run.stages),
                "output": sum(stage.output_tokens for stage in run.stages),
            },
        }

        counts = summary["counts"]
        return StageResult(
            artifacts=[
                ProducedArtifact(kind=ArtifactKind.SUMMARY, name="Run summary", data=summary)
            ],
            summary=(
                f"{counts['features']} features, {counts['phases']} phases, "
                f"{counts['tasks']} tasks, {counts['diagrams']} diagrams, "
                f"{counts['screens']} screens"
            ),
        )


def _latest_by_kind(run) -> dict[ArtifactKind, dict]:
    """The newest version of each artifact kind, keyed by kind."""
    latest: dict[ArtifactKind, dict] = {}
    for artifact in run.artifacts:
        current = latest.get(artifact.kind)
        if current is None or artifact.version > current["version"]:
            latest[artifact.kind] = {"version": artifact.version, "data": artifact.data}
    return latest
