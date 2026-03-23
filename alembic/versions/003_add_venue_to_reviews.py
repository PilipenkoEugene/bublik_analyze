"""Add venue column to reviews

Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column("venue", sa.String(255), nullable=False, server_default="Бублик Ставрополь"),
    )
    op.create_index("ix_reviews_venue", "reviews", ["venue"])
    # Drop old unique constraint and create new one with venue
    op.drop_constraint("uq_platform_external_id", "reviews", type_="unique")
    op.create_unique_constraint(
        "uq_venue_platform_external_id", "reviews", ["venue", "platform", "external_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_venue_platform_external_id", "reviews", type_="unique")
    op.create_unique_constraint(
        "uq_platform_external_id", "reviews", ["platform", "external_id"]
    )
    op.drop_index("ix_reviews_venue", "reviews")
    op.drop_column("reviews", "venue")
