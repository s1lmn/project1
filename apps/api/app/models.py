import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalize DB datetimes; SQLite drops tzinfo while PostgreSQL preserves it."""
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def new_id() -> str:
    return str(uuid.uuid4())


class Level(str, enum.Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class ActivityStatus(str, enum.Enum):
    active = "active"
    filled = "filled"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"


class ResponseStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    cancelled = "cancelled"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class District(Base):
    __tablename__ = "districts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Sport(Base):
    __tablename__ = "sports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), default="🏃")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128))
    photo_url: Mapped[str | None] = mapped_column(Text)
    age: Mapped[int | None] = mapped_column(Integer)
    bio: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    district_id: Mapped[str | None] = mapped_column(ForeignKey("districts.id"))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    globally_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acquisition_source: Mapped[str] = mapped_column(String(80), default="unknown", nullable=False)
    is_dev: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_moderator: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    sports: Mapped[list["UserSport"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (CheckConstraint("age IS NULL OR age BETWEEN 1 AND 120", name="ck_user_age"),)


class UserSport(Base):
    __tablename__ = "user_sports"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sport_id: Mapped[str] = mapped_column(ForeignKey("sports.id"), primary_key=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    sport_id: Mapped[str] = mapped_column(ForeignKey("sports.id"), index=True, nullable=False)
    district_id: Mapped[str] = mapped_column(ForeignKey("districts.id"), index=True, nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    place: Mapped[str] = mapped_column(String(200), nullable=False)
    players_needed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=ActivityStatus.active.value, index=True)
    client_request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    had_response: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    author: Mapped[User] = relationship()
    sport: Mapped[Sport] = relationship()
    district: Mapped[District] = relationship()
    responses: Mapped[list["Response"]] = relationship(cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("author_id", "client_request_id", name="uq_activity_idempotency"),
        CheckConstraint(
            "players_needed IS NULL OR players_needed BETWEEN 1 AND 20",
            name="ck_activity_players",
        ),
        Index("ix_feed", "status", "district_id", "starts_at"),
    )


class Response(TimestampMixin, Base):
    __tablename__ = "responses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    activity_id: Mapped[str] = mapped_column(
        ForeignKey("activities.id"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=ResponseStatus.pending.value, index=True
    )
    decision_reason: Mapped[str | None] = mapped_column(String(100))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
    activity: Mapped[Activity] = relationship(back_populates="responses")
    __table_args__ = (UniqueConstraint("activity_id", "user_id", name="uq_response_user"),)


class AttendanceConfirmation(Base):
    __tablename__ = "attendance_confirmations"
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    occurred: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Rating(Base):
    __tablename__ = "ratings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), nullable=False)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    review: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("activity_id", "author_id", "target_id", name="uq_rating_pair"),
        CheckConstraint("score BETWEEN 1 AND 5", name="ck_rating_score"),
        CheckConstraint("author_id <> target_id", name="ck_rating_not_self"),
    )


class Report(TimestampMixin, Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"))
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)


class UserBlock(Base):
    __tablename__ = "user_blocks"
    blocker_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    blocked_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("blocker_id <> blocked_id", name="ck_block_not_self"),)


class NotificationJob(Base):
    __tablename__ = "notification_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    recipient_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(500))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    activity_id: Mapped[str | None] = mapped_column(ForeignKey("activities.id"), index=True)
    properties: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    environment: Mapped[str] = mapped_column(String(20), index=True, nullable=False)


class ModerationAudit(Base):
    __tablename__ = "moderation_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    moderator_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
