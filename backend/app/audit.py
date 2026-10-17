"""A record of every model call and every external API call.

Two audiences. Debugging: when a stage fails, the audit log says whether the
model was even reached, how long it took, and which external call broke. And
the report: "the pipeline made 11 model calls totalling 47k tokens and 34 ClickUp
requests" is evidence, where a screenshot is an anecdote.

Collection uses a context variable rather than threading a logger through every
function. The engine opens a collector around a stage; anything that call stack
reaches — the LLM client, any integration — records into it without knowing the
engine exists. Outside a collector, recording is a no-op, so the same functions
stay usable from scripts and tests.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class AuditEntry:
    kind: str  # "llm" | "api"
    target: str  # model id, or "GitHub POST /git/trees"
    ok: bool = True
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    detail: dict | None = None
    error: str | None = None


@dataclass
class Collector:
    entries: list[AuditEntry] = field(default_factory=list)

    def add(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    @property
    def input_tokens(self) -> int:
        return sum(entry.input_tokens for entry in self.entries)

    @property
    def output_tokens(self) -> int:
        return sum(entry.output_tokens for entry in self.entries)


_current: ContextVar[Collector | None] = ContextVar("audit_collector", default=None)


@contextlib.contextmanager
def collecting() -> Iterator[Collector]:
    """Collect every call recorded within this block."""
    collector = Collector()
    token = _current.set(collector)
    try:
        yield collector
    finally:
        _current.reset(token)


def record(entry: AuditEntry) -> None:
    """Record a call, if anything is listening."""
    collector = _current.get()
    if collector is not None:
        collector.add(entry)


def record_llm(
    *,
    model: str,
    ok: bool,
    duration_ms: int,
    input_tokens: int = 0,
    output_tokens: int = 0,
    thought_tokens: int = 0,
    output_model: str | None = None,
    error: str | None = None,
) -> None:
    record(
        AuditEntry(
            kind="llm",
            target=model,
            ok=ok,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            detail={"schema": output_model, "thought_tokens": thought_tokens},
            error=error,
        )
    )


def record_api(
    *,
    service: str,
    method: str,
    url: str,
    status: int | None,
    ok: bool,
    duration_ms: int,
    attempts: int = 1,
    error: str | None = None,
) -> None:
    record(
        AuditEntry(
            kind="api",
            target=f"{service} {method} {_path_of(url)}"[:200],
            ok=ok,
            duration_ms=duration_ms,
            detail={"status": status, "attempts": attempts},
            error=error,
        )
    )


def _path_of(url: str) -> str:
    """The path part of a URL. Full URLs make the audit table unreadable."""
    without_scheme = url.split("://", 1)[-1]
    slash = without_scheme.find("/")
    return without_scheme[slash:] if slash != -1 else without_scheme
