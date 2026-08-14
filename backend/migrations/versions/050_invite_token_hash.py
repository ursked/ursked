"""Hash invite tokens at rest

Revision ID: 050_invite_token_hash
Revises: 049_node_schedule_visibility

Store only the SHA-256 hash of an invite/activation token, mirroring
password_reset_tokens. Previously the raw token was stored in plaintext, so a
leaked database was a set of working activation links.

The column `token` (String(255)) becomes `token_hash` (String(64)). Any existing
invite rows hold raw tokens that can never match the new hashed lookup, so they
are cleared — an operator simply re-sends those invites. Invite tokens are
short-lived and low-value, so this is safe.
"""
from alembic import op
import sqlalchemy as sa

revision = "050_invite_token_hash"
down_revision = "049_node_schedule_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old rows carry raw tokens; under hashed lookup they are unreachable. Drop
    # them so no stale/plaintext values linger.
    op.execute("DELETE FROM user_invite_tokens")

    # Drop the old unique index on the plaintext column, rename + resize the
    # column, then recreate the unique index on the hash.
    op.drop_index("ix_user_invite_tokens_token", table_name="user_invite_tokens")
    op.alter_column(
        "user_invite_tokens",
        "token",
        new_column_name="token_hash",
        type_=sa.String(length=64),
        existing_type=sa.String(length=255),
        existing_nullable=False,
    )
    op.create_index(
        "ix_user_invite_tokens_token_hash",
        "user_invite_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM user_invite_tokens")
    op.drop_index("ix_user_invite_tokens_token_hash", table_name="user_invite_tokens")
    op.alter_column(
        "user_invite_tokens",
        "token_hash",
        new_column_name="token",
        type_=sa.String(length=255),
        existing_type=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_index(
        "ix_user_invite_tokens_token",
        "user_invite_tokens",
        ["token"],
        unique=True,
    )
