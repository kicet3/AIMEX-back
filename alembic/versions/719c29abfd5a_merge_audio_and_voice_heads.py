"""merge audio and voice heads

Revision ID: 719c29abfd5a
Revises: 319fae47d61f, create_voice_tables
Create Date: 2025-07-17 14:09:09.036287

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '719c29abfd5a'
down_revision = ('319fae47d61f', 'create_voice_tables')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
