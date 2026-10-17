"""The process-wide, in-memory home of all pipeline state.

One :class:`Store` instance (``store``) is shared by everything in the process:
the Slack listener writes captured messages and drives runs, the engine mutates
runs and stages in place, and the dashboard API reads the same objects. That
only works because Slack and the API run in one process — see ``app.main``.

Deliberately not persisted. A restart starts from an empty store: runs, stages,
artifacts, approvals, captured Slack messages and the audit trail are all gone.
What must outlive the process is committed to GitHub by the PROTOTYPE stage.

No locking: everything runs on one asyncio event loop and no method awaits, so
each call is atomic with respect to other tasks.
"""

from __future__ import annotations

import uuid

from app.models import AuditLog, Run, SlackMessage, Stage


class Store:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Forget everything. Used by tests; a restart does the same implicitly."""
        self.runs: dict[uuid.UUID, Run] = {}
        #: Keyed on (channel, ts), which is what makes capture idempotent.
        self.messages: dict[tuple[str, str], SlackMessage] = {}
        self.audit: list[AuditLog] = []

    # --- runs --------------------------------------------------------------

    def add_run(self, run: Run) -> Run:
        self.runs[run.id] = run
        return run

    def get_run(self, run_id: uuid.UUID) -> Run | None:
        return self.runs.get(run_id)

    def list_runs(self, limit: int | None = None) -> list[Run]:
        """Newest first."""
        runs = sorted(self.runs.values(), key=lambda run: run.created_at, reverse=True)
        return runs[:limit] if limit is not None else runs

    def latest_run_for(self, channel_id: str, thread_ts: str | None) -> Run | None:
        """The most recent run started from this conversation, if any."""
        matching = [
            run
            for run in self.runs.values()
            if run.slack_channel_id == channel_id
            and (not thread_ts or run.slack_thread_ts == thread_ts)
        ]
        return max(matching, key=lambda run: run.created_at, default=None)

    def get_stage(self, stage_id: uuid.UUID) -> Stage | None:
        for run in self.runs.values():
            for stage in run.stages:
                if stage.id == stage_id:
                    return stage
        return None

    # --- Slack messages ----------------------------------------------------

    def add_message(self, message: SlackMessage) -> bool:
        """Store a message. False if the same (channel, ts) was already stored."""
        key = (message.channel_id, message.ts)
        if key in self.messages:
            return False
        self.messages[key] = message
        return True

    def messages_in(self, channel_id: str) -> list[SlackMessage]:
        return [m for m in self.messages.values() if m.channel_id == channel_id]

    def conversation_for(self, run: Run) -> list[SlackMessage]:
        """Human messages belonging to this run's conversation, oldest first.

        Matched on channel plus thread rather than on run_id, because messages
        are captured as they arrive and only claimed by a run afterwards.
        """
        if run.slack_channel_id:
            matching = [
                m
                for m in self.messages.values()
                if m.channel_id == run.slack_channel_id
                and (not run.slack_thread_ts or m.thread_ts == run.slack_thread_ts)
            ]
        else:
            matching = [m for m in self.messages.values() if m.run_id == run.id]
        return sorted((m for m in matching if not m.is_bot), key=lambda m: m.ts)

    def clear_channel(self, channel_id: str) -> None:
        for key in [key for key in self.messages if key[0] == channel_id]:
            del self.messages[key]

    # --- audit -------------------------------------------------------------

    def add_audit(self, entry: AuditLog) -> None:
        self.audit.append(entry)

    def audit_for(self, run_id: uuid.UUID) -> list[AuditLog]:
        return sorted(
            (entry for entry in self.audit if entry.run_id == run_id),
            key=lambda entry: entry.created_at,
        )


store = Store()
