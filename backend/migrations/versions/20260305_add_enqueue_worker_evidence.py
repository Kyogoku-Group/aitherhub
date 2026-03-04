"""Add enqueue evidence and worker claimed columns to videos table

Revision ID: 20260305_enqueue_evidence
Revises: 20260304_human_tags
Create Date: 2026-03-05 02:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '20260305_enqueue_evidence'
down_revision = '20260304_human_tags'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Improvement 1: Enqueue evidence
    op.add_column('videos', sa.Column('queue_enqueued_at', sa.DateTime(), nullable=True))
    op.add_column('videos', sa.Column('queue_message_id', sa.String(255), nullable=True))
    op.add_column('videos', sa.Column('enqueue_status', sa.String(20), nullable=True))
    op.add_column('videos', sa.Column('enqueue_error', sa.Text(), nullable=True))

    # Improvement 2: Worker claimed evidence
    op.add_column('videos', sa.Column('worker_claimed_at', sa.DateTime(), nullable=True))
    op.add_column('videos', sa.Column('worker_instance_id', sa.String(255), nullable=True))
    op.add_column('videos', sa.Column('dequeue_count', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('videos', 'dequeue_count')
    op.drop_column('videos', 'worker_instance_id')
    op.drop_column('videos', 'worker_claimed_at')
    op.drop_column('videos', 'enqueue_error')
    op.drop_column('videos', 'enqueue_status')
    op.drop_column('videos', 'queue_message_id')
    op.drop_column('videos', 'queue_enqueued_at')
