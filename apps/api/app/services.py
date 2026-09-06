from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .models import (
    Activity,
    AnalyticsEvent,
    AttendanceConfirmation,
    NotificationJob,
    Rating,
    Response,
    ResponseStatus,
    User,
    UserBlock,
    as_utc,
)
from .schemas import ActivityAuthor, ActivityOut, PublicProfile, UserSportInput


def blocked_between(db: Session, first_id: str, second_id: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    or_(
                        and_(UserBlock.blocker_id == first_id, UserBlock.blocked_id == second_id),
                        and_(UserBlock.blocker_id == second_id, UserBlock.blocked_id == first_id),
                    )
                )
            )
        )
    )


def rating_summary(db: Session, user_id: str) -> tuple[float | None, int]:
    average, count = db.execute(
        select(func.avg(Rating.score), func.count(Rating.id)).where(Rating.target_id == user_id)
    ).one()
    return (round(float(average), 1) if average is not None else None, int(count))


def public_profile(db: Session, user: User) -> PublicProfile:
    average, count = rating_summary(db, user.id)
    return PublicProfile(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        photo_url=user.photo_url,
        age=user.age,
        bio=user.bio,
        district_id=user.district_id,
        sports=[UserSportInput(sport_id=item.sport_id, level=item.level) for item in user.sports],
        rating_average=average,
        rating_count=count,
    )


def accepted_count(activity: Activity) -> int:
    return sum(item.status == ResponseStatus.accepted.value for item in activity.responses)


def response_count(activity: Activity) -> int:
    return len(activity.responses)


def activity_out(db: Session, activity: Activity, actor: User) -> ActivityOut:
    accepted = accepted_count(activity)
    own_response = next((item for item in activity.responses if item.user_id == actor.id), None)
    average, count = rating_summary(db, activity.author_id)
    confirmations = db.scalars(
        select(AttendanceConfirmation).where(AttendanceConfirmation.activity_id == activity.id)
    ).all()
    positives = sum(item.occurred for item in confirmations)
    negatives = len(confirmations) - positives
    result = (
        "occurred"
        if positives and not negatives
        else "disputed"
        if positives and negatives
        else "did_not_occur"
        if negatives
        else "unknown"
    )
    eligible = actor.id == activity.author_id or any(
        item.user_id == actor.id and item.status == ResponseStatus.accepted.value
        for item in activity.responses
    )
    can_confirm = (
        eligible
        and as_utc(activity.starts_at) <= datetime.now(timezone.utc)
        and activity.status not in {"cancelled", "expired"}
        and not any(item.user_id == actor.id for item in confirmations)
    )
    return ActivityOut(
        id=activity.id,
        author=ActivityAuthor(
            id=activity.author.id,
            first_name=activity.author.first_name,
            age=activity.author.age,
            photo_url=activity.author.photo_url,
            rating_average=average,
            rating_count=count,
        ),
        sport_id=activity.sport_id,
        sport_name=activity.sport.name,
        sport_emoji=activity.sport.emoji,
        district_id=activity.district_id,
        district_name=activity.district.name,
        level=activity.level,
        starts_at=activity.starts_at,
        timezone=activity.timezone,
        place=activity.place,
        players_needed=activity.players_needed,
        accepted_count=accepted,
        remaining_places=(
            None
            if activity.players_needed is None
            else max(0, activity.players_needed - accepted)
        ),
        response_count=response_count(activity),
        comment=activity.comment,
        status=activity.status,
        is_owner=activity.author_id == actor.id,
        my_response_id=own_response.id if own_response else None,
        my_response_status=own_response.status if own_response else None,
        can_respond=(
            activity.status == "active"
            and as_utc(activity.starts_at) > datetime.now(timezone.utc)
            and activity.author_id != actor.id
            and own_response is None
            and (activity.players_needed is None or accepted < activity.players_needed)
        ),
        can_confirm_result=can_confirm,
        meeting_result=result,
    )


def activity_query():
    return select(Activity).options(
        selectinload(Activity.author).selectinload(User.sports),
        selectinload(Activity.sport),
        selectinload(Activity.district),
        selectinload(Activity.responses).selectinload(Response.user).selectinload(User.sports),
    )


def get_visible_activity(
    db: Session, activity_id: str, actor: User, lock: bool = False
) -> Activity:
    query = activity_query().where(Activity.id == activity_id)
    if lock:
        query = query.with_for_update()
    activity = db.scalar(query)
    if not activity or blocked_between(db, actor.id, activity.author_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Активность не найдена")
    return activity


def track(
    db: Session,
    name: str,
    actor: User | None = None,
    activity: Activity | None = None,
    properties: dict | None = None,
    event_id: str | None = None,
) -> None:
    settings = get_settings()
    db.add(
        AnalyticsEvent(
            event_id=event_id or None,
            event_name=name,
            actor_id=actor.id if actor else None,
            activity_id=activity.id if activity else None,
            environment=settings.app_env,
            properties=properties or {},
        )
    )


def enqueue(
    db: Session,
    event_type: str,
    recipient_id: str,
    activity: Activity,
    suffix: str,
    scheduled_at: datetime | None = None,
    payload: dict | None = None,
) -> None:
    key = f"{event_type}:{activity.id}:{recipient_id}:{suffix}"
    if db.scalar(select(NotificationJob.id).where(NotificationJob.deduplication_key == key)):
        return
    db.add(
        NotificationJob(
            event_type=event_type,
            recipient_id=recipient_id,
            activity_id=activity.id,
            payload=payload or {},
            deduplication_key=key,
            scheduled_at=scheduled_at or datetime.now(timezone.utc),
        )
    )


def schedule_activity_jobs(db: Session, activity: Activity) -> None:
    settings = get_settings()
    reminder_at = activity.starts_at - timedelta(minutes=settings.reminder_minutes_before)
    enqueue(db, "reminder", activity.author_id, activity, "organizer", reminder_at)
    result_at = activity.starts_at + timedelta(minutes=settings.result_request_minutes_after)
    enqueue(db, "result_request", activity.author_id, activity, "organizer", result_at)
