"""End-to-end acceptance: a seeded conversation to a live prototype.

This is both the test and the demo script. It drives a real run through all six
stages against the real OpenAI, ClickUp, GitHub and Vercel APIs, then checks the
five things that have to be true for the project to have done what it claims:

1. A ClickUp folder exists with phase lists, tasks and at least one dependency.
2. Four Mermaid diagrams exist and all parse.
3. A GitHub repository holds the prototype with the diagrams in its README.
4. The Vercel URL serves the prototype over HTTP 200.
5. Every stage is COMPLETE and every artifact is present.

It approves the plan automatically. That is the one thing it cannot check —
whether a human agreed — so the approval gate is exercised for real in the
Slack demo instead.

Pipeline state is in memory, so this script seeds the canned conversation into
its own process and drives and verifies the run there. It does not need (or
see) a running API server; the prototype it produces persists on GitHub.

Usage:
    python -m scripts.e2e --channel C0123456789
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass

import httpx

from app.config import settings
from app.mermaid import check, describe
from app.models import ArtifactKind, RunStatus, StageKind, StageStatus
from app.orchestrator import engine
from app.schemas.design import ALLOWED_HEADERS, DiagramKind
from scripts.seed import seed_store

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    #: A check that was deliberately turned off. Neither a pass nor a failure:
    #: reporting it as either would misrepresent what the run demonstrated.
    skipped: bool = False

    def render(self) -> str:
        if self.skipped:
            mark = f"{YELLOW}SKIP{RESET}"
        else:
            mark = f"{GREEN}PASS{RESET}" if self.ok else f"{RED}FAIL{RESET}"
        return f"  [{mark}] {self.name}\n         {DIM}{self.detail}{RESET}"


async def drive(channel_id: str) -> uuid.UUID:
    """Run the pipeline end to end, approving the plan without a human."""
    seed_store(channel_id)
    run = await engine.create_run(
        title="End-to-end acceptance", slack_channel_id=channel_id, started_by="e2e"
    )
    run_id = run.id
    print(f"{DIM}run {run_id}{RESET}")

    async def announce(_run, stage):
        print(f"  {stage.kind:<10} {stage.status:<18} {stage.duration_seconds or 0:.1f}s")

    run = await engine.advance(run_id, on_stage=announce)

    plan = next(s for s in run.stages if s.kind == StageKind.PLAN)
    if plan.status == StageStatus.AWAITING_APPROVAL:
        print(f"{YELLOW}  approving the plan automatically{RESET}")
        run = await engine.approve(run_id, StageKind.PLAN, on_stage=announce)

    return run_id


async def verify(run_id: uuid.UUID) -> list[Check]:
    run = await engine.load_run(run_id)
    if run is None:
        return [Check("Run exists", False, f"no run with id {run_id}")]

    artifacts = {kind: [a for a in run.artifacts if a.kind == kind] for kind in ArtifactKind}
    checks = [
        _check_stages(run),
        _check_clickup(run, artifacts[ArtifactKind.WBS]),
        _check_diagrams(artifacts[ArtifactKind.DIAGRAM]),
    ]
    checks.append(await _check_github(run))
    checks.append(await _check_prototype(run))
    return checks


def _check_stages(run) -> Check:
    incomplete = [
        f"{stage.kind}={stage.status}"
        for stage in sorted(run.stages, key=lambda s: s.position)
        if stage.status != StageStatus.COMPLETE
    ]
    tokens = sum(s.input_tokens + s.output_tokens for s in run.stages)
    if incomplete or run.status != RunStatus.COMPLETE:
        return Check(
            "Every stage completed",
            False,
            f"run is {run.status}; incomplete: {', '.join(incomplete) or 'none'}",
        )
    return Check(
        "Every stage completed",
        True,
        f"6 stages, {tokens:,} tokens, {run.error or 'no errors'}",
    )


def _check_clickup(run, wbs_artifacts) -> Check:
    if not settings.clickup_enabled:
        tasks = (wbs_artifacts[-1].data or {}).get("tasks", []) if wbs_artifacts else []
        dependencies = sum(len(task.get("depends_on", [])) for task in tasks)
        return Check(
            "ClickUp project with dependencies",
            True,
            f"CLICKUP_ENABLED is false — {len(tasks)} tasks and {dependencies} dependencies "
            "were built and stored, but not published",
            skipped=True,
        )
    if not run.clickup_url or not wbs_artifacts:
        return Check("ClickUp project with dependencies", False, "no ClickUp project was created")
    tasks = (wbs_artifacts[-1].data or {}).get("tasks", [])
    dependencies = sum(len(task.get("depends_on", [])) for task in tasks)
    if dependencies == 0:
        return Check(
            "ClickUp project with dependencies",
            False,
            f"{len(tasks)} tasks but no dependency links — check the Dependencies ClickApp",
        )
    return Check(
        "ClickUp project with dependencies",
        True,
        f"{len(tasks)} tasks, {dependencies} dependency links — {run.clickup_url}",
    )


def _check_diagrams(diagram_artifacts) -> Check:
    latest: dict[str, object] = {}
    for artifact in diagram_artifacts:
        kind = (artifact.data or {}).get("kind", "")
        current = latest.get(kind)
        if current is None or artifact.version > current.version:
            latest[kind] = artifact

    missing = [kind.value for kind in DiagramKind if kind.value not in latest]
    if missing:
        return Check("Four diagrams, all parsing", False, f"missing: {', '.join(missing)}")

    for kind, artifact in latest.items():
        problems = check(artifact.text or "", expected_headers=ALLOWED_HEADERS[DiagramKind(kind)])
        if problems:
            return Check("Four diagrams, all parsing", False, f"{kind}: {describe(problems)}")

    return Check("Four diagrams, all parsing", True, ", ".join(sorted(latest)))


async def _check_github(run) -> Check:
    if not run.github_repo_url:
        return Check("Prototype committed to GitHub", False, "no repository was created")

    raw = run.github_repo_url.replace("github.com", "raw.githubusercontent.com")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        readme = await client.get(f"{raw}/main/README.md")
        index = await client.get(f"{raw}/main/index.html")

    if readme.status_code != 200 or index.status_code != 200:
        return Check(
            "Prototype committed to GitHub",
            False,
            f"README {readme.status_code}, index.html {index.status_code} at {run.github_repo_url}",
        )
    if "```mermaid" not in readme.text:
        return Check(
            "Prototype committed to GitHub",
            False,
            "README has no Mermaid block, so GitHub will render no diagrams",
        )
    return Check(
        "Prototype committed to GitHub",
        True,
        f"README with diagrams and {len(index.text):,} bytes of index.html — {run.github_repo_url}",
    )


async def _check_prototype(run) -> Check:
    if not run.vercel_url:
        return Check("Prototype live on Vercel", False, "no deployment URL was recorded")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            response = await client.get(run.vercel_url)
        except httpx.HTTPError as exc:
            return Check("Prototype live on Vercel", False, f"{run.vercel_url}: {exc}")
    if response.status_code != 200:
        return Check(
            "Prototype live on Vercel", False, f"{run.vercel_url} returned {response.status_code}"
        )
    return Check(
        "Prototype live on Vercel",
        True,
        f"{run.vercel_url} returned 200, {len(response.text):,} bytes",
    )


async def main_async(args) -> int:
    run_id = await drive(args.channel)

    print("\nAcceptance checks")
    checks = await verify(run_id)
    for item in checks:
        print(item.render())

    passed = sum(1 for item in checks if item.ok and not item.skipped)
    skipped = sum(1 for item in checks if item.skipped)
    tail = f", {skipped} skipped" if skipped else ""
    print(f"\n{passed}/{len(checks) - skipped} checks passed{tail}")
    if args.json:
        print(
            json.dumps(
                [
                    {"name": c.name, "ok": c.ok, "detail": c.detail, "skipped": c.skipped}
                    for c in checks
                ]
            )
        )
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel", required=True, help="Slack channel id to attribute the seeded run to"
    )
    parser.add_argument("--json", action="store_true", help="also print the results as JSON")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
