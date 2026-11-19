"""initial: created_campaigns, offer_changes

Revision ID: 0001
Revises:
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "created_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("domain_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("traffic_source_id", sa.Integer(), nullable=False),
        sa.Column("geo_stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_stream_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_created_campaigns_keitaro_id", "created_campaigns", ["keitaro_id"], unique=True)

    op.create_table(
        "offer_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("offer_ids", sa.JSON(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_offer_changes_campaign_id", "offer_changes", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_changes_campaign_id", table_name="offer_changes")
    op.drop_table("offer_changes")
    op.drop_index("ix_created_campaigns_keitaro_id", table_name="created_campaigns")
    op.drop_table("created_campaigns")
