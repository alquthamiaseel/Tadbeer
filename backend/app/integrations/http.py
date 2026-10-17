"""Shared HTTP behaviour for the external integrations.

ClickUp, GitHub and Vercel all rate-limit, all occasionally return a 5xx, and all
report failures in their own JSON shape. Without a common layer each
integration grows its own half-correct retry loop, and a run dies on a 429 that
asked to be retried in two seconds.

Two rules:

* **Honour ``Retry-After``.** Guessing a backoff when the server has told you
  the answer is how you get rate-limited a second time.
* **Fail with the provider's own message.** A stage failure is shown verbatim
  in Slack and the dashboard, so "ClickUp said: dependencies are disabled" is worth
  far more than "HTTP 402".
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

from app import audit
from app.orchestrator.base import StageFailed

log = logging.getLogger(__name__)

#: Statuses worth trying again. 403 is included because GitHub reports
#: secondary rate limits with it rather than 429.
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}

MAX_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 30.0


def _retry_after(response: httpx.Response) -> float | None:
    for header in ("retry-after", "x-ratelimit-reset"):
        value = response.headers.get(header)
        if not value:
            continue
        try:
            seconds = float(value)
        except ValueError:
            continue
        if header == "x-ratelimit-reset":
            # An absolute epoch second, not a duration.
            seconds = seconds - time.time()
        if 0 < seconds <= 300:
            return seconds
    return None


def _is_rate_limited(response: httpx.Response) -> bool:
    """A 403 is only a rate limit when the provider says so."""
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    body = response.text.lower()
    return "rate limit" in body or "secondary rate" in body


def error_message(service: str, response: httpx.Response) -> str:
    """The provider's own explanation, or the status if it did not give one."""
    detail = ""
    try:
        body = response.json()
    except ValueError:
        detail = response.text[:300]
    else:
        if isinstance(body, dict):
            # "err" is ClickUp's key.
            for key in ("message", "error", "err", "detail", "errors"):
                value = body.get(key)
                if isinstance(value, dict):
                    value = value.get("message") or value.get("code")
                if isinstance(value, list) and value:
                    first = value[0]
                    value = first.get("message") if isinstance(first, dict) else str(first)
                if value:
                    detail = str(value)
                    break
        if not detail:
            detail = str(body)[:300]
    return f"{service} returned {response.status_code}: {detail}"


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    service: str,
    json: dict | None = None,
    params: dict | None = None,
) -> dict:
    """One API call, retried on rate limits and transient errors.

    Raises :class:`StageFailed` with the provider's own message, which is what
    the user sees in Slack.
    """
    last: httpx.Response | None = None
    started = time.perf_counter()

    def _elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    for attempt in range(MAX_ATTEMPTS):
        response = await client.request(method, url, json=json, params=params)
        if not response.is_error:
            audit.record_api(
                service=service,
                method=method,
                url=url,
                status=response.status_code,
                ok=True,
                duration_ms=_elapsed(),
                attempts=attempt + 1,
            )
            body = response.json() if response.content else {}
            return body if isinstance(body, dict) else {"data": body}

        last = response
        retryable = response.status_code in RETRY_STATUSES and (
            response.status_code != 403 or _is_rate_limited(response)
        )
        if not retryable or attempt == MAX_ATTEMPTS - 1:
            break

        delay = _retry_after(response) or random.uniform(0, min(2**attempt, MAX_BACKOFF_SECONDS))
        log.warning(
            "%s %s %s -> %d, retrying in %.1fs (attempt %d/%d)",
            service,
            method,
            url,
            response.status_code,
            delay,
            attempt + 1,
            MAX_ATTEMPTS,
        )
        await asyncio.sleep(delay)

    assert last is not None
    message = error_message(service, last)
    audit.record_api(
        service=service,
        method=method,
        url=url,
        status=last.status_code,
        ok=False,
        duration_ms=_elapsed(),
        attempts=attempt + 1,
        error=message[:500],
    )
    raise StageFailed(message, retryable=last.status_code >= 500)
