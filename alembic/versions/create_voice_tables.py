"""create voice tables

Revision ID: create_voice_tables
Revises: 
Create Date: 2024-01-17

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_voice_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Create voice_base table
    op.create_table('voice_base',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('influencer_id', sa.Integer(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('file_type', sa.String(length=50), nullable=True),
        sa.Column('s3_url', sa.Text(), nullable=False),
        sa.Column('s3_key', sa.String(length=500), nullable=False),
        sa.Column('duration', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['influencer_id'], ['ai_influencer.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('influencer_id')
    )
    op.create_index(op.f('ix_voice_base_id'), 'voice_base', ['id'], unique=False)

    # Create generated_voice table
    op.create_table('generated_voice',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('influencer_id', sa.Integer(), nullable=False),
        sa.Column('base_voice_id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('s3_url', sa.Text(), nullable=False),
        sa.Column('s3_key', sa.String(length=500), nullable=False),
        sa.Column('duration', sa.Float(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['base_voice_id'], ['voice_base.id'], ),
        sa.ForeignKeyConstraint(['influencer_id'], ['ai_influencer.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generated_voice_id'), 'generated_voice', ['id'], unique=False)
    op.create_index(op.f('ix_generated_voice_influencer_id'), 'generated_voice', ['influencer_id'], unique=False)
    op.create_index(op.f('ix_generated_voice_base_voice_id'), 'generated_voice', ['base_voice_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_generated_voice_base_voice_id'), table_name='generated_voice')
    op.drop_index(op.f('ix_generated_voice_influencer_id'), table_name='generated_voice')
    op.drop_index(op.f('ix_generated_voice_id'), table_name='generated_voice')
    op.drop_table('generated_voice')
    op.drop_index(op.f('ix_voice_base_id'), table_name='voice_base')
    op.drop_table('voice_base')