"""initial: campaigns and offer_changes

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("alias", sa.String(64), nullable=False),
        sa.Column("geo", sa.String(255), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("offer_name", sa.String(255), nullable=True),
        sa.Column("geo_stream_id", sa.Integer(), nullable=True),
        sa.Column("offer_stream_id", sa.Integer(), nullable=True),
        sa.Column("domain_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.Column("traffic_source_id", sa.Integer(), nullable=True),
        sa.Column("tracker_url", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campaigns_keitaro_id", "campaigns", ["keitaro_id"], unique=True)

    op.create_table(
        "offer_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_keitaro_id", sa.Integer(), nullable=False),
        sa.Column("stream_keitaro_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=True),
        sa.Column("offer_name", sa.String(255), nullable=True),
        sa.Column("shares_before", sa.JSON(), nullable=False),
        sa.Column("shares_after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_offer_changes_campaign_keitaro_id", "offer_changes", ["campaign_keitaro_id"])


def downgrade() -> None:
    op.drop_index("ix_offer_changes_campaign_keitaro_id", table_name="offer_changes")
    op.drop_table("offer_changes")
    op.drop_index("ix_campaigns_keitaro_id", table_name="campaigns")
    op.drop_table("campaigns")
