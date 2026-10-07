"""Track approval decisions for department-manager registrations.

Revision ID: 20261004_0003
Revises: 20261004_0002
"""
from alembic import op
import sqlalchemy as sa

revision = "20261004_0003"
down_revision = "20261004_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("registration_status", sa.String(20), server_default="APPROVED", nullable=False))


def downgrade():
    op.drop_column("users", "registration_status")