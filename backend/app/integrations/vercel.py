"""Vercel — deploy the generated prototype and wait for a live URL.

Files are uploaded **inline** with the deployment request rather than by linking
a GitHub repository. Linking would require the Vercel GitHub App to be installed
and the repo connected, which is the flakiest part of that integration and adds
a manual step per generated repo. Inline deployment needs only a token.

The prototype is static, so ``framework`` is null and there is no build command:
Vercel serves the files as uploaded. That is the whole reason a build cannot
fail during a demo — there is no build.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from app.config import settings
from app.integrations.http import request_json
from app.orchestrator.base import StageFailed

log = logging.getLogger(__name__)

API = "https://api.vercel.com"

#: A static deployment is ready in seconds; this ceiling exists so a stuck
#: deployment fails with an explanation instead of hanging the run.
POLL_TIMEOUT_SECONDS = 180
POLL_INTERVAL_SECONDS = 3

READY = "READY"
TERMINAL = {"READY", "ERROR", "CANCELED"}


class VercelClient:
    def __init__(self, *, token: str | None = None, team_id: str | None = None) -> None:
        self.token = token if token is not None else settings.vercel_token
        self.team_id = team_id if team_id is not None else settings.vercel_team_id

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise StageFailed(
                "Vercel is not configured. Create a token at "
                "https://vercel.com/account/tokens and set VERCEL_TOKEN in .env, "
                "then run `make check`.",
                retryable=False,
            )
        return {"Authorization": f"Bearer {self.token}"}

    def _params(self) -> dict:
        return {"teamId": self.team_id} if self.team_id else {}

    async def deploy(self, *, name: str, files: dict[str, str]) -> str:
        """Deploy ``files`` as a static site and return the live https URL."""
        payload = {
            "name": name[:100],
            "target": "production",
            "files": [
                {
                    "file": path,
                    "data": base64.b64encode(contents.encode()).decode(),
                    "encoding": "base64",
                }
                for path, contents in files.items()
            ],
            # No framework and no build command: the files are served as they are.
            "projectSettings": {
                "framework": None,
                "buildCommand": None,
                "installCommand": None,
                "outputDirectory": None,
            },
        }

        async with httpx.AsyncClient(headers=self._headers(), timeout=120) as client:
            deployment = await request_json(
                client,
                "POST",
                f"{API}/v13/deployments",
                service="Vercel",
                json=payload,
                params=self._params(),
            )
            deployment_id = deployment.get("id")
            url = deployment.get("url")
            if not deployment_id or not url:
                raise StageFailed(
                    f"Vercel accepted the deployment but returned no URL: {deployment}"
                )

            state = await self._await_ready(client, deployment_id)

        if state != READY:
            raise StageFailed(
                f"The Vercel deployment finished in state {state}. "
                f"The build log is at https://{url}/_logs"
            )
        log.info("deployed %s", url)
        return f"https://{url}"

    async def _await_ready(self, client: httpx.AsyncClient, deployment_id: str) -> str:
        """Poll until the deployment reaches a terminal state."""
        waited = 0.0
        while waited < POLL_TIMEOUT_SECONDS:
            body = await request_json(
                client,
                "GET",
                f"{API}/v13/deployments/{deployment_id}",
                service="Vercel",
                params=self._params(),
            )
            state = body.get("readyState") or body.get("status") or ""
            if state in TERMINAL:
                return state
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            waited += POLL_INTERVAL_SECONDS

        raise StageFailed(
            f"The Vercel deployment was still {state or 'pending'} after "
            f"{POLL_TIMEOUT_SECONDS} seconds; giving up rather than hanging the run."
        )
