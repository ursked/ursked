"""Admin mode: a sign-in session is either an employee session or an admin session

Revision ID: 067_admin_mode
Revises: 066_finance_confidentiality
Create Date: 2026-09-29

The owner's decision (2026-09): an administrator who is also an employee signs
in at two separate doors. The ordinary sign-in page always opens an EMPLOYEE
session, in which the tenant_admin role is dormant; the administrator sign-in
page opens an ADMIN session, which lapses after 30 idle minutes and 8 hours at
most. Which door a session came through has to be recorded on the server and
checked on every request: a claim in the token alone could be replayed after
the admin session was ended, and a flag in the browser could simply be set.

user_sessions already holds one row per sign-in, so the portal lives there:

  * session_key       stable id of the sign-in, carried in both tokens as
                      `sid`. The access-token JTI changes on every refresh, so
                      it cannot identify the session across refreshes.
  * portal            'employee' or 'admin'. Existing rows are employee
                      sessions: least privilege, and nothing signed in before
                      this change came through the admin door.
  * admin_expires_at  the absolute end of an admin session (sign-in + 8 h).
                      The idle limit slides on last_activity_at, which already
                      exists and was never written.

Downgrade drops the three columns. Admin sessions then become ordinary
sessions, which is what they were before this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "067_admin_mode"
down_revision = "066_finance_confidentiality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("session_key", sa.String(64), nullable=True))
    op.add_column(
        "user_sessions",
        sa.Column("portal", sa.String(16), nullable=False, server_default="employee"),
    )
    op.add_column(
        "user_sessions",
        sa.Column("admin_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_user_sessions_session_key", "user_sessions", ["session_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_user_sessions_session_key", table_name="user_sessions")
    op.drop_column("user_sessions", "admin_expires_at")
    op.drop_column("user_sessions", "portal")
    op.drop_column("user_sessions", "session_key")
