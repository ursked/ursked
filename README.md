# ursked — Community Edition

A self-hosted platform for **employee scheduling, leave, attendance and
payroll** — the roster all the way to the payslip, in one place.

This is the **Community Edition**: a single-organization, self-hosted build. It
has no marketing page, no self-service sign-up, and no multi-tenant / billing
console. You run it for your own organization.

> **Source available, not open source.** ursked is licensed under the
> [Elastic License 2.0](LICENSE). You can run and modify it for your own use,
> but you may not offer it to third parties as a hosted or managed service. See
> [NOTICE](NOTICE) and [TRADEMARK.md](TRADEMARK.md).

## Requirements

- A Linux host with **Docker** and the **Docker Compose plugin**.
- ~2 GB RAM free.
- Optionally, a reverse proxy (Caddy, nginx, Traefik) to terminate HTTPS in
  front of the app.

## Quickstart

```bash
# 1. Get the code
git clone https://github.com/ursked/ursked.git
cd ursked

# 2. Configure
cp .env.example .env

# Generate the two required secrets and paste them into .env
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(64))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(24))"

# Edit .env: set the passwords above, and your ORG_NAME / ADMIN_EMAIL.
# Leave ADMIN_PASSWORD blank to have one generated for you.
nano .env

# 3. Start
docker compose up -d
```

On first boot the backend runs the database migrations and then creates your
**one organization and one administrator**.

### Get your admin password

If you left `ADMIN_PASSWORD` blank, it was generated and printed **once** in the
backend logs:

```bash
docker compose logs backend | grep -A6 "first-run setup complete"
```

You will see a banner with your organization name, the admin email, and the
generated password. Copy it now.

### Sign in

Open the app (default `http://127.0.0.1:3000`, or your proxied domain), sign in
with the admin email and that password. **You will be required to change the
password on first sign-in.**

## Running behind HTTPS

Keep `COOKIE_SECURE=true` and put a TLS-terminating reverse proxy in front of
the frontend's `127.0.0.1:3000`. The browser only ever talks to the frontend
origin; it proxies `/api/*` to the backend internally, so no CORS setup is
needed. For a plain-HTTP trial on localhost only, set `COOKIE_SECURE=false`.

## Updating

```bash
git pull
docker compose build
docker compose up -d
```

Migrations run automatically on start. The seed step is skipped once your
organization exists, so your data is never touched.

## Common commands

```bash
docker compose ps                 # service status
docker compose logs -f backend    # follow API logs
docker compose down               # stop (data is kept in named volumes)
```

## Backups

Your data lives in the `postgres_data` Docker volume. Back it up with a standard
`pg_dump`:

```bash
docker compose exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql
```

## License

[Elastic License 2.0](LICENSE) · Copyright (c) 2026 Jan Roldan Hernandez.
"ursked" is a trademark of Jan Roldan Hernandez; forks must rename
(see [TRADEMARK.md](TRADEMARK.md)).
