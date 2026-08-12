#!/bin/sh
set -eu

# Bring the schema up to date before serving traffic. Without this the app can
# start against an older schema and fail at request time instead of at boot.
echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."

exec "$@"
