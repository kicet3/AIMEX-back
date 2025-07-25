"""remove session_id and pipeline_id from BOARD

Revision ID: 20250724120000_remove_session_pipeline_id
Revises: f87e17b6b685
Create Date: 2025-07-24 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "remove_session_pipeline_id"
down_revision = "f87e17b6b685"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("BOARD") as batch_op:
        batch_op.drop_column("session_id")
        batch_op.drop_column("pipeline_id")


def downgrade():
    with op.batch_alter_table("BOARD") as batch_op:
        batch_op.add_column(
            sa.Column("session_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("pipeline_id", sa.String(length=36), nullable=True)
        )
