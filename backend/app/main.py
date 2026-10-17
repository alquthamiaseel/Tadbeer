"""FastAPI application entrypoint.

The Slack Socket Mode listener and the ClickUp monitor run inside this process,
started by the lifespan below. They have to: pipeline state lives in memory
(:mod:`app.store`), so a run started from Slack, and the deviations the monitor
finds, are only visible to the dashboard if all three share one process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import users
from app.api.auth import router as auth_router
from app.api.routes import router as api_router
from app.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("pmfyp")


def _prepare_users_file() -> None:
    """Create users.json if missing and sync the optional admin login.

    Failures are logged, not raised: a bad users.json should lock the dashboard
    (every /api call then reports why), not stop Slack from working.
    """
    try:
        users.ensure_file()
        users.dashboard_account()
        if not users.load_users():
            log.warning("no dashboard logins yet; run `make create-user` or set DASHBOARD_PASSWORD")
    except (users.UsersFileError, OSError) as exc:
        log.error("users file problem: %s", exc)


async def _start_slack():
    if not (settings.slack_bot_token and settings.slack_app_token):
        log.warning("Slack tokens not set; running the dashboard API without the Slack listener")
        return None
    from app.integrations import slack

    try:
        return await slack.connect_socket_mode()
    except Exception:  # noqa: BLE001 - a Slack outage must not take the dashboard down
        log.exception("could not connect to Slack; the dashboard API is still running")
        return None


def _start_monitor() -> asyncio.Task | None:
    if not (settings.clickup_enabled and settings.monitor_enabled and settings.clickup_api_token):
        log.info("ClickUp monitor is off (needs CLICKUP_ENABLED, MONITOR_ENABLED and a token)")
        return None
    from app.orchestrator.stages.monitor import monitor_loop

    return asyncio.create_task(monitor_loop())


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("pm-fyp backend starting (model=%s)", settings.llm_model)
    log.info("pipeline state is in memory only; runs are lost when this process stops")
    _prepare_users_file()

    if settings.seed_channel:
        from scripts.seed import seed_store

        seed_store(settings.seed_channel)

    slack_handler = await _start_slack()
    monitor_task = _start_monitor()
    yield
    if monitor_task is not None:
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
    if slack_handler is not None:
        await slack_handler.close_async()
    log.info("pm-fyp backend stopping")


app = FastAPI(
    title="pm-fyp",
    description="Agentic AI project manager: Slack conversation to plan, ClickUp WBS, prototype",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
