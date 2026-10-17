.PHONY: help install check create-user api web dev seed e2e test fmt lint clean

# One process serves the dashboard API, the Slack listener and the ClickUp
# monitor, because pipeline state is held in memory. No --reload: a reload would restart the process and
# forget every run in progress.
API = uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

help:
	@echo "make install   install backend + frontend dependencies"
	@echo "make check     verify every API credential"
	@echo "make create-user u=NAME  add a dashboard login (or reset its password)"
	@echo "make api       run the backend: API + Slack listener + ClickUp monitor"
	@echo "make web       run the frontend only"
	@echo "make dev       run backend + frontend together"
	@echo "make seed      run the backend with a canned conversation loaded (c=CHANNEL_ID)"
	@echo "make e2e       run the full pipeline for real and check the result (c=CHANNEL_ID)"
	@echo "make test      run the backend test suite"
	@echo "make fmt       format and autofix"

install:
	cd backend && uv sync
	cd frontend && npm install

check:
	cd backend && uv run python -m scripts.check_creds $(ARGS)

create-user:
	@test -n "$(u)" || (echo "usage: make create-user u=USERNAME" && exit 1)
	cd backend && uv run python -m scripts.create_user --username $(u)

api:
	cd backend && $(API)

web:
	cd frontend && npm run dev

dev:
	@trap 'kill 0' EXIT; \
	( cd backend && $(API) ) & \
	( cd frontend && npm run dev ) & \
	wait

seed:
	@test -n "$(c)" || (echo "usage: make seed c=C0123456789" && exit 1)
	cd backend && SEED_CHANNEL=$(c) $(API)

e2e:
	@test -n "$(c)" || (echo "usage: make e2e c=C0123456789" && exit 1)
	cd backend && uv run python -m scripts.e2e --channel $(c)

test:
	cd backend && uv run pytest -q

fmt:
	cd backend && uv run ruff format . && uv run ruff check --fix .

lint:
	cd backend && uv run ruff check .

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.ruff_cache
