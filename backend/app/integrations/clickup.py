"""ClickUp — publish an approved work-breakdown structure as a real project.

Dependencies are the reason this integration exists rather than a CSV export:
the project statement calls for a WBS "with all dependencies and constraints",
and ClickUp is where a project manager would actually look at one.

ClickUp has no "project" object, so the WBS maps onto its hierarchy as one
Folder per run (inside ``CLICKUP_SPACE_ID``), one List per phase, one Task per
WBS task, and a "waiting on" dependency for every ``depends_on`` edge.

Dependencies are available on every ClickUp plan, but they belong to the
Dependencies ClickApp, which a Space admin can switch off. When it is off the
folder, lists and tasks are all created and only the links fail — so the
failure arrives late, with most of the work already done. :meth:`publish`
reports that case for what it is.

Calls go through the shared HTTP layer, so ClickUp's 100-requests-a-minute
limit is waited out (it sends ``X-RateLimit-Reset``) and every call lands in
the run's audit trail.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app.config import settings
from app.integrations.http import request_json
from app.orchestrator.base import StageFailed
from app.schemas.wbs import WbsTask, WorkBreakdownStructure

BASE_URL = "https://api.clickup.com/api/v2"


class ClickUpClient:
    """Creates a ClickUp folder, one list per phase, tasks, then dependency links."""

    def __init__(self, *, token: str | None = None, space_id: str | None = None) -> None:
        self.token = token if token is not None else settings.clickup_api_token
        self.space_id = space_id if space_id is not None else settings.clickup_space_id
        #: WBS task id -> {"id", "planned_due"}; filled by :meth:`publish` so the
        #: monitor can later match ClickUp tasks back to the plan.
        self.published: dict[str, dict] = {}

    def _client(self) -> httpx.AsyncClient:
        if not self.token or not self.space_id:
            raise StageFailed(
                "ClickUp is not configured. Set CLICKUP_API_TOKEN and "
                "CLICKUP_SPACE_ID, then re-run WBS.",
                retryable=False,
            )
        # Personal tokens (pk_...) are sent bare, without a "Bearer" prefix.
        return httpx.AsyncClient(
            base_url=BASE_URL, headers={"Authorization": self.token}, timeout=30
        )

    async def publish(self, project_name: str, wbs: WorkBreakdownStructure) -> tuple[str, str]:
        """Publish ``wbs`` and return ``(folder_id, folder_url)``."""
        async with self._client() as client:
            folder = await self._post(
                client, f"/space/{self.space_id}/folder", {"name": project_name}
            )
            folder_id = str(folder["id"])
            phases = list(dict.fromkeys(task.phase for task in wbs.tasks))
            lists = {
                phase: await self._post(
                    client,
                    f"/folder/{folder_id}/list",
                    {"name": phase, "content": wbs.project_summary},
                )
                for phase in phases
            }
            ids: dict[str, str] = {}
            team_id: str | None = None
            start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            for task in wbs.tasks:
                payload = self._task_payload(task, start)
                created = await self._post(client, f"/list/{lists[task.phase]['id']}/task", payload)
                ids[task.id] = created["id"]
                self.published[task.id] = {
                    "id": created["id"],
                    "planned_due": payload.get("due_date"),
                }
                team_id = team_id or created.get("team_id")
            url = self._folder_url(folder_id, team_id)
            await self._link_dependencies(client, wbs, ids, url)
        return folder_id, url

    def _folder_url(self, folder_id: str, team_id: str | None) -> str:
        if team_id:
            return f"https://app.clickup.com/{team_id}/v/f/{folder_id}/{self.space_id}"
        return "https://app.clickup.com/"

    async def _link_dependencies(
        self,
        client: httpx.AsyncClient,
        wbs: WorkBreakdownStructure,
        ids: dict[str, str],
        url: str,
    ) -> None:
        """Link every dependency, or explain why the space cannot.

        By this point the folder and every task already exist, so a bare
        "ClickUp returned 400" would leave the user staring at a project that
        looks fine and a run that failed for no visible reason.
        """
        for task in wbs.tasks:
            for dependency in task.depends_on:
                try:
                    await self._post(
                        client,
                        f"/task/{ids[task.id]}/dependency",
                        {"depends_on": ids[dependency]},
                    )
                except StageFailed as exc:
                    raise StageFailed(
                        "ClickUp created the folder and all its tasks, but linking task "
                        f"dependencies failed ({exc}). Check that the Dependencies "
                        "ClickApp is enabled for this Space (Space settings → ClickApps), "
                        f"then re-run WBS. The tasks created so far are at {url}",
                        retryable=False,
                    ) from exc

    async def fetch_tasks(self, folder_id: str) -> dict[str, dict]:
        """Every task in a published folder (closed ones included), keyed by ClickUp id."""
        tasks: dict[str, dict] = {}
        async with self._client() as client:
            body = await request_json(client, "GET", f"/folder/{folder_id}/list", service="ClickUp")
            for item in body.get("lists", []):
                page = 0
                while True:
                    body = await request_json(
                        client,
                        "GET",
                        f"/list/{item['id']}/task",
                        service="ClickUp",
                        params={"include_closed": "true", "subtasks": "true", "page": page},
                    )
                    for task in body.get("tasks", []):
                        tasks[task["id"]] = task
                    if body.get("last_page", True):
                        break
                    page += 1
        return tasks

    async def _post(self, client: httpx.AsyncClient, path: str, data: dict) -> dict:
        """One ClickUp write, retried on rate limits by the shared HTTP layer."""
        return await request_json(client, "POST", path, service="ClickUp", json=data)

    @staticmethod
    def _task_payload(task: WbsTask, start: datetime) -> dict:
        constraints = ", ".join(task.constraints) if task.constraints else "None"
        payload: dict[str, object] = {
            "name": task.name,
            "markdown_description": (
                f"{task.description}\n\n**Owner role:** {task.owner_role}\n"
                f"**Estimate:** {task.estimate_days} working day(s)\n"
                f"**Constraints:** {constraints}"
            ),
        }
        if task.due_offset_days is not None:
            due = start + timedelta(days=task.due_offset_days)
            payload["due_date"] = int(due.timestamp() * 1000)
            payload["due_date_time"] = False
        return payload
