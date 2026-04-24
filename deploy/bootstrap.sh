#!/usr/bin/env bash
# Bootstrap script for a fresh Ubuntu 24.04 VPS.
#
# Installs: PostgreSQL 16, Caddy, uv. Creates the "app" user, the app
# directory at /opt/twitter_jobs, and a Postgres database + role.
#
# This script must run as root (use sudo). After it finishes, see the
# instructions it prints for the next manual steps.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Run as root (sudo bash deploy/bootstrap.sh)." >&2
    exit 1
fi

APP_USER=${APP_USER:-app}
APP_DIR=${APP_DIR:-/opt/twitter_jobs}
DB_NAME=${DB_NAME:-twitter_jobs}
DB_USER=${DB_USER:-twitter_jobs}
DB_PASSWORD=${DB_PASSWORD:-$(openssl rand -hex 16)}

echo "=== apt update ==="
apt-get update -y
apt-get install -y curl ca-certificates gnupg debian-keyring debian-archive-keyring apt-transport-https

echo "=== installing PostgreSQL 16 ==="
install -d /usr/share/postgresql-common/pgdg
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
. /etc/os-release
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list
apt-get update -y
apt-get install -y postgresql-16
systemctl enable --now postgresql

echo "=== installing Caddy ==="
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y
apt-get install -y caddy
systemctl enable --now caddy

echo "=== creating app user ==="
id "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"

echo "=== creating app directory at $APP_DIR ==="
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"

echo "=== installing uv for $APP_USER ==="
sudo -u "$APP_USER" bash -lc 'curl -LsSf https://astral.sh/uv/install.sh | sh'

echo "=== creating Postgres role and database ==="
sudo -u postgres psql <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
    END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
 WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec
SQL

echo ""
echo "=== Bootstrap complete ==="
echo "Postgres DB:   ${DB_NAME}"
echo "Postgres user: ${DB_USER}"
echo "Postgres pass: ${DB_PASSWORD}   <-- write this down"
echo "App user:      ${APP_USER}"
echo "App dir:       ${APP_DIR}"
echo ""
echo "Next steps (see README.md for details):"
echo "  1. sudo -u ${APP_USER} git clone <repo> ${APP_DIR}"
echo "  2. cp ${APP_DIR}/.env.example ${APP_DIR}/.env and fill it in"
echo "     DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@localhost:5432/${DB_NAME}"
echo "  3. sudo -u ${APP_USER} -i bash -lc 'cd ${APP_DIR} && uv sync && uv run alembic upgrade head'"
echo "  4. Run scripts/run_oauth_flow.py locally, paste X_REFRESH_TOKEN into .env"
echo "  5. sudo -u ${APP_USER} -i bash -lc 'cd ${APP_DIR} && uv run python scripts/smoke_test.py'"
echo "  6. sudo cp deploy/systemd/twitter_jobs.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now twitter_jobs"
echo "  7. sudo cp deploy/caddy/Caddyfile /etc/caddy/Caddyfile (edit the domain!) && sudo systemctl reload caddy"
