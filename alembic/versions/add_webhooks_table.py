"""add webhooks table

Revision ID: b2f1c3d4e5a6
Revises: 0a3e9a1488ea
Create Date: 2026-03-22 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2f1c3d4e5a6'
down_revision: Union[str, Sequence[str], None] = '0a3e9a1488ea'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'webhooks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('secret', sa.String(), server_default='', nullable=False),
        sa.Column('event_types', sa.JSON(), server_default='[]', nullable=False),
        sa.Column('source_filter', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('url'),
    )

def downgrade() -> None:
    op.drop_table('webhooks')
