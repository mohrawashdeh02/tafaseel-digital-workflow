from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

JsonData = JSON().with_variant(JSONB(), "postgresql")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name_ar: Mapped[str] = mapped_column(String(100))


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(150))
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    registration_status: Mapped[str] = mapped_column(String(20), default="APPROVED", server_default="APPROVED")
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    role: Mapped[Role] = relationship()
    department: Mapped[Department | None] = relationship()


class RequestType(Base):
    __tablename__ = "request_types"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name_ar: Mapped[str] = mapped_column(String(150))
    fields: Mapped[dict] = mapped_column(JsonData, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_type_id: Mapped[int] = mapped_column(ForeignKey("request_types.id"), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    request_type: Mapped[RequestType] = relationship()
    steps: Mapped[list["WorkflowStep"]] = relationship(back_populates="workflow", order_by="WorkflowStep.position", cascade="all, delete-orphan")


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id"))
    position: Mapped[int] = mapped_column(Integer)
    role_code: Mapped[str] = mapped_column(String(50))
    label_ar: Mapped[str] = mapped_column(String(150))
    workflow: Mapped[Workflow] = relationship(back_populates="steps")
    __table_args__ = (UniqueConstraint("workflow_id", "position"),)


class Request(Base):
    __tablename__ = "requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_type_id: Mapped[int] = mapped_column(ForeignKey("request_types.id"))
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(80), default="DRAFT", index=True)
    current_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    form_data: Mapped[dict] = mapped_column(JsonData, default=dict)
    approval_route: Mapped[list[str] | None] = mapped_column(JsonData, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    request_type: Mapped[RequestType] = relationship()
    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    approvals: Mapped[list["RequestApproval"]] = relationship(order_by="RequestApproval.created_at", cascade="all, delete-orphan")
    history: Mapped[list["RequestHistory"]] = relationship(order_by="RequestHistory.created_at", cascade="all, delete-orphan")


class RequestApproval(Base):
    __tablename__ = "request_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    step_position: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewer: Mapped[User] = relationship()


class RequestHistory(Base):
    __tablename__ = "request_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[User | None] = relationship()


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), nullable=True)
    message: Mapped[str] = mapped_column(String(300))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
