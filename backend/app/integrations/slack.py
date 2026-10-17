"""Slack integration.

Slack is the conversation hub: it is where requirements arrive, where the agent
reports, and where a human approves or rejects what it produced. This module is
the boundary — it captures messages, handles `/pm`, and posts results. It holds
no pipeline logic of its own; that lives in the orchestrator.

Socket Mode, not webhooks. The app opens an outbound WebSocket to Slack, so
there is no public URL, no tunnel to configure, and nothing to expire in the
middle of a demo.

Two properties this module has to get right:

* **Capture is idempotent.** Slack redelivers events, so the same message can
  arrive twice. Messages are keyed on (channel, ts) and a duplicate is dropped
  rather than doubling up in the transcript.
* **Handlers acknowledge fast.** Slack times out a slash command in 3 seconds,
  but a pipeline run takes minutes, so commands acknowledge immediately and the
  run continues in the background.

Captured messages, runs and approvals live in the in-memory store shared with
the dashboard API (the listener runs inside the API process), so a restart
forgets them — the bot only sees messages sent while it is running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError

from app.config import settings
from app.models import (
    Approval,
    ApprovalDecision,
    ArtifactKind,
    Run,
    RunStatus,
    SlackMessage,
    Stage,
    StageKind,
    StageStatus,
)
from app.orchestrator import engine
from app.store import store

log = logging.getLogger(__name__)

#: Message subtypes that are not conversation: joins, edits, deletions, and the
#: bot's own posts. Capturing these would pollute the requirements transcript.
IGNORED_SUBTYPES = {
    "bot_message",
    "message_changed",
    "message_deleted",
    "channel_join",
    "channel_leave",
    "channel_topic",
    "channel_purpose",
    "channel_name",
    "thread_broadcast",
}

HELP = (
    "*PM Agent*\n"
    "• `/pm start` — read this conversation and start planning\n"
    "• `/pm status` — where the current run has got to\n"
    "• `/pm help` — this message\n\n"
    "Discuss what you want built, then run `/pm start`. "
    "I will extract the requirements and come back with a plan to approve."
)


def build_app() -> AsyncApp:
    if not settings.slack_bot_token or not settings.slack_app_token:
        raise RuntimeError(
            "SLACK_BOT_TOKEN and SLACK_APP_TOKEN must both be set. Run `make check`."
        )
    return AsyncApp(token=settings.slack_bot_token)


app = build_app() if settings.slack_bot_token and settings.slack_app_token else None

#: user id -> display name. Resolved lazily; Slack rate-limits users.info and
#: the same handful of people speak throughout a conversation.
_NAME_CACHE: dict[str, str] = {}


async def resolve_user_name(client, user_id: str | None) -> str | None:
    """A human-readable name for a Slack user id.

    Names matter to the pipeline: the transcript reads as people talking, which
    is what lets the model work out who wants what.
    """
    if not user_id:
        return None
    if user_id in _NAME_CACHE:
        return _NAME_CACHE[user_id]
    try:
        response = await client.users_info(user=user_id)
        profile = response["user"]
        name = (
            profile.get("profile", {}).get("display_name")
            or profile.get("profile", {}).get("real_name")
            or profile.get("name")
            or user_id
        )
    except SlackApiError as exc:
        # Not fatal: the user id still identifies the speaker.
        log.warning("could not resolve user %s: %s", user_id, exc)
        name = user_id
    _NAME_CACHE[user_id] = name
    return name


async def capture_message(event: dict, client) -> bool:
    """Store one Slack message. Returns False if it was ignored or a duplicate."""
    if event.get("subtype") in IGNORED_SUBTYPES or event.get("bot_id"):
        return False

    text = (event.get("text") or "").strip()
    if not text:
        return False

    name = await resolve_user_name(client, event.get("user"))

    # Slack redelivers events; (channel, ts) is unique, so a False here is the
    # same message arriving twice rather than an error.
    return store.add_message(
        SlackMessage(
            channel_id=event["channel"],
            ts=event["ts"],
            thread_ts=event.get("thread_ts"),
            user_id=event.get("user"),
            user_name=name,
            text=text,
            is_bot=False,
        )
    )


class NotInChannel(RuntimeError):
    """The bot is not a member of the channel, so it cannot post there."""


async def post(client, channel: str, text: str, thread_ts: str | None = None) -> None:
    """Post to a channel.

    Raises :class:`NotInChannel` rather than logging it, because that failure
    has a fix the user can apply and they will never read the log.
    """
    try:
        await client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    except SlackApiError as exc:
        error = (exc.response or {}).get("error") if hasattr(exc, "response") else None
        if error in ("not_in_channel", "channel_not_found"):
            raise NotInChannel(channel) from exc
        log.error("could not post to %s: %s", channel, exc)


async def post_blocks(
    client, channel: str, text: str, blocks: list[dict], thread_ts: str | None = None
) -> dict:
    """Post an interactive Block Kit message, preserving the membership diagnosis."""
    try:
        return await client.chat_postMessage(
            channel=channel, text=text, blocks=blocks, thread_ts=thread_ts
        )
    except SlackApiError as exc:
        error = (exc.response or {}).get("error") if hasattr(exc, "response") else None
        if error in ("not_in_channel", "channel_not_found"):
            raise NotInChannel(channel) from exc
        raise


INVITE_ME = (
    ":wave: I am not in this channel yet, so I cannot read the conversation or reply in it.\n\n"
    "Type `/invite @PM Agent` here, then run `/pm start` again."
)

NOTHING_TO_READ = (
    ":thinking_face: I have not seen any conversation in this channel yet.\n\n"
    "I only receive messages sent *after* I joined, so if you have just invited me, "
    "discuss what you want built and then run `/pm start` again."
)


def explain_failure(exc: Exception) -> str:
    """Turn an exception into something the person in Slack can act on.

    The infrastructure failures all look the same from Slack — a command that
    never answers — so name the likely cause and the command that fixes it.
    """
    text = str(exc)

    if "no quota or credit" in text:
        return (
            ":x: The OpenAI account has no credit left.\n"
            "Add billing to the account behind `OPENAI_API_KEY`, then try again."
        )
    if "rate limit" in text.lower():
        return (
            ":x: The model's rate limit is used up for now.\n"
            "Wait a minute for the window to reset, then try again."
        )
    if "(network)" in text:
        return (
            ":x: I could not reach the model — the connection kept dropping.\n"
            "This is usually the network rather than the run. Try `/pm start` again."
        )
    if "OPENAI_API_KEY" in text:
        return ":x: The model API key is missing or was rejected. Check `OPENAI_API_KEY`."

    return f":x: Something went wrong.\n```{type(exc).__name__}: {text[:400]}```"


async def active_run(channel_id: str, thread_ts: str | None) -> Run | None:
    """The most recent run for this conversation, if any."""
    return store.latest_run_for(channel_id, thread_ts)


#: What each stage is doing, posted as it finishes. A full run takes minutes,
#: and silence in the channel is indistinguishable from a crash.
STAGE_DONE = {
    StageKind.INGEST: ":mag: Read the conversation and extracted the requirements.",
    StageKind.PLAN: ":clipboard: Drafted the project plan.",
    StageKind.WBS: ":card_index_dividers: Built the work breakdown and pushed it to ClickUp.",
    StageKind.DESIGN: ":triangular_ruler: Produced the system design diagrams.",
    StageKind.PROTOTYPE: ":rocket: Generated the prototype, committed it, and deployed it.",
    StageKind.DONE: ":checkered_flag: Finished.",
}


def _progress_reporter(client, channel: str, thread_ts: str | None):
    """An engine observer that narrates each completed stage into the channel."""

    async def report(run: Run, stage: Stage) -> None:
        if stage.status == StageStatus.FAILED:
            return  # the failure itself is reported once, by the caller
        note = STAGE_DONE.get(stage.kind)
        if note and stage.status == StageStatus.COMPLETE:
            await post(client, channel, note, thread_ts)

    return report


async def _revise_plan(
    run_id: uuid.UUID, channel: str, thread_ts: str | None, feedback: str, client
) -> None:
    """Re-run PLAN with the reviewer's feedback and post the revision for review."""
    try:
        run = await engine.request_changes(
            run_id,
            StageKind.PLAN,
            feedback,
            on_stage=_progress_reporter(client, channel, thread_ts),
        )
        if _awaiting_plan_approval(run):
            await post_plan_approval(client, channel, run, thread_ts)
            return
        message = describe(run)
    except Exception as exc:  # noqa: BLE001 - the user must hear about any failure
        log.exception("revising the plan for run %s failed", run_id)
        message = explain_failure(exc)

    await post(client, channel, message, thread_ts)


async def run_pipeline(run_id: uuid.UUID, channel: str, thread_ts: str | None, client) -> None:
    """Drive a run to its next stopping point, reporting progress in Slack.

    Runs detached from the command handler, which has already acknowledged —
    a pipeline takes minutes and Slack gives a slash command three seconds.
    """
    try:
        run = await engine.advance(run_id, on_stage=_progress_reporter(client, channel, thread_ts))
        if _awaiting_plan_approval(run):
            await post_plan_approval(client, channel, run, thread_ts)
            return
        message = describe(run)
    except Exception as exc:  # noqa: BLE001 - the user must hear about any failure
        log.exception("run %s failed", run_id)
        message = explain_failure(exc)

    await post(client, channel, message, thread_ts)


def _awaiting_plan_approval(run: Run) -> bool:
    return any(
        stage.kind == StageKind.PLAN and stage.status == StageStatus.AWAITING_APPROVAL
        for stage in run.stages
    )


def _latest_plan(run: Run) -> dict:
    plans = [artifact for artifact in run.artifacts if artifact.kind == ArtifactKind.PLAN]
    if not plans:
        raise RuntimeError("PLAN is awaiting approval but no plan artifact was stored")
    latest = max(plans, key=lambda artifact: (artifact.version, artifact.created_at))
    return latest.data or {}


def _plan_blocks(run: Run) -> list[dict]:
    """A compact plan review that stays below Slack's Block Kit limits."""
    plan = _latest_plan(run)
    phases = plan.get("phases", [])
    risks = plan.get("risks", [])
    phase_lines = [
        f"• *{phase.get('name', 'Phase')}* — {phase.get('estimated_duration_days', '?')} days"
        for phase in phases[:6]
    ]
    risk_lines = [f"• {risk.get('title', 'Risk')}" for risk in risks[:4]]
    context = f"Estimate: *{plan.get('estimated_total_days', '?')} working days*"
    if plan.get("open_questions"):
        context += f" · {len(plan['open_questions'])} open question(s)"
    value = json.dumps({"run_id": str(run.id), "stage": StageKind.PLAN.value})
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Project plan ready"}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": plan.get("executive_summary", "")[:2900]},
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": "*Delivery phases*\n" + ("\n".join(phase_lines) or "Not specified"),
                },
                {
                    "type": "mrkdwn",
                    "text": "*Key risks*\n" + ("\n".join(risk_lines) or "None identified"),
                },
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "plan_approve",
                    "text": {"type": "plain_text", "text": "Approve plan"},
                    "style": "primary",
                    "value": value,
                },
                {
                    "type": "button",
                    "action_id": "plan_request_changes",
                    "text": {"type": "plain_text", "text": "Request changes"},
                    "value": value,
                },
            ],
        },
    ]


async def post_plan_approval(client, channel: str, run: Run, thread_ts: str | None) -> None:
    await post_blocks(
        client,
        channel,
        "Project plan ready for review. Approve it or request changes.",
        _plan_blocks(run),
        thread_ts,
    )


def describe(run: Run) -> str:
    """A Slack-readable summary of where a run has got to."""
    done = [s for s in run.stages if s.status == StageStatus.COMPLETE]
    failed = next((s for s in run.stages if s.status == StageStatus.FAILED), None)
    waiting = next((s for s in run.stages if s.status == StageStatus.AWAITING_APPROVAL), None)

    header = f"*{run.title}*"

    if failed is not None:
        return f"{header}\n:x: Stopped at *{failed.kind}*.\n```{failed.error}```"

    if waiting is not None:
        return (
            f"{header}\n:hourglass: *{waiting.kind}* is ready for your review.\n"
            f"_{len(done)} of {len(run.stages)} stages complete._"
        )

    if run.status == RunStatus.COMPLETE:
        links = [
            f"• <{url}|{label}>"
            for label, url in (
                ("ClickUp project", run.clickup_url),
                ("GitHub repo", run.github_repo_url),
                ("Live prototype", run.vercel_url),
            )
            if url
        ]
        body = "\n".join(links) if links else "_No external artifacts were produced._"
        return f"{header}\n:white_check_mark: Finished.\n{body}"

    stage = run.current_stage or "?"
    return f"{header}\n:gear: Working on *{stage}* ({len(done)} of {len(run.stages)} done)."


def register(app: AsyncApp) -> None:
    """Attach every listener. Separate from module import so tests can drive it."""

    @app.event("message")
    async def on_message(event, client):
        captured = await capture_message(event, client)
        if captured:
            log.debug("captured message %s in %s", event.get("ts"), event.get("channel"))

    @app.event("app_mention")
    async def on_mention(event, client):
        # A mention is still conversation, so capture it, then point at /pm.
        await capture_message(event, client)
        await post(
            client,
            event["channel"],
            HELP,
            event.get("thread_ts"),
        )

    @app.action("plan_approve")
    async def on_plan_approve(ack, body, client):
        await ack()
        action = body["actions"][0]
        payload = json.loads(action["value"])
        run_id = uuid.UUID(payload["run_id"])
        user = body.get("user", {}).get("username") or body.get("user", {}).get("id")
        channel = body["channel"]["id"]
        message_ts = body.get("message", {}).get("ts")
        try:
            run = await engine.load_run(run_id)
            if run is None:
                # Runs live in memory, so this is also what a restart looks like.
                raise ValueError("This plan run no longer exists.")
            stage = next(stage for stage in run.stages if stage.kind == StageKind.PLAN)
            run = await engine.mark_stage_approved(run.id, StageKind.PLAN)
            run.approvals.append(
                Approval(
                    run_id=run.id,
                    stage_id=stage.id,
                    decision=ApprovalDecision.APPROVED,
                    decided_by=user,
                    slack_message_ts=message_ts,
                )
            )
            thread_ts = run.slack_thread_ts
            title = run.title
            await post(client, channel, f":white_check_mark: *{title}* plan approved by {user}.")
            # The remaining four stages take minutes. Continue in the background
            # so the button does not sit spinning while ClickUp and Vercel work.
            asyncio.create_task(run_pipeline(run_id, channel, thread_ts, client))
        except Exception as exc:  # noqa: BLE001
            log.exception("plan approval failed")
            await post(client, channel, explain_failure(exc))

    @app.action("plan_request_changes")
    async def on_plan_request_changes(ack, body, client):
        await ack()
        action = body["actions"][0]
        await client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "plan_feedback",
                "private_metadata": action["value"],
                "title": {"type": "plain_text", "text": "Revise project plan"},
                "submit": {"type": "plain_text", "text": "Send feedback"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "feedback_block",
                        "label": {"type": "plain_text", "text": "What should change?"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "feedback",
                            "multiline": True,
                            "min_length": 3,
                            "placeholder": {
                                "type": "plain_text",
                                "text": "For example: add a pilot phase.",
                            },
                        },
                    }
                ],
            },
        )

    @app.view("plan_feedback")
    async def on_plan_feedback(ack, body, client):
        await ack()
        payload = json.loads(body["view"]["private_metadata"])
        run_id = uuid.UUID(payload["run_id"])
        feedback = body["view"]["state"]["values"]["feedback_block"]["feedback"]["value"].strip()
        user = body.get("user", {}).get("username") or body.get("user", {}).get("id")
        try:
            run = await engine.load_run(run_id)
            if run is None:
                raise ValueError("This plan run no longer exists.")
            stage = next(stage for stage in run.stages if stage.kind == StageKind.PLAN)
            run.approvals.append(
                Approval(
                    run_id=run.id,
                    stage_id=stage.id,
                    decision=ApprovalDecision.CHANGES_REQUESTED,
                    feedback=feedback,
                    decided_by=user,
                )
            )
            channel = run.slack_channel_id
            thread_ts = run.slack_thread_ts
            if not channel:
                raise ValueError("This run has no Slack channel.")
            await post(
                client,
                channel,
                ":arrows_counterclockwise: Revising the project plan from your feedback…",
                thread_ts,
            )
            asyncio.create_task(_revise_plan(run_id, channel, thread_ts, feedback, client))
        except Exception as exc:  # noqa: BLE001
            log.exception("plan feedback submission failed")
            # A modal has no durable response destination. A best-effort DM is
            # overkill for v1; write the error to the log and keep the run as is.
            raise exc

    @app.command("/pm")
    async def on_command(ack, command, client, respond):
        # Acknowledge inside Slack's three-second window before doing anything.
        await ack()

        action = (command.get("text") or "").strip().split(" ")[0].lower() or "help"
        channel = command["channel_id"]
        # A slash command is not itself in a thread, so runs started this way
        # read the whole channel.
        thread_ts = None

        # Every command reports its own failure into the channel. Without this,
        # an exception here reaches the user as Slack's generic "the app did not
        # respond", which is indistinguishable whether the cause is a missing
        # API key, exhausted model quota, or a bug — and says nothing about
        # which. The listener must also survive: one bad command should not take
        # the process down.
        try:
            if action == "start":
                await _start(channel, thread_ts, command, client)
            elif action == "status":
                await _status(channel, thread_ts, client)
            elif action == "cancel":
                await _cancel(channel, thread_ts, client)
            else:
                await post(client, channel, HELP)
        except NotInChannel:
            # Cannot post to the channel, so answer over the command's own
            # response URL instead. This is the one failure that is otherwise
            # completely silent — the user sees nothing at all.
            log.warning("not a member of %s; replying privately", channel)
            await respond(INVITE_ME)
        except Exception as exc:  # noqa: BLE001 - the user must see what went wrong
            log.exception("/pm %s failed", action)
            explanation = explain_failure(exc)
            try:
                await post(client, channel, explanation, thread_ts)
            except NotInChannel:
                await respond(explanation)


async def _start(channel: str, thread_ts: str | None, command: dict, client) -> None:
    existing = await active_run(channel, thread_ts)
    if existing is not None and existing.status in (
        RunStatus.RUNNING,
        RunStatus.AWAITING_APPROVAL,
    ):
        await post(
            client,
            channel,
            f"A run is already in progress here — *{existing.title}*. "
            "Use `/pm status`, or `/pm cancel` to abandon it.",
            thread_ts,
        )
        return

    message_count = len(store.messages_in(channel))

    if message_count == 0:
        # The bot only receives messages from channels it is in, so an empty
        # transcript almost always means it was never invited — say that here
        # rather than letting INGEST fail with the same diagnosis a minute later.
        await post(client, channel, NOTHING_TO_READ, thread_ts)
        return

    # Post before creating the run. If the bot is not in the channel this raises
    # NotInChannel and the command handler explains the fix — creating the run
    # first would leave a failed run behind for a problem that is not the run's.
    await post(
        client,
        channel,
        f":mag: Reading {message_count} message(s) from this channel and extracting "
        "requirements. This takes a moment.",
        thread_ts,
    )

    run = await engine.create_run(
        slack_channel_id=channel,
        slack_thread_ts=thread_ts,
        started_by=command.get("user_name") or command.get("user_id"),
    )

    # Detached: the command handler must return, the pipeline takes minutes.
    asyncio.create_task(run_pipeline(run.id, channel, thread_ts, client))


async def _status(channel: str, thread_ts: str | None, client) -> None:
    run = await active_run(channel, thread_ts)
    if run is None:
        await post(client, channel, "No runs here yet. Use `/pm start`.", thread_ts)
        return
    await post(client, channel, describe(run), thread_ts)


async def _cancel(channel: str, thread_ts: str | None, client) -> None:
    run = await active_run(channel, thread_ts)
    if run is None:
        await post(client, channel, "There is no run here to cancel.", thread_ts)
        return
    run.status = RunStatus.CANCELLED
    await post(client, channel, f"Cancelled *{run.title}*.", thread_ts)


async def connect_socket_mode() -> AsyncSocketModeHandler:
    """Open the Socket Mode connection and return the handler without blocking.

    Called from the API's lifespan, so the listener shares the process — and
    the in-memory store — with the dashboard. The caller closes the handler
    on shutdown.
    """
    if app is None:
        raise RuntimeError("Slack tokens are not configured; run `make check`.")
    register(app)
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    log.info("connecting to Slack over Socket Mode")
    await handler.connect_async()
    return handler
