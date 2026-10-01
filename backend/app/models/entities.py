from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def now() -> datetime:
    return datetime.utcnow()


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    permissions: Mapped[str] = mapped_column(Text, default="")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    role: Mapped[Role] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(80), default="system")
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(80), default="")
    target_id: Mapped[str] = mapped_column(String(120), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(80), default="excel")
    status: Mapped[str] = mapped_column(String(40), default="pending")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    success_rows: Mapped[int] = mapped_column(Integer, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    imported_by: Mapped[str] = mapped_column(String(80), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    order_no: Mapped[str] = mapped_column(String(100), index=True)
    order_type: Mapped[str] = mapped_column(String(40), default="")
    problem_category: Mapped[str] = mapped_column(String(255), default="", index=True)
    tags: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(255), default="", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="")
    caller_name: Mapped[str] = mapped_column(String(80), default="")
    caller_phone: Mapped[str] = mapped_column(String(80), default="")
    district: Mapped[str] = mapped_column(String(80), default="")
    town: Mapped[str] = mapped_column(String(80), default="", index=True)
    handling_result: Mapped[str] = mapped_column(Text, default="")
    reply_content: Mapped[str] = mapped_column(Text, default="")
    handling_method: Mapped[str] = mapped_column(String(60), default="")
    host_unit: Mapped[str] = mapped_column(String(255), default="")
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    company_name: Mapped[str] = mapped_column(String(255), default="", index=True)
    is_resolved: Mapped[str] = mapped_column(String(40), default="", index=True)
    satisfaction: Mapped[str] = mapped_column(String(40), default="", index=True)
    order_nature: Mapped[str] = mapped_column(String(60), default="")
    community: Mapped[str] = mapped_column(String(120), default="")
    location_point: Mapped[str] = mapped_column(String(255), default="", index=True)
    case_domain: Mapped[str] = mapped_column(String(120), default="", index=True)
    extra_fields: Mapped[str] = mapped_column(Text, default="[]")
    exported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    exported_by: Mapped[str] = mapped_column(String(80), default="")
    export_context: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Clue(Base):
    __tablename__ = "clues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), unique=True)
    predicted_domain: Mapped[str] = mapped_column(String(120), index=True)
    priority: Mapped[str] = mapped_column(String(20), default="低", index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(40), default="待确认", index=True)
    rule_hits: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    reviewer: Mapped[str] = mapped_column(String(80), default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    work_order: Mapped[WorkOrder] = relationship()


class ClueReview(Base):
    __tablename__ = "clue_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clue_id: Mapped[int] = mapped_column(ForeignKey("clues.id"))
    reviewer: Mapped[str] = mapped_column(String(80))
    before_status: Mapped[str] = mapped_column(String(40), default="")
    after_status: Mapped[str] = mapped_column(String(40), default="")
    before_domain: Mapped[str] = mapped_column(String(120), default="")
    after_domain: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class CaseClassification(Base):
    __tablename__ = "case_classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), index=True)
    module: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(120), index=True)
    priority: Mapped[str] = mapped_column(String(20), default="低", index=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0)
    rule_hits: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    review_status: Mapped[str] = mapped_column(String(40), default="待确认", index=True)
    reviewer: Mapped[str] = mapped_column(String(80), default="")
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    work_order: Mapped[WorkOrder] = relationship()


class EventCluster(Base):
    __tablename__ = "event_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(120), index=True)
    representative_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    match_reason: Mapped[str] = mapped_column(Text, default="")
    location_point: Mapped[str] = mapped_column(String(255), default="")
    town: Mapped[str] = mapped_column(String(80), default="")
    complaint_count: Mapped[int] = mapped_column(Integer, default=0)
    unresolved_count: Mapped[int] = mapped_column(Integer, default=0)
    dissatisfied_count: Mapped[int] = mapped_column(Integer, default=0)
    risk_level: Mapped[str] = mapped_column(String(20), default="低", index=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ClusterMember(Base):
    __tablename__ = "cluster_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("event_clusters.id"))
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"))


class ScreeningRule(Base):
    __tablename__ = "screening_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    module: Mapped[str] = mapped_column(String(40), default="public_interest", index=True)
    domain: Mapped[str] = mapped_column(String(120))
    keywords: Mapped[str] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), default="openai-compatible")
    base_url: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    api_key_masked: Mapped[str] = mapped_column(String(80), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ExportTask(Base):
    __tablename__ = "export_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    export_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    file_path: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
