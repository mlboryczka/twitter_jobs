# twitter_jobs

Personal X (Twitter) job posting intelligence. Monitors your home timeline for
openings in corporate development, strategy/strategic finance, BD, operations,
and chief-of-staff roles. Classifies with Claude Haiku. Surfaces in a local
dashboard.

Single-user by design. Runs 24/7 on a small VPS.

## Stack

- Python 3.12+, async
- FastAPI + Jinja2 + HTMX + Pico.css (no build step)
- APScheduler (in-process)
- PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic
- X API v2 via OAuth 2.0 PKCE (scopes `tweet.read users.read bookmark.read offline.access`)
- Anthropic SDK, `claude-haiku-4-5` for classification with tool-use structured output
- systemd + Caddy on Ubuntu 24.04

## Bootstrap (VPS)

1. Spin up an Ubuntu 24.04 VPS.
2. Point a domain at the VPS IP (A record).
3. Register an X developer app. Enable OAuth 2.0. Add callback URLs:
   - `http://localhost:8765/callback` (for local OAuth exchange)
   Copy the client ID and client secret.
4. Clone this repo into `/opt/twitter_jobs`.
5. Run `sudo bash deploy/bootstrap.sh`. It installs Postgres 16, Caddy, uv,
   creates the `app` user, and creates the database.
6. `cp .env.example .env` and fill in every variable.
7. `uv sync` then `uv run alembic upgrade head`.
8. On your **local** machine (same X account), run
   `uv run python scripts/run_oauth_flow.py`. Follow the prompt. Copy the
   printed refresh token into the VPS `.env` as `X_REFRESH_TOKEN`.
9. Back on the VPS, run `uv run python scripts/smoke_test.py`. It should
   print your X username and confirm an api_calls row was written.
10. `sudo systemctl enable --now twitter_jobs`.
11. Drop `deploy/caddy/Caddyfile` into `/etc/caddy/Caddyfile` (edit the
    domain), then `sudo systemctl reload caddy`.
12. Visit `https://yourdomain.com`. Log in with the credentials you set in
    `.env` (`DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`).

## Local development

```bash
uv sync
cp .env.example .env     # fill in values
uv run alembic upgrade head
uv run python -m twitter_jobs.main
```

Dashboard: http://127.0.0.1:8000

## Useful commands

- `uv run python scripts/smoke_test.py` — verify X API auth and cost logging
- `uv run python scripts/prefilter_dry_run.py` — inspect prefilter quality
- `uv run python scripts/reclassify.py` — re-run the classifier on all matched tweets
- `uv run python scripts/build_eval_set.py` — export 50 random prefilter hits for manual labeling
- `uv run alembic revision --autogenerate -m "description"`
- `uv run alembic upgrade head`

## Design decisions made during build

Decisions are recorded here as they come up.

## Known limitations / future work

- No MCP server — planned for a later iteration.
- No email/Slack digest.
- No bookmark ingestion (separate tool planned).
- No multimodal (image) classification. Image-only job postings are flagged
  for manual review.
- Single-user. No multi-user support.
