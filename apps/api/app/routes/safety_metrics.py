from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from hmac import compare_digest
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, require_onboarded
from ..config import Settings, get_settings
from ..database import get_db
from ..models import (
    Activity,
    AnalyticsEvent,
    AttendanceConfirmation,
    District,
    NotificationJob,
    Report,
    Response,
    Sport,
    User,
    UserBlock,
    UserSport,
    utcnow,
)
from ..schemas import BlockInput, ClientEventInput, MetricsOut, ReportInput
from ..services import get_visible_activity, track

router = APIRouter()

CLIENT_EVENTS = {
    "app_opened",
    "onboarding_started",
    "feed_viewed",
    "activity_viewed",
    "filter_applied",
    "activity_create_started",
}
ALLOWED_PROPERTIES = {"screen", "source", "sport_id", "district_id", "level", "has_filters"}


@router.post("/reports", status_code=201)
def report_user(
    body: ReportInput,
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
):
    if body.target_user_id == actor.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нельзя пожаловаться на себя"
        )
    target = db.scalar(select(User).where(User.id == body.target_user_id))
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    if body.activity_id:
        get_visible_activity(db, body.activity_id, actor)
    report = Report(
        author_id=actor.id,
        target_id=target.id,
        activity_id=body.activity_id,
        reason=body.reason,
        details=body.details.strip(),
    )
    db.add(report)
    db.flush()
    track(db, "report_submitted", actor, properties={"reason": body.reason})
    db.commit()
    return {"id": report.id, "status": "received"}


@router.post("/blocks", status_code=201)
def block_user(
    body: BlockInput,
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
):
    if body.target_user_id == actor.id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нельзя заблокировать себя"
        )
    if not db.scalar(select(User.id).where(User.id == body.target_user_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    existing = db.scalar(
        select(UserBlock).where(
            UserBlock.blocker_id == actor.id, UserBlock.blocked_id == body.target_user_id
        )
    )
    if not existing:
        db.add(UserBlock(blocker_id=actor.id, blocked_id=body.target_user_id))
    # Закрываем pending и будущие accepted связи пары, не стирая историю.
    responses = db.scalars(
        select(Response)
        .join(Activity)
        .where(
            Activity.starts_at > utcnow(),
            or_(
                and_(Activity.author_id == actor.id, Response.user_id == body.target_user_id),
                and_(Activity.author_id == body.target_user_id, Response.user_id == actor.id),
            ),
            Response.status.in_(["pending", "accepted"]),
        )
        .with_for_update()
    ).all()
    for response in responses:
        response.status = "cancelled"
        response.cancelled_at = utcnow()
        response.decision_reason = "user_blocked"
        accepted = (
            db.scalar(
                select(func.count(Response.id)).where(
                    Response.activity_id == response.activity_id, Response.status == "accepted"
                )
            )
            or 0
        )
        activity = db.scalar(select(Activity).where(Activity.id == response.activity_id))
        if (
            activity
            and activity.status == "filled"
            and (activity.players_needed is None or accepted < activity.players_needed)
        ):
            activity.status = "active"
    track(db, "user_blocked", actor, properties={"target_user_id": body.target_user_id})
    db.commit()
    return {"status": "blocked"}


@router.post("/analytics/events", status_code=202)
def client_event(
    body: ClientEventInput,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.event_name not in CLIENT_EVENTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Событие нельзя отправить с клиента"
        )
    properties = {k: v for k, v in body.properties.items() if k in ALLOWED_PROPERTIES}
    if db.scalar(select(AnalyticsEvent.event_id).where(AnalyticsEvent.event_id == body.event_id)):
        return {"status": "duplicate"}
    activity = None
    if body.activity_id:
        activity = get_visible_activity(db, body.activity_id, actor)
    track(db, body.event_name, actor, activity, properties, event_id=body.event_id)
    db.commit()
    return {"status": "accepted"}


def internal_access(
    x_internal_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if (
        not settings.internal_api_key
        or not x_internal_key
        or not compare_digest(x_internal_key, settings.internal_api_key)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")


@router.get("/internal/metrics", response_model=MetricsOut, dependencies=[Depends(internal_access)])
def metrics(
    period_start: date = Query(default_factory=lambda: date.today().replace(day=1)),
    period_end: date = Query(default_factory=date.today),
    sport_id: str | None = Query(default=None),
    district_id: str | None = Query(default=None),
    level: str | None = Query(default=None),
    acquisition_source: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if period_start > period_end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Начало позже конца периода"
        )
    start = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    end = datetime.combine(period_end, time.max, tzinfo=timezone.utc)
    real_users = User.is_dev.is_(False) if settings.app_env == "production" else True
    user_query = select(User).where(User.created_at.between(start, end), real_users)
    if district_id:
        user_query = user_query.where(User.district_id == district_id)
    if acquisition_source:
        user_query = user_query.where(User.acquisition_source == acquisition_source)
    if sport_id or level:
        user_query = user_query.join(UserSport)
        if sport_id:
            user_query = user_query.where(UserSport.sport_id == sport_id)
        if level:
            user_query = user_query.where(UserSport.level == level)
        user_query = user_query.distinct()
    cohort = list(db.scalars(user_query).all())
    cohort_ids = {user.id for user in cohort}

    activity_query = (
        select(Activity)
        .join(User, User.id == Activity.author_id)
        .where(Activity.created_at.between(start, end), real_users)
    )
    if sport_id:
        activity_query = activity_query.where(Activity.sport_id == sport_id)
    if district_id:
        activity_query = activity_query.where(Activity.district_id == district_id)
    if level:
        activity_query = activity_query.where(Activity.level == level)
    if acquisition_source:
        activity_query = activity_query.where(User.acquisition_source == acquisition_source)
    activities = list(db.scalars(activity_query).all())
    activity_ids = {activity.id for activity in activities}
    activity_responses = (
        list(db.scalars(select(Response).where(Response.activity_id.in_(activity_ids))).all())
        if activity_ids
        else []
    )
    responses_by_activity: dict[str, list[Response]] = {}
    for response in activity_responses:
        responses_by_activity.setdefault(response.activity_id, []).append(response)

    registrations = len(cohort)
    onboarded = sum(user.onboarding_completed_at is not None for user in cohort)
    activated_ids = {activity.author_id for activity in activities} | {
        response.user_id
        for response in activity_responses
        if start
        <= response.created_at.replace(tzinfo=response.created_at.tzinfo or timezone.utc)
        <= end
    }
    activation = len(activated_ids & cohort_ids)
    activities_created = len(activities)
    activities_with_response = sum(
        bool(responses_by_activity.get(activity.id)) for activity in activities
    )
    responses_sent = len(activity_responses)
    responses_accepted = sum(response.accepted_at is not None for response in activity_responses)
    pending_responses = sum(response.status == "pending" for response in activity_responses)
    system_closed = sum(
        response.decision_reason in {"activity_cancelled", "recruitment_closed", "user_blocked"}
        for response in activity_responses
    )
    first_response_minutes = []
    for activity in activities:
        responses = responses_by_activity.get(activity.id, [])
        if responses:
            first = min(response.created_at for response in responses)
            created = activity.created_at
            if first.tzinfo is None:
                first = first.replace(tzinfo=timezone.utc)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            first_response_minutes.append(max(0.0, (first - created).total_seconds() / 60))

    now = datetime.now(timezone.utc)
    past_activities = [
        activity
        for activity in activities
        if activity.starts_at.replace(tzinfo=activity.starts_at.tzinfo or timezone.utc) <= now
        and activity.status != "cancelled"
    ]
    completed = sum(activity.status == "completed" for activity in past_activities)
    cancelled = sum(activity.status == "cancelled" for activity in activities)
    successful_ids = (
        {
            confirmation.activity_id
            for confirmation in db.scalars(
                select(AttendanceConfirmation).where(
                    AttendanceConfirmation.activity_id.in_(activity_ids),
                    AttendanceConfirmation.occurred.is_(True),
                )
            ).all()
        }
        if activity_ids
        else set()
    )
    accepted_activity_ids = {
        response.activity_id for response in activity_responses if response.accepted_at is not None
    }
    successful = len(successful_ids & accepted_activity_ids)

    report_query = select(Report).where(Report.created_at.between(start, end))
    if activity_ids:
        report_query = report_query.where(Report.activity_id.in_(activity_ids))
    elif sport_id or district_id or level or acquisition_source:
        report_query = report_query.where(False)
    report_rows = list(db.scalars(report_query).all())
    reports = len(report_rows)
    active_user_ids = set(
        db.scalars(
            select(AnalyticsEvent.actor_id).where(
                AnalyticsEvent.event_name == "app_opened",
                AnalyticsEvent.timestamp.between(start, end),
                AnalyticsEvent.actor_id.is_not(None),
            )
        ).all()
    )
    if settings.app_env == "production":
        active_user_ids &= set(db.scalars(select(User.id).where(User.is_dev.is_(False))).all())
    reported_user_ids = {report.target_id for report in report_rows}
    no_show_activity_ids = {
        report.activity_id
        for report in report_rows
        if report.reason == "no_show" and report.activity_id
    }
    past_with_accepted = {
        activity.id for activity in past_activities if activity.id in accepted_activity_ids
    }

    cluster_tz = ZoneInfo(settings.cluster_timezone)
    activities_by_day = dict(
        sorted(
            Counter(
                activity.created_at.replace(tzinfo=activity.created_at.tzinfo or timezone.utc)
                .astimezone(cluster_tz)
                .date()
                .isoformat()
                for activity in activities
            ).items()
        )
    )

    app_open_events = (
        list(
            db.execute(
                select(AnalyticsEvent.actor_id, AnalyticsEvent.timestamp).where(
                    AnalyticsEvent.event_name == "app_opened",
                    AnalyticsEvent.actor_id.in_(cohort_ids),
                )
            ).all()
        )
        if cohort_ids
        else []
    )
    opened_days: dict[str, set[date]] = {}
    for actor_id, timestamp in app_open_events:
        aware = timestamp.replace(tzinfo=timestamp.tzinfo or timezone.utc)
        opened_days.setdefault(actor_id, set()).add(aware.astimezone(cluster_tz).date())

    def ratio(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    def retention(day_number: int) -> tuple[int, int, float | None]:
        mature = []
        retained = 0
        today = now.astimezone(cluster_tz).date()
        for user in cohort:
            created = user.created_at.replace(tzinfo=user.created_at.tzinfo or timezone.utc)
            cohort_day = created.astimezone(cluster_tz).date()
            if cohort_day + timedelta(days=day_number) <= today:
                mature.append(user)
                retained += cohort_day + timedelta(days=day_number) in opened_days.get(
                    user.id, set()
                )
        return retained, len(mature), ratio(retained, len(mature))

    d1_retained, d1_eligible, d1_rate = retention(1)
    d7_retained, d7_eligible, d7_rate = retention(7)
    d30_retained, d30_eligible, d30_rate = retention(30)

    pending = (
        db.scalar(select(func.count(NotificationJob.id)).where(NotificationJob.status == "pending"))
        or 0
    )
    failed = (
        db.scalar(select(func.count(NotificationJob.id)).where(NotificationJob.status == "failed"))
        or 0
    )
    return MetricsOut(
        period_start=period_start,
        period_end=period_end,
        registrations=registrations,
        onboarding_completed=onboarded,
        activation_users=activation,
        activities_created=activities_created,
        activities_with_response=activities_with_response,
        responses_sent=responses_sent,
        responses_accepted=responses_accepted,
        completed_activities=completed,
        successful_matches=successful,
        cancelled_activities=cancelled,
        reports=reports,
        notification_queue_pending=pending,
        notification_queue_failed=failed,
        past_activities=len(past_activities),
        pending_responses=pending_responses,
        system_closed_responses=system_closed,
        reported_users=len(reported_user_ids & active_user_ids),
        active_users=len(active_user_ids),
        no_show_report_activities=len(no_show_activity_ids & past_with_accepted),
        past_activities_with_accepted=len(past_with_accepted),
        retention_d1_retained=d1_retained,
        retention_d1_eligible=d1_eligible,
        retention_d7_retained=d7_retained,
        retention_d7_eligible=d7_eligible,
        retention_d30_retained=d30_retained,
        retention_d30_eligible=d30_eligible,
        onboarding_completion_rate=ratio(onboarded, registrations),
        activation_rate=ratio(activation, registrations),
        activities_with_response_rate=ratio(activities_with_response, activities_created),
        responses_per_activity=ratio(responses_sent, activities_created),
        median_first_response_minutes=(
            round(float(median(first_response_minutes)), 1) if first_response_minutes else None
        ),
        activities_without_response_rate=ratio(
            activities_created - activities_with_response, activities_created
        ),
        acceptance_rate=ratio(responses_accepted, responses_sent),
        pending_response_rate=ratio(pending_responses, responses_sent),
        system_closed_response_rate=ratio(system_closed, responses_sent),
        completion_rate=ratio(completed, len(past_activities)),
        cancellation_rate=ratio(cancelled, activities_created),
        reported_users_rate=ratio(len(reported_user_ids & active_user_ids), len(active_user_ids)),
        no_show_reports_rate=ratio(
            len(no_show_activity_ids & past_with_accepted), len(past_with_accepted)
        ),
        successful_matches_per_week=round(
            successful / max(1.0, ((period_end - period_start).days + 1) / 7), 2
        ),
        retention_d1=d1_rate,
        retention_d7=d7_rate,
        retention_d30=d30_rate,
        cohort_age_days=max(0, (date.today() - period_end).days),
        activities_by_day=activities_by_day,
        filter_sports=[
            {"id": item.id, "name": item.name, "emoji": item.emoji}
            for item in db.scalars(
                select(Sport).where(Sport.is_enabled.is_(True)).order_by(Sport.name)
            )
        ],
        filter_districts=[
            {"id": item.id, "name": item.name, "timezone": item.timezone}
            for item in db.scalars(
                select(District).where(District.is_enabled.is_(True)).order_by(District.name)
            )
        ],
        filter_levels=["beginner", "intermediate", "advanced"],
        filter_sources=list(
            db.scalars(select(User.acquisition_source).distinct().order_by(User.acquisition_source))
        ),
    )
