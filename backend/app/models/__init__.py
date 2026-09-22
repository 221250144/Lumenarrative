import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from app.config import settings


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[str] = mapped_column(
        String, default=lambda: datetime.now(timezone.utc).isoformat()
    )


class Project(Base):
    __tablename__ = "projects"
    title: Mapped[str] = mapped_column(String(200))
    intent: Mapped[str] = mapped_column(Text)
    target_duration_s: Mapped[int] = mapped_column(Integer, default=60)
    style: Mapped[str] = mapped_column(String, default="自然叙事")
    input_mode: Mapped[str] = mapped_column(String, default="clips")
    constraints_json: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    latest_analysis_id: Mapped[str | None] = mapped_column(String, nullable=True)
    demo_scenario: Mapped[str | None] = mapped_column(String, nullable=True)


class Asset(Base):
    __tablename__ = "assets"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_type: Mapped[str] = mapped_column(String)
    original_name: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String)
    duration_s: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    has_audio: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String, default="queued")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class AnalysisRun(Base):
    __tablename__ = "analyses"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    project_revision: Mapped[int] = mapped_column(Integer)
    asset_snapshot: Mapped[list] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    stage: Mapped[str] = mapped_column(String, default="等待分析")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Record:
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Shot(Record, Base):
    __tablename__ = "shots"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)


class TranscriptSegment(Record, Base):
    __tablename__ = "transcript_segments"
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)


class Evidence(Record, Base):
    __tablename__ = "evidence"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)


class Requirement(Record, Base):
    __tablename__ = "requirements"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)


class RequirementMatch(Record, Base):
    __tablename__ = "requirement_matches"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)


class Gap(Record, Base):
    __tablename__ = "gaps"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)


class CompletionPlan(Record, Base):
    __tablename__ = "completion_plans"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"), index=True)


class CompletionTask(Record, Base):
    __tablename__ = "completion_tasks"
    plan_id: Mapped[str] = mapped_column(ForeignKey("completion_plans.id"), index=True)


class Submission(Record, Base):
    __tablename__ = "submissions"
    task_id: Mapped[str] = mapped_column(ForeignKey("completion_tasks.id"), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    verification_status: Mapped[str] = mapped_column(String, default="queued")


class EditVersion(Record, Base):
    __tablename__ = "edit_versions"
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analyses.id"))
    render_status: Mapped[str] = mapped_column(String, default="queued")
    output_key: Mapped[str | None] = mapped_column(String, nullable=True)


class Job(Record, Base):
    __tablename__ = "jobs"
    type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued")
    stage: Mapped[str] = mapped_column(String, default="等待处理")
    completed_units: Mapped[int] = mapped_column(Integer, default=0)
    total_units: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)


class Idempotency(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("scope", "key"),)
    scope: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String)
    response: Mapped[dict] = mapped_column(JSON)


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {},
    pool_pre_ping=True,
    **({} if settings.database_url.startswith("sqlite") else {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
    }),
)
if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_config(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")


SessionLocal = sessionmaker(engine, expire_on_commit=False)


def serialize(row):
    result = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    if "data" in result:
        result.update(result.pop("data") or {})
    return result
