"""Store the approval route on each request.

Revision ID: 20261004_0002
Revises: 20260921_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261004_0002"
down_revision = "20260921_0001"
branch_labels = None
depends_on = None


def upgrade():
    route_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.add_column("requests", sa.Column("approval_route", route_type, nullable=True))


def downgrade():
    op.drop_column("requests", "approval_route")