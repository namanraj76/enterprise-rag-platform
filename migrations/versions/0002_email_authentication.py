"""Add password authentication and persisted email verification.

Revision ID: 0002_email_authentication
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_email_authentication"
down_revision = "0001_private_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "google_sub",
            existing_type=sa.String(length=255),
            nullable=True,
        )
        batch_op.add_column(sa.Column("password_hash", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # The preceding Google-only system created users only from Google's verified-email claim.
    op.execute(sa.text("UPDATE users SET email_verified = true WHERE google_sub IS NOT NULL"))

    op.create_table(
        "email_verifications",
        sa.Column("token_hash", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )
    op.create_index("ix_email_verifications_user_id", "email_verifications", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_email_verifications_user_id", table_name="email_verifications")
    op.drop_table("email_verifications")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("email_verified")
        batch_op.drop_column("password_hash")
        batch_op.alter_column(
            "google_sub",
            existing_type=sa.String(length=255),
            nullable=False,
        )
