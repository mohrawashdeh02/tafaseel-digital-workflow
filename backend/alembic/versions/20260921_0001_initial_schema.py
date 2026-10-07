"""initial workflow schema

Revision ID: 20260921_0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260921_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("roles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(50), nullable=False, unique=True), sa.Column("name_ar", sa.String(100), nullable=False))
    op.create_index("ix_roles_code", "roles", ["code"])
    op.create_table("departments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("name", sa.String(120), nullable=False, unique=True))
    op.create_table("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("full_name", sa.String(150), nullable=False), sa.Column("employee_id", sa.String(50), nullable=False, unique=True), sa.Column("email", sa.String(255), nullable=False, unique=True), sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=False), sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id")))
    op.create_index("ix_users_email", "users", ["email"]); op.create_index("ix_users_employee_id", "users", ["employee_id"])
    op.create_table("request_types", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(80), nullable=False, unique=True), sa.Column("name_ar", sa.String(150), nullable=False), sa.Column("fields", postgresql.JSONB(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_request_types_code", "request_types", ["code"])
    op.create_table("workflows", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_type_id", sa.Integer(), sa.ForeignKey("request_types.id"), nullable=False, unique=True), sa.Column("name", sa.String(150), nullable=False))
    op.create_table("workflow_steps", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflows.id"), nullable=False), sa.Column("position", sa.Integer(), nullable=False), sa.Column("role_code", sa.String(50), nullable=False), sa.Column("label_ar", sa.String(150), nullable=False), sa.UniqueConstraint("workflow_id", "position"))
    op.create_table("requests", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_type_id", sa.Integer(), sa.ForeignKey("request_types.id"), nullable=False), sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("status", sa.String(80), nullable=False, server_default="DRAFT"), sa.Column("current_step", sa.Integer()), sa.Column("form_data", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_requests_status", "requests", ["status"])
    op.create_table("request_approvals", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_id", sa.Integer(), sa.ForeignKey("requests.id"), nullable=False), sa.Column("step_position", sa.Integer(), nullable=False), sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("action", sa.String(20), nullable=False), sa.Column("comment", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_request_approvals_request_id", "request_approvals", ["request_id"])
    op.create_table("request_history", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("request_id", sa.Integer(), sa.ForeignKey("requests.id"), nullable=False), sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("actor_role", sa.String(50)), sa.Column("action", sa.String(100), nullable=False), sa.Column("comment", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_request_history_request_id", "request_history", ["request_id"])
    op.create_table("notifications", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("request_id", sa.Integer(), sa.ForeignKey("requests.id")), sa.Column("message", sa.String(300), nullable=False), sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])


def downgrade():
    for name in ["notifications", "request_history", "request_approvals", "requests", "workflow_steps", "workflows", "request_types", "users", "departments", "roles"]: op.drop_table(name)
