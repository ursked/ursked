#!/usr/bin/env bash
#
# Reset the admin password for a self-hosted ursked Community Edition install.
#
#   ./reset-admin-password.sh [new-password]
#
# If no password is given, one is generated and printed once (same as first boot).
# Run this from the directory containing your docker-compose.yml and .env.
#
# What it does:
#   1. Hashes the password with bcrypt inside the backend container.
#   2. Updates the user row via psql in the database container.
#   3. Sets must_change_password = true so the user is forced to change it.
#   4. Clears tokens_valid_from to sign out any existing sessions.
#
# The .env must be present (it supplies POSTGRES_USER, POSTGRES_DB, and
# ADMIN_EMAIL). If ADMIN_EMAIL is unset, defaults to admin@localhost.
set -euo pipefail

if [ ! -f .env ]; then
  echo "Error: no .env file in the current directory. Run this from your ursked install." >&2
  exit 1
fi

# shellcheck source=/dev/null
set -a; source .env; set +a

ADMIN=${ADMIN_EMAIL:-admin@localhost}
PG_USER=${POSTGRES_USER:-ursked}
PG_DB=${POSTGRES_DB:-ursked}

if [ -n "${1:-}" ]; then
  PASSWORD="$1"
else
  PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(12))" 2>/dev/null \
             || openssl rand -base64 12)
  echo
  echo "Generated password: $PASSWORD"
  echo "This is shown ONCE. Copy it now."
  echo
fi

# Hash with bcrypt inside the backend container (which has the library).
HASH=$(docker compose exec -T backend python -c "
import bcrypt, sys
pw = sys.stdin.read().strip()
print(bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
" <<< "$PASSWORD")

if [ -z "$HASH" ]; then
  echo "Error: could not generate password hash. Is the backend container running?" >&2
  exit 1
fi

# Update the database. Escape single quotes in the hash (bcrypt hashes contain $
# which is safe in single-quoted SQL, but the hash never contains single quotes).
docker compose exec -T db psql -U "$PG_USER" -d "$PG_DB" -c "
  UPDATE users
  SET password_hash = '$HASH',
      must_change_password = true,
      tokens_valid_from = NOW()
  WHERE email = '$ADMIN';
" >/dev/null

echo "Password reset for $ADMIN. They will be required to change it on next sign-in."
