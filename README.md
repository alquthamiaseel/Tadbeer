# pm-fyp — Agentic AI Project Manager

An AI system that turns stakeholder conversation into delivered project artifacts, end to end,
with a human in the loop.

It listens in **Slack**, extracts requirements, drafts a project plan and asks for approval,
then expands the approved plan into a **Work Breakdown Structure pushed into ClickUp** (with
dependencies and constraints), generates **system design diagrams** as Mermaid, and finally
generates a **low-fidelity prototype** committed to **GitHub** and deployed live on **Vercel**.
A dashboard shows every stage, artifact, and approval in real time.

## Pipeline

```
Slack conversation
      │
      ▼
  1. INGEST     → structured requirements
  2. PLAN       → project plan ──── human approval in Slack ────┐
  3. WBS        → task tree + dependencies → ClickUp            │ feedback re-runs the stage
  4. DESIGN     → Mermaid use-case / architecture / ERD / seq   │
  5. PROTOTYPE  → static site → GitHub repo → Vercel deploy      │
  6. DONE       → dashboard summary + Slack recap ──────────────┘
```

Each stage is a single LLM call with a forced JSON schema, recording its output in shared
in-memory state before the next stage runs. Within a running process, a failed stage or rate
limit picks up from the last completed stage, and any individual stage can be re-run with
feedback.

**There is no database.** Pipeline state (runs, stages, artifacts, approvals, captured Slack
messages, the audit trail) lives in memory and **disappears when the backend restarts**. What
persists: the generated prototype and its diagrams, committed to GitHub (plus whatever was
pushed to ClickUp and deployed to Vercel), and dashboard logins in `users.json`, the only
local data file, which holds a salted password hash and nothing else.

## Architecture

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| LLM | OpenAI GPT (`gpt-4o-mini` by default) with strict structured output per stage |
| Slack | `slack-bolt` in Socket Mode — no public URL required |
| Jobs | In-process asyncio tasks; Slack listener and API share one process |
| State | In memory (lost on restart); dashboard account in `users.json` |
| Frontend | React 19 + Vite, Tailwind; username/password login against `users.json` |
| Monitoring | Background check of each published ClickUp project for deviations from the plan |

## Quick start

```bash
cp .env.example .env        # then fill in the tokens
make install                # install backend + frontend dependencies
make check                  # verify every API credential works
make create-user u=sara     # a dashboard login (asks for the password)
make dev                    # backend (API + Slack listener, one process) + dashboard
```

Open the dashboard at http://localhost:3000, then invite the bot to a Slack
channel, discuss what you want built, and run `/pm start`.

To rehearse without typing a conversation:

```bash
make seed c=C0123456789     # run the backend with a canned conversation in that channel
make e2e  c=C0123456789     # run all six stages for real and check the result
```

Full setup, including the Slack app and each token, is in
[docs/setup.md](docs/setup.md).

## Credentials required

See `.env.example` for where to obtain each one. `make check` verifies all of them before you
start; nothing else will work until it reports all-green.

| Service | Purpose |
|---|---|
| OpenAI | The LLM behind every pipeline stage (paid API key) |
| Slack | Conversation capture and approval buttons (Socket Mode) |
| ClickUp | Where the Work Breakdown Structure is published, then monitored |
| GitHub | Where the generated prototype is committed |
| Vercel | Where the generated prototype is deployed |

## Layout

```
backend/app/orchestrator/            the six-stage state machine
backend/app/orchestrator/stages/     one module per pipeline stage
backend/app/integrations/            Slack, ClickUp, GitHub, Vercel clients
backend/app/schemas/                 Pydantic models — also the LLM output schemas
backend/app/llm/                     OpenAI client and the strict-schema converter
backend/scripts/                     credential check, seed, end-to-end acceptance
frontend/                            React + Vite dashboard
docs/                                setup, architecture, requirements, demo script
```

## Documentation

| Document | What it covers |
|---|---|
| [docs/setup.md](docs/setup.md) | Getting every credential and running the system |
| [docs/architecture.md](docs/architecture.md) | How it works and why it is shaped this way |
| [docs/requirements.md](docs/requirements.md) | What the system must do, and how each is verified |
| [docs/api.md](docs/api.md) | The REST and event-stream API |
| [docs/demo.md](docs/demo.md) | The demonstration script, and what to do if a step fails |
| [docs/evaluation.md](docs/evaluation.md) | What works, what it costs, and the honest limitations |
