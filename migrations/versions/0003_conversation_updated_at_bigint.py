"""Use a 64-bit integer for conversation millisecond timestamps.

Revision ID: 0003_conversation_updated_at
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_conversation_updated_at"
down_revision = "0002_email_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
