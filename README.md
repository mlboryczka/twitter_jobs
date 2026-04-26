# twitter_jobs

Personal X (Twitter) job posting intelligence. Monitors your home timeline for
openings in five target roles — Corporate Development, Corporate Strategy /
Strategic Finance, Business Development, Operations / Business Operations, and
Chief of Staff — classifies them with Claude Haiku, and surfaces them in a
local dashboard.

Single-user by design. Runs 24/7 on a small VPS.

## Stack

- Python 3.12+, async
- FastAPI + Jinja2 + HTMX + Pico.css (no build step)
- APScheduler (in-process)
- PostgreSQL 16 + SQLAlchemy 2.0 (async) + Alembic
- X API v2 via OAuth 2.0 PKCE, scopes `tweet.read users.read bookmark.read offline.access`
- Anthropic SDK, `claude-sonnet-4-6` with tool-use structured output
- systemd + Caddy on Ubuntu 24.04

## Bootstrap (VPS)

1. Spin up an Ubuntu 24.04 VPS.
2. Point a domain at the VPS IP (A record).
3. Register an X developer app. Enable OAuth 2.0. Add callback URL
   `http://localhost:8765/callback` (used by the one-time OAuth script below).
   Copy the client ID and client secret.
4. Clone this repo into `/opt/twitter_jobs`.
5. Run `sudo bash deploy/bootstrap.sh`. It installs Postgres 16, Caddy, uv,
   creates the `app` user, and creates the database. Write down the printed
   database password.
6. `cp .env.example .env` and fill in every variable. Use the `DATABASE_URL`
   the bootstrap script prints.
7. `uv sync && uv run alembic upgrade head`.
8. On your **local** machine (logged in to the same X account), run
   `uv run python scripts/run_oauth_flow.py`. Follow the link in your browser.
   Copy the printed refresh token into the VPS `.env` as `X_REFRESH_TOKEN`.
9. On the VPS, run `uv run python scripts/smoke_test.py`. It should print
   your X username and confirm an `api_calls` row was written.
10. `sudo cp deploy/systemd/twitter_jobs.service /etc/systemd/system/`,
    `sudo systemctl daemon-reload`, `sudo systemctl enable --now twitter_jobs`.
11. `sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile` (edit the domain
    first), then `sudo systemctl reload caddy`.
12. Visit `https://yourdomain.com`. Log in with `DASHBOARD_USERNAME` /
    `DASHBOARD_PASSWORD` from `.env`.

## Local development

```bash
uv sync
cp .env.example .env      # fill in values
uv run alembic upgrade head
uv run python -m twitter_jobs.main
```

Dashboard: <http://127.0.0.1:8000>

## Useful commands

- `uv run python scripts/smoke_test.py` — verify X API auth and cost logging
- `uv run python scripts/prefilter_dry_run.py` — inspect prefilter quality
- `uv run python scripts/reclassify.py` — re-run the classifier on matched tweets
- `uv run python scripts/build_eval_set.py` — export 50 random prefilter hits for manual labeling
- `uv run alembic revision --autogenerate -m "description"` — new migration
- `uv run alembic upgrade head` — apply migrations

## Cost control

Every X API call is logged to `api_calls` with an estimated USD cost from
`src/twitter_jobs/x_api/pricing.py`. The `/health` endpoint reports cost
spent in the last 24 hours. The feed worker has a hard `MAX_PAGES_PER_RUN`
safety cap so a bug can't blow through budget.

## Classifier prompt

The prompt and few-shot examples live in
`src/twitter_jobs/classify/classifier.py`. Iterate there, then run
`scripts/reclassify.py` to re-label existing data without re-pulling from X.

## Design decisions made during build

- **Refresh token persistence.** X rotates refresh tokens on every use. We
  persist the newest one to `secrets/x_refresh_token` (file-based, mode 0600).
  The `.env` value is read only once at startup as a seed.
- **Numeric ID comparison.** Tweet IDs are stored as text (per the spec). To
  compare them correctly we use length-then-lexicographic ordering rather than
  raw string compare.
- **Safety cap on feed pulls.** Hardcoded at 10 pages per invocation. The X
  home-timeline max is ~800 tweets / 15 minutes; 10 pages × 100 = 1000 tweets
  which is comfortably above expected steady-state.
- **Dual-layer auth.** The FastAPI app enforces HTTP Basic auth using
  `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`. The Caddyfile ships without an
  extra `basicauth` block to avoid a double prompt — re-add one there if you
  want belt-and-braces.
- **Image-only job postings.** Not classified by Haiku (no multimodal in v1).
  A small heuristic in `feed_worker._should_flag_as_image` flags them to the
  review queue.

## Known limitations / future work

- No MCP server — planned for a later iteration.
- No email/Slack digest.
- No bookmark ingestion (separate tool planned).
- No multimodal (image) classification. Image-only job postings are flagged
  for manual review.
- Single-user. No multi-user support.
