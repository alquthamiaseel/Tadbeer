"""GitHub — create a repository and commit the generated prototype into it.

Files are committed through the Git Data API (blob, tree, commit, ref) rather
than one Contents API call per file. That is four requests plus one per file
instead of one commit per file, and more importantly it produces a **single
commit** containing the whole prototype, which is what the history should show:
one generation, one commit.

The repository is created empty and the first commit has no parent, so there is
no README to merge against and no default-branch race.
"""

from __future__ import annotations

import base64
import logging
import re
import uuid

import httpx

from app.config import settings
from app.integrations.http import request_json
from app.orchestrator.base import StageFailed

log = logging.getLogger(__name__)

API = "https://api.github.com"
BRANCH = "main"
#: Regular file, non-executable. GitHub rejects a tree entry without a mode.
BLOB_MODE = "100644"


def slugify(title: str, *, suffix: str = "") -> str:
    """A repository name GitHub will accept, derived from the run title."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug) or "prototype"
    slug = slug[:80].strip("-")
    return f"{slug}-{suffix}" if suffix else slug


class GitHubClient:
    def __init__(self, *, token: str | None = None, owner: str | None = None) -> None:
        self.token = token if token is not None else settings.github_token
        self.owner = owner if owner is not None else settings.github_owner

    def _headers(self) -> dict[str, str]:
        if not self.token or not self.owner:
            raise StageFailed(
                "GitHub is not configured. Set GITHUB_TOKEN (fine-grained, with "
                "Administration and Contents read/write) and GITHUB_OWNER in .env, "
                "then run `make check`.",
                retryable=False,
            )
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def publish(
        self, *, repo_name: str, description: str, files: dict[str, str], message: str
    ) -> tuple[str, str]:
        """Create the repo, commit ``files`` to it, and return (name, html_url)."""
        async with httpx.AsyncClient(headers=self._headers(), timeout=60) as client:
            repo = await self._create_repo(client, repo_name, description)
            name, html_url = repo["name"], repo["html_url"]

            base = f"{API}/repos/{self.owner}/{name}"
            tree = []
            for path, contents in files.items():
                blob = await request_json(
                    client,
                    "POST",
                    f"{base}/git/blobs",
                    service="GitHub",
                    json={
                        "content": base64.b64encode(contents.encode()).decode(),
                        "encoding": "base64",
                    },
                )
                tree.append({"path": path, "mode": BLOB_MODE, "type": "blob", "sha": blob["sha"]})

            created_tree = await request_json(
                client, "POST", f"{base}/git/trees", service="GitHub", json={"tree": tree}
            )
            commit = await request_json(
                client,
                "POST",
                f"{base}/git/commits",
                service="GitHub",
                json={"message": message, "tree": created_tree["sha"], "parents": []},
            )
            await request_json(
                client,
                "POST",
                f"{base}/git/refs",
                service="GitHub",
                json={"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]},
            )

        log.info("committed %d files to %s", len(files), html_url)
        return name, html_url

    async def _create_repo(self, client: httpx.AsyncClient, name: str, description: str) -> dict:
        """Create the repository, retrying once under a new name if it exists.

        Name collisions are expected rather than exceptional: re-running
        PROTOTYPE for the same run asks for the same slug a second time.
        """
        payload = {
            "name": name,
            "description": description[:350],
            "private": False,
            "auto_init": False,
            "has_issues": False,
            "has_wiki": False,
        }
        try:
            return await request_json(
                client, "POST", f"{API}/user/repos", service="GitHub", json=payload
            )
        except StageFailed as exc:
            if "already exists" not in str(exc):
                raise
            payload["name"] = f"{name}-{uuid.uuid4().hex[:6]}"
            log.info("repo %s already exists; using %s", name, payload["name"])
            return await request_json(
                client, "POST", f"{API}/user/repos", service="GitHub", json=payload
            )
