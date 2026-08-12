<div align="center">

<img src="frontend/public/logo/urskedlogo.png" alt="ursked" width="360">

### The employee roster, all the way to the payslip — self-hosted.

**ursked** is a workforce-management platform for scheduling, leave, attendance
and payroll. This is the **Community Edition**: a single-organization build you
run on your own server, with your data on your own infrastructure.

[Quickstart](#quickstart) · [What it does](#what-it-does) · [Screenshots](#screenshots) · [Security](#security--access-control) · [License](#license)

![Weekly schedule](frontend/public/screenshots/schedules.png)

</div>

---

> **Source available, not open source.** ursked is licensed under the
> [Elastic License 2.0](LICENSE). You may run and modify it for your own
> organization, but you may **not** offer it to third parties as a hosted or
> managed service. See [NOTICE](NOTICE) and [TRADEMARK.md](TRADEMARK.md).

## What it does

ursked replaces the spreadsheet-and-email workflow most teams use to run their
staff. It covers the whole cycle in one place, with role-aware access so people
only see and do what they should.

### Scheduling
- Weekly roster grid with multiple shift patterns and work arrangements
  (on-site, WFH, hybrid).
- Draft rosters, then publish when they're ready — nothing is visible to staff
  until you say so.
- One-click week duplication, per-employee display timezones, and guardrails
  against over-scheduling.
- Shift change requests and swaps that route through approval.

### Leave management
- Configurable leave types with balances and accrual.
- Multi-level, priority-based approval chains — route requests to the right
  approvers, with fallbacks and exclusions.
- Live balance tracking so requesters and approvers see what's available.

### Attendance & overtime
- Track clock times, tardiness and overtime against policy rules.
- Policy-driven exceptions are flagged automatically.
- Night-differential and holiday handling built in.

### Payroll & compensation
- Salary grades with effective-dated raises.
- Bonuses, allowances and deductions as an auditable ledger.
- Run payroll per period; figures are denominated in your organization's master
  currency.
- Sensitive salary data sits behind an approval-based enrollment gate.

### Organization
- Model your company down to Company → Division → Department → Section → Team —
  the hierarchy is configurable to any depth.
- Assign heads and deputies; drive schedule visibility and approval routing from
  the tree.
- List view and an interactive org chart.

### Analytics
- Monthly trends for overtime, leave and attendance to help you staff smarter.

## Screenshots

<table>
  <tr>
    <td width="50%"><b>Weekly schedule</b><br>
      <img src="frontend/public/screenshots/schedules.png" alt="Weekly schedule grid"></td>
    <td width="50%"><b>Payroll &amp; salaries</b><br>
      <img src="frontend/public/screenshots/payroll.png" alt="Employee salaries and payroll"></td>
  </tr>
  <tr>
    <td width="50%"><b>Organization chart</b><br>
      <img src="frontend/public/screenshots/org.png" alt="Organization chart"></td>
    <td width="50%"><b>Dashboard</b><br>
      <img src="frontend/public/screenshots/dashboard.png" alt="Dashboard overview"></td>
  </tr>
</table>

## How it's built

| Layer | Stack |
|---|---|
| Backend | FastAPI · SQLAlchemy (async) · Alembic migrations |
| Frontend | Next.js 14 (App Router) · Tailwind CSS |
| Data | PostgreSQL · Redis |
| Delivery | Docker images for `backend` and `frontend`, orchestrated by Docker Compose |

The browser only ever talks to the frontend origin; it proxies `/api/*` to the
backend internally, so auth cookies stay first-party and there is no CORS to
configure for the default deployment.

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

# Generate the required secrets and paste them into .env
python3 -c "import secrets; print('JWT_SECRET_KEY=' + secrets.token_urlsafe(64))"
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
python3 -c "import secrets; print('REDIS_PASSWORD=' + secrets.token_urlsafe(24))"

# Edit .env: set the secrets above, and your ORG_NAME / ADMIN_EMAIL.
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

By default the app serves on all interfaces, so open `http://<this-host>:3000`
on your LAN, `http://127.0.0.1:3000` locally, or your proxied domain. Sign in
with the admin email and that password. **You will be required to change the
password on first sign-in.**

## Running behind HTTPS

For production, keep `ENVIRONMENT=production` and `COOKIE_SECURE=true`, and put a
TLS-terminating reverse proxy in front of the frontend's `:3000`. The browser
only ever talks to the frontend origin; it proxies `/api/*` to the backend
internally, so no CORS setup is needed.

### Plain-HTTP trial (no proxy)

Secure cookies require HTTPS, so production refuses to start without them. To try
the app over plain HTTP on a **trusted network** (localhost or a LAN IP, no
reverse proxy), set both of these in `.env`:

```
COOKIE_SECURE=false
ALLOW_INSECURE_TRANSPORT=true
```

`ENVIRONMENT` stays `production`. The opt-in downgrades only the two transport
checks (Secure cookies and `http://` CORS origins) to loud startup warnings;
`DEBUG` and wildcard CORS remain hard-blocked. **Never enable
`ALLOW_INSECURE_TRANSPORT` on anything reachable from the internet** — put TLS in
front and leave it `false`.

## Security & access control

- **Role-based access control** — a module-and-action permission matrix across
  seven built-in roles governs what each user can see and do.
- **Two-factor authentication** — TOTP, SMS, or email.
- **Salary access gating** — payroll figures are only visible to users
  explicitly enrolled through an approval flow.
- **Hardened startup** — the backend refuses to boot in production with a weak
  JWT secret, `DEBUG` on, wildcard CORS, or insecure cookies (see the trial
  opt-in above for the one deliberate, network-scoped exception).
- **CSRF protection** on state-changing requests, with security response headers
  applied globally.

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
