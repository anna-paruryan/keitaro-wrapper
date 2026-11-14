
"""editor drafts: streams and stream_offers

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keitaro_id", sa.Integer(), nullable=False),
        sa.Column("campaign_keitaro_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("has_offers", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_streams_keitaro_id", "streams", ["keitaro_id"], unique=True)
    op.create_index("ix_streams_campaign_keitaro_id", "streams", ["campaign_keitaro_id"])

    op.create_table(
        "stream_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stream_id", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.Integer(), nullable=False),
        sa.Column("offer_name", sa.String(255), nullable=False),
        sa.Column("share", sa.Integer(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False),
        sa.Column("draft_added", sa.Boolean(), nullable=False),
        sa.Column("published_share", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["stream_id"], ["streams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("stream_id", "offer_id", name="uq_stream_offers_stream_offer"),
    )
    op.create_index("ix_stream_offers_stream_id", "stream_offers", ["stream_id"])


def downgrade() -> None:
    op.drop_index("ix_stream_offers_stream_id", table_name="stream_offers")
    op.drop_table("stream_offers")
    op.drop_index("ix_streams_campaign_keitaro_id", table_name="streams")
    op.drop_index("ix_streams_keitaro_id", table_name="streams")
    op.drop_table("streams")