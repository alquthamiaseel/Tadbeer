"""Verify every external credential before anything else runs.

    make check              # fast: read-only probes against all five APIs
    make check ARGS=--deep  # also proves ClickUp can actually link dependencies

The deep check exists because of a specific trap: **ClickUp task dependencies
belong to the Dependencies ClickApp, which a Space admin can switch off**, and
that fails at the point of linking rather than at authentication. A read-only
probe cannot tell the difference, so the deep check creates a throwaway folder,
links two tasks, and deletes it.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.config import settings

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

_COLOUR = {
    PASS: "\033[32m",
    FAIL: "\033[31m",
    WARN: "\033[33m",
    SKIP: "\033[90m",
}
_RESET = "\033[0m"

TIMEOUT = httpx.Timeout(20.0)


class Result:
    def __init__(self, service: str, status: str, detail: str, hint: str = "") -> None:
        self.service = service
        self.status = status
        self.detail = detail
        self.hint = hint

    def _with_hint(self, hint: str) -> Result:
        self.hint = hint
        return self


def missing(service: str, var: str) -> Result:
    return Result(service, FAIL, f"{var} is not set", f"Add {var} to .env (see .env.example)")


# --------------------------------------------------------------------------
# OpenAI
#
# A real generation, not just an auth ping: the failures that actually bite are
# a model the key cannot use and an account with no credit, and only a
# generation surfaces those.
# --------------------------------------------------------------------------
async def check_openai() -> Result:
    if not settings.openai_api_key:
        return missing("OpenAI", "OPENAI_API_KEY")._with_hint(
            "Create a key at https://platform.openai.com/api-keys"
        )
    try:
        from pydantic import BaseModel

        from app.llm.client import generate_structured

        class Ping(BaseModel):
            ok: bool

        result = await generate_structured(
            output_model=Ping,
            system="You verify connectivity. Answer exactly as instructed.",
            user="Set ok to true.",
            max_output_tokens=200,
            repair_attempts=0,
        )
        return Result(
            "OpenAI",
            PASS,
            f"{settings.llm_model} responded "
            f"({result.input_tokens} in / {result.output_tokens} out tokens)",
        )
    except Exception as exc:  # noqa: BLE001 - the point is to report any failure
        return Result(
            "OpenAI",
            FAIL,
            _short(exc),
            f"Check OPENAI_API_KEY, billing, and that LLM_MODEL={settings.llm_model} "
            "supports structured outputs",
        )


# --------------------------------------------------------------------------
# Slack — both tokens matter: the bot token posts, the app token opens the
# Socket Mode connection. A run fails at startup if either is wrong.
# --------------------------------------------------------------------------
async def check_slack() -> list[Result]:
    results: list[Result] = []

    if not settings.slack_bot_token:
        results.append(missing("Slack bot", "SLACK_BOT_TOKEN"))
    else:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(
                    "https://slack.com/api/auth.test",
                    headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                )
                body = r.json()
            if body.get("ok"):
                results.append(
                    Result(
                        "Slack bot",
                        PASS,
                        f"{body.get('user')} in workspace {body.get('team')}",
                    )
                )
            else:
                results.append(
                    Result(
                        "Slack bot",
                        FAIL,
                        body.get("error", "unknown error"),
                        "SLACK_BOT_TOKEN should start with xoxb- "
                        "(OAuth & Permissions -> Bot User OAuth Token)",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            results.append(Result("Slack bot", FAIL, _short(exc)))

    if not settings.slack_app_token:
        results.append(missing("Slack app", "SLACK_APP_TOKEN"))
    else:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(
                    "https://slack.com/api/apps.connections.open",
                    headers={"Authorization": f"Bearer {settings.slack_app_token}"},
                )
                body = r.json()
            if body.get("ok"):
                results.append(Result("Slack app", PASS, "Socket Mode connection available"))
            else:
                results.append(
                    Result(
                        "Slack app",
                        FAIL,
                        body.get("error", "unknown error"),
                        "SLACK_APP_TOKEN should start with xapp- and have the "
                        "connections:write scope (Basic Information -> App-Level Tokens)",
                    )
                )
        except Exception as exc:  # noqa: BLE001
            results.append(Result("Slack app", FAIL, _short(exc)))

    return results


# --------------------------------------------------------------------------
# ClickUp
# --------------------------------------------------------------------------
CLICKUP = "https://api.clickup.com/api/v2"


def _clickup_headers() -> dict[str, str]:
    # Personal tokens (pk_...) are sent bare, without a "Bearer" prefix.
    return {"Authorization": settings.clickup_api_token}


async def check_clickup(deep: bool) -> list[Result]:
    if not settings.clickup_enabled:
        # A deliberate choice, not a missing credential. Reporting it as a
        # failure would train you to ignore a red line in this table.
        return [
            Result(
                "ClickUp",
                SKIP,
                "CLICKUP_ENABLED is false — the WBS is built and stored, but not published",
            )
        ]
    if not settings.clickup_api_token:
        return [
            missing("ClickUp", "CLICKUP_API_TOKEN")._with_hint(
                "Create a personal token (pk_...) under ClickUp avatar -> Settings -> Apps"
            )
        ]
    if not settings.clickup_space_id:
        return [
            missing("ClickUp", "CLICKUP_SPACE_ID")._with_hint(
                "Open the Space in ClickUp; the URL ends /v/s/<SPACE_ID>"
            )
        ]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=_clickup_headers()) as client:
            r = await client.get(f"{CLICKUP}/space/{settings.clickup_space_id}")
    except Exception as exc:  # noqa: BLE001
        return [Result("ClickUp", FAIL, _short(exc))]
    if r.status_code != 200:
        return [
            Result(
                "ClickUp",
                FAIL,
                f"HTTP {r.status_code}: {_body(r)}",
                "Check CLICKUP_API_TOKEN, and that CLICKUP_SPACE_ID is a Space it can see",
            )
        ]
    space = r.json()
    results = [Result("ClickUp", PASS, f"space {space.get('name')!r}")]

    if deep:
        results.append(await _check_clickup_dependencies())
    else:
        dependencies_on = (space.get("features") or {}).get("dependencies", {}).get("enabled")
        results.append(
            Result(
                "ClickUp dependencies",
                WARN if dependencies_on is False else SKIP,
                "the Dependencies ClickApp is off in this Space"
                if dependencies_on is False
                else "not verified",
                "Run `make check ARGS=--deep` once to prove tasks can be linked",
            )
        )
    return results


async def _check_clickup_dependencies() -> Result:
    """Create a throwaway folder, link two tasks, delete it.

    Anything short of actually adding a dependency can't tell whether the
    Dependencies ClickApp is on for this Space.
    """
    folder_id: str | None = None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=_clickup_headers()) as client:
            r = await client.post(
                f"{CLICKUP}/space/{settings.clickup_space_id}/folder",
                json={"name": "Tadbeer credential check (safe to delete)"},
            )
            if r.status_code >= 300:
                return Result(
                    "ClickUp dependencies",
                    FAIL,
                    f"could not create a test folder: {_body(r)}",
                    "The token needs permission to create folders in this Space",
                )
            folder_id = r.json()["id"]
            lr = await client.post(f"{CLICKUP}/folder/{folder_id}/list", json={"name": "check"})
            if lr.status_code >= 300:
                return Result("ClickUp dependencies", FAIL, f"list create failed: {_body(lr)}")
            list_id = lr.json()["id"]

            task_ids = []
            for label in ("A", "B"):
                tr = await client.post(
                    f"{CLICKUP}/list/{list_id}/task", json={"name": f"check task {label}"}
                )
                if tr.status_code >= 300:
                    return Result("ClickUp dependencies", FAIL, f"task create failed: {_body(tr)}")
                task_ids.append(tr.json()["id"])

            dr = await client.post(
                f"{CLICKUP}/task/{task_ids[1]}/dependency", json={"depends_on": task_ids[0]}
            )
            if dr.status_code < 300:
                return Result("ClickUp dependencies", PASS, "task dependencies work in this Space")
            return Result(
                "ClickUp dependencies",
                FAIL,
                f"HTTP {dr.status_code}: {_body(dr)}",
                "Enable the Dependencies ClickApp: Space settings -> ClickApps -> Dependencies",
            )
    except Exception as exc:  # noqa: BLE001
        return Result("ClickUp dependencies", FAIL, _short(exc))
    finally:
        if folder_id:
            try:
                async with httpx.AsyncClient(timeout=TIMEOUT, headers=_clickup_headers()) as c:
                    await c.delete(f"{CLICKUP}/folder/{folder_id}")
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass


# --------------------------------------------------------------------------
# GitHub
# --------------------------------------------------------------------------
async def check_github() -> list[Result]:
    if not settings.github_token:
        return [missing("GitHub", "GITHUB_TOKEN")]
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {settings.github_token}",
                    "Accept": "application/vnd.github+json",
                },
            )
        if r.status_code != 200:
            return [
                Result(
                    "GitHub",
                    FAIL,
                    f"HTTP {r.status_code}: {_body(r)}",
                    "Create a fine-grained PAT with Administration and Contents "
                    "read/write at https://github.com/settings/personal-access-tokens",
                )
            ]
        login = r.json().get("login")
        results = [Result("GitHub", PASS, f"authenticated as {login}")]
        owner = settings.github_owner or login
        if not settings.github_owner:
            results.append(
                Result(
                    "GitHub owner",
                    WARN,
                    "GITHUB_OWNER is not set",
                    f"Generated repos will default to {login}; set it explicitly to be sure",
                )
            )
        else:
            results.append(Result("GitHub owner", PASS, f"repos will be created under {owner}"))
        return results
    except Exception as exc:  # noqa: BLE001
        return [Result("GitHub", FAIL, _short(exc))]


# --------------------------------------------------------------------------
# Vercel
# --------------------------------------------------------------------------
async def check_vercel() -> Result:
    if not settings.vercel_token:
        return missing("Vercel", "VERCEL_TOKEN")
    try:
        params = {"teamId": settings.vercel_team_id} if settings.vercel_team_id else None
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(
                "https://api.vercel.com/v2/user",
                headers={"Authorization": f"Bearer {settings.vercel_token}"},
                params=params,
            )
        if r.status_code != 200:
            return Result(
                "Vercel",
                FAIL,
                f"HTTP {r.status_code}: {_body(r)}",
                "Create a token at https://vercel.com/account/tokens",
            )
        user = r.json().get("user", {})
        return Result(
            "Vercel", PASS, f"authenticated as {user.get('username') or user.get('email')}"
        )
    except Exception as exc:  # noqa: BLE001
        return Result("Vercel", FAIL, _short(exc))


# --------------------------------------------------------------------------
# Users file
# --------------------------------------------------------------------------
async def check_users_file() -> Result:
    from app import users

    try:
        accounts = users.load_users()
    except users.UsersFileError as exc:
        return Result(
            "Users file",
            FAIL,
            _short(exc),
            "Fix users.json, or delete it to recreate the account from DASHBOARD_PASSWORD",
        )
    if (
        settings.dashboard_auth
        and not accounts
        and not users.password_configured(settings.dashboard_password)
    ):
        return Result(
            "Users file",
            FAIL,
            "DASHBOARD_AUTH is on but there is no account and no DASHBOARD_PASSWORD",
            "Set DASHBOARD_PASSWORD",
        )
    return Result("Users file", PASS, f"{settings.users_file.name}: {len(accounts)} account(s)")


# --------------------------------------------------------------------------
# Presentation
# --------------------------------------------------------------------------
def _short(exc: Exception, limit: int = 120) -> str:
    text = " ".join(str(exc).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _body(response: httpx.Response, limit: int = 120) -> str:
    text = " ".join(response.text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(results: list[Result]) -> None:
    width = max(len(r.service) for r in results)
    print()
    for r in results:
        colour = _COLOUR[r.status]
        print(f"  {colour}{r.status:<4}{_RESET}  {r.service:<{width}}  {r.detail}")
        if r.hint:
            print(f"        {' ' * width}  \033[90m{r.hint}{_RESET}")
    print()

    failures = [r for r in results if r.status == FAIL]
    warnings = [r for r in results if r.status == WARN]
    if failures:
        print(f"  \033[31m{len(failures)} check(s) failed.\033[0m Fix these before continuing.\n")
    elif warnings:
        print(f"  \033[33mAll required checks passed, {len(warnings)} warning(s).\033[0m\n")
    else:
        print("  \033[32mAll checks passed.\033[0m\n")


async def main() -> int:
    deep = "--deep" in sys.argv

    print("\n  pm-fyp credential check" + ("  (deep)" if deep else ""))

    (
        llm_result,
        slack_results,
        clickup_results,
        github_results,
        vercel_result,
        users_result,
    ) = await asyncio.gather(
        check_openai(),
        check_slack(),
        check_clickup(deep),
        check_github(),
        check_vercel(),
        check_users_file(),
    )

    results = [
        llm_result,
        *slack_results,
        *clickup_results,
        *github_results,
        vercel_result,
        users_result,
    ]
    render(results)
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
