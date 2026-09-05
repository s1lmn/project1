from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Time, and_, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import require_onboarded
from ..config import Settings, get_settings
from ..database import get_db
from ..models import (
    Activity,
    ActivityStatus,
    AttendanceConfirmation,
    District,
    Rating,
    Response,
    Sport,
    User,
    UserBlock,
    as_utc,
    utcnow,
)
from ..schemas import (
    ActivityCreate,
    ActivityOut,
    ActivityUpdate,
    ContactOut,
    Page,
    RatingInput,
    ResponseOut,
    ResultInput,
)
from ..services import (
    accepted_count,
    activity_out,
    activity_query,
    blocked_between,
    enqueue,
    get_visible_activity,
    public_profile,
    schedule_activity_jobs,
    track,
)

router = APIRouter()


def _validate_refs(db: Session, sport_id: str, district_id: str) -> District:
    if not db.scalar(select(Sport.id).where(Sport.id == sport_id, Sport.is_enabled.is_(True))):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Вид спорта недоступен")
    district = db.scalar(
        select(District).where(District.id == district_id, District.is_enabled.is_(True))
    )
    if not district:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Район недоступен")
    return district


def _check_players(value: int, settings: Settings) -> None:
    if not settings.min_players_needed <= value <= settings.max_players_needed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Недопустимое число игроков"
        )


@router.get("/activities", response_model=Page)
def feed(
    sport_id: str | None = None,
    district_id: str | None = None,
    level: str | None = None,
    day: date | None = None,
    time_from: time | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    query = activity_query().where(
        Activity.status == ActivityStatus.active.value,
        Activity.starts_at > utcnow(),
        ~exists_block(actor.id),
    )
    if sport_id:
        query = query.where(Activity.sport_id == sport_id)
    if district_id:
        query = query.where(Activity.district_id == district_id)
    if level:
        query = query.where(Activity.level == level)
    zone_name = settings.cluster_timezone
    if district_id:
        zone_name = (
            db.scalar(select(District.timezone).where(District.id == district_id)) or zone_name
        )
    if day:
        local_zone = ZoneInfo(zone_name)
        start = datetime.combine(day, time.min, tzinfo=local_zone).astimezone(timezone.utc)
        finish = datetime.combine(day + timedelta(days=1), time.min, tzinfo=local_zone).astimezone(
            timezone.utc
        )
        query = query.where(Activity.starts_at >= start, Activity.starts_at < finish)
    if time_from:
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.where(
                cast(func.timezone(zone_name, Activity.starts_at), Time) >= time_from
            )
        else:
            query = query.where(func.time(Activity.starts_at) >= time_from.isoformat())
    rows = db.scalars(
        query.order_by(Activity.starts_at).offset((page - 1) * page_size).limit(page_size + 1)
    ).all()
    return Page(
        items=[activity_out(db, x, actor) for x in rows[:page_size]],
        page=page,
        page_size=page_size,
        has_more=len(rows) > page_size,
    )


def exists_block(actor_id: str):
    return (
        select(UserBlock.blocker_id)
        .where(
            or_(
                and_(UserBlock.blocker_id == actor_id, UserBlock.blocked_id == Activity.author_id),
                and_(UserBlock.blocked_id == actor_id, UserBlock.blocker_id == Activity.author_id),
            )
        )
        .exists()
    )


@router.post("/activities", response_model=ActivityOut, status_code=201)
def create_activity(
    body: ActivityCreate,
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if body.starts_at <= utcnow():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Время должно быть в будущем"
        )
    _check_players(body.players_needed, settings)
    district = _validate_refs(db, body.sport_id, body.district_id)
    existing = db.scalar(
        select(Activity).where(
            Activity.author_id == actor.id, Activity.client_request_id == body.client_request_id
        )
    )
    if existing:
        return activity_out(
            db, db.scalar(activity_query().where(Activity.id == existing.id)), actor
        )
    activity = Activity(
        author_id=actor.id,
        sport_id=body.sport_id,
        district_id=body.district_id,
        level=body.level.value,
        starts_at=body.starts_at,
        timezone=district.timezone,
        place=body.place.strip(),
        players_needed=body.players_needed,
        comment=body.comment.strip(),
        client_request_id=body.client_request_id,
        expires_at=utcnow() + timedelta(hours=settings.activity_ttl_hours),
    )
    db.add(activity)
    db.flush()
    track(db, "activity_created", actor, activity)
    schedule_activity_jobs(db, activity)
    db.commit()
    return activity_out(db, db.scalar(activity_query().where(Activity.id == activity.id)), actor)


@router.get("/activities/{activity_id}", response_model=ActivityOut)
def get_activity(
    activity_id: str, actor: User = Depends(require_onboarded), db: Session = Depends(get_db)
):
    activity = get_visible_activity(db, activity_id, actor)
    return activity_out(db, activity, actor)


@router.patch("/activities/{activity_id}", response_model=ActivityOut)
def update_activity(
    activity_id: str,
    body: ActivityUpdate,
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    activity = get_visible_activity(db, activity_id, actor, lock=True)
    if activity.author_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Изменять может только организатор")
    if activity.status not in {"active", "filled"} or as_utc(activity.starts_at) <= utcnow():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Эту активность уже нельзя изменить")
    accepted = accepted_count(activity)
    locked_fields = {"sport_id", "district_id", "starts_at", "place"}
    changes = body.model_dump(exclude_unset=True)
    if accepted and locked_fields.intersection(changes):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="После принятия участника место, время, район и спорт менять нельзя",
        )
    if body.players_needed is not None:
        _check_players(body.players_needed, settings)
        if body.players_needed < accepted:
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="Мест не может быть меньше уже принятых участников"
            )
    if body.starts_at is not None and body.starts_at <= utcnow():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Время должно быть в будущем"
        )
    if body.sport_id or body.district_id:
        district = _validate_refs(
            db, body.sport_id or activity.sport_id, body.district_id or activity.district_id
        )
        if body.district_id:
            activity.timezone = district.timezone
    for key, value in changes.items():
        setattr(
            activity,
            key,
            value.value
            if hasattr(value, "value")
            else value.strip()
            if isinstance(value, str)
            else value,
        )
    activity.status = "filled" if accepted >= activity.players_needed else "active"
    db.commit()
    return activity_out(db, db.scalar(activity_query().where(Activity.id == activity.id)), actor)


@router.delete("/activities/{activity_id}", response_model=ActivityOut)
def cancel_activity(
    activity_id: str, actor: User = Depends(require_onboarded), db: Session = Depends(get_db)
):
    activity = get_visible_activity(db, activity_id, actor, lock=True)
    if activity.author_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Отменить может только организатор")
    if activity.status in {"cancelled", "completed", "expired"}:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Активность уже закрыта")
    activity.status = "cancelled"
    activity.cancellation_reason = "cancelled_by_organizer"
    for response in activity.responses:
        if response.status in {"pending", "accepted"}:
            response.status = "cancelled"
            response.cancelled_at = utcnow()
            response.decision_reason = "activity_cancelled"
            enqueue(
                db,
                "activity_cancelled",
                response.user_id,
                activity,
                response.id,
                payload={"counterpart_id": actor.id},
            )
    track(db, "activity_cancelled", actor, activity)
    db.commit()
    return activity_out(db, activity, actor)


@router.get("/me/activities", response_model=Page)
def my_activities(
    role: str = Query("organizer", pattern="^(organizer|participant)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
):
    query = activity_query()
    if role == "organizer":
        query = query.where(Activity.author_id == actor.id)
    else:
        query = query.join(Response).where(Response.user_id == actor.id)
    rows = (
        db.scalars(
            query.order_by(Activity.starts_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size + 1)
        )
        .unique()
        .all()
    )
    return Page(
        items=[activity_out(db, x, actor) for x in rows[:page_size]],
        page=page,
        page_size=page_size,
        has_more=len(rows) > page_size,
    )


@router.post("/activities/{activity_id}/respond", response_model=ResponseOut, status_code=201)
def respond(
    activity_id: str, actor: User = Depends(require_onboarded), db: Session = Depends(get_db)
):
    activity = get_visible_activity(db, activity_id, actor, lock=True)
    if activity.author_id == actor.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Нельзя откликнуться на свою активность"
        )
    if blocked_between(db, actor.id, activity.author_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Активность не найдена")
    if (
        activity.status != "active"
        or as_utc(activity.starts_at) <= utcnow()
        or accepted_count(activity) >= activity.players_needed
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Отклики больше не принимаются")
    existing = db.scalar(
        select(Response).where(Response.activity_id == activity.id, Response.user_id == actor.id)
    )
    if existing:
        return ResponseOut(
            id=existing.id,
            status=existing.status,
            decision_reason=existing.decision_reason,
            created_at=existing.created_at,
            user=public_profile(db, actor),
        )
    response = Response(activity_id=activity.id, user_id=actor.id)
    db.add(response)
    activity.had_response = True
    db.flush()
    track(db, "response_sent", actor, activity)
    enqueue(
        db,
        "new_response",
        activity.author_id,
        activity,
        response.id,
        payload={"responder_name": actor.first_name, "counterpart_id": actor.id},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Отклик уже существует") from exc
    return ResponseOut(
        id=response.id,
        status=response.status,
        decision_reason=None,
        created_at=response.created_at,
        user=public_profile(db, actor),
    )


@router.get("/activities/{activity_id}/responses", response_model=list[ResponseOut])
def list_responses(
    activity_id: str, actor: User = Depends(require_onboarded), db: Session = Depends(get_db)
):
    activity = get_visible_activity(db, activity_id, actor)
    if activity.author_id != actor.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Отклики доступны только организатору"
        )
    return [
        ResponseOut(
            id=x.id,
            status=x.status,
            decision_reason=x.decision_reason,
            created_at=x.created_at,
            user=public_profile(db, x.user),
        )
        for x in activity.responses
    ]


def _decide(response_id: str, decision: str, actor: User, db: Session) -> ResponseOut:
    response = db.scalar(select(Response).where(Response.id == response_id).with_for_update())
    if not response:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Отклик не найден")
    activity = get_visible_activity(db, response.activity_id, actor, lock=True)
    if activity.author_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Решение принимает организатор")
    if response.status == decision:
        return ResponseOut(
            id=response.id,
            status=response.status,
            decision_reason=response.decision_reason,
            created_at=response.created_at,
            user=public_profile(db, response.user),
        )
    if response.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Отклик уже закрыт")
    if as_utc(activity.starts_at) <= utcnow() or activity.status not in {"active", "filled"}:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Набор уже закрыт")
    if decision == "accepted":
        if accepted_count(activity) >= activity.players_needed:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Места уже набраны")
        response.status = "accepted"
        response.accepted_at = utcnow()
        response.decision_reason = "organizer_decision"
        if accepted_count(activity) >= activity.players_needed:
            activity.status = "filled"
        track(db, "response_accepted", actor, activity)
        enqueue(
            db,
            "response_accepted",
            response.user_id,
            activity,
            response.id,
            payload={"counterpart_id": actor.id},
        )
        schedule_activity_jobs(db, activity)
        settings = get_settings()
        enqueue(
            db,
            "reminder",
            response.user_id,
            activity,
            response.id,
            activity.starts_at - timedelta(minutes=settings.reminder_minutes_before),
        )
        enqueue(
            db,
            "result_request",
            response.user_id,
            activity,
            response.id,
            activity.starts_at + timedelta(minutes=settings.result_request_minutes_after),
        )
    else:
        response.status = "rejected"
        response.rejected_at = utcnow()
        response.decision_reason = "organizer_decision"
        track(db, "response_rejected", actor, activity)
        enqueue(
            db,
            "response_rejected",
            response.user_id,
            activity,
            response.id,
            payload={"counterpart_id": actor.id},
        )
    db.commit()
    return ResponseOut(
        id=response.id,
        status=response.status,
        decision_reason=response.decision_reason,
        created_at=response.created_at,
        user=public_profile(db, response.user),
    )


@router.patch("/responses/{response_id}/accept", response_model=ResponseOut)
def accept(
    response_id: str, actor: User = Depends(require_onboarded), db: Session = Depends(get_db)
):
    return _decide(response_id, "accepted", actor, db)


@router.patch("/responses/{response_id}/reject", response_model=ResponseOut)
def reject(
    response_id: str, actor: User = Depends(require_onboarded), db: Session = Depends(get_db)
):
    return _decide(response_id, "rejected", actor, db)


@router.patch("/responses/{response_id}/cancel", response_model=ResponseOut)
def cancel_response(
    response_id: str, actor: User = Depends(require_onboarded), db: Session = Depends(get_db)
):
    response = db.scalar(select(Response).where(Response.id == response_id).with_for_update())
    if not response:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Отклик не найден")
    if response.user_id != actor.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Можно отменить только свой отклик")
    if response.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Можно отменить только ожидающий отклик"
        )
    response.status = "cancelled"
    response.cancelled_at = utcnow()
    response.decision_reason = "cancelled_by_user"
    db.commit()
    return ResponseOut(
        id=response.id,
        status=response.status,
        decision_reason=response.decision_reason,
        created_at=response.created_at,
        user=public_profile(db, actor),
    )


@router.get("/activities/{activity_id}/contact/{user_id}", response_model=ContactOut)
def contact(
    activity_id: str,
    user_id: str,
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
):
    activity = get_visible_activity(db, activity_id, actor)
    if activity.status in {"cancelled", "expired"} or blocked_between(db, actor.id, user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Контакт недоступен")
    pair_ok = False
    if actor.id == activity.author_id:
        pair_ok = bool(
            db.scalar(
                select(Response.id).where(
                    Response.activity_id == activity.id,
                    Response.user_id == user_id,
                    Response.status == "accepted",
                )
            )
        )
    elif user_id == activity.author_id:
        pair_ok = bool(
            db.scalar(
                select(Response.id).where(
                    Response.activity_id == activity.id,
                    Response.user_id == actor.id,
                    Response.status == "accepted",
                )
            )
        )
    if not pair_ok:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="Контакт доступен только принятой паре"
        )
    target = db.scalar(select(User).where(User.id == user_id))
    if not target or target.globally_blocked_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    url = (
        f"https://t.me/{target.username}"
        if target.username
        else f"tg://user?id={target.telegram_id}"
    )
    track(db, "telegram_contact_clicked", actor, activity, {"target_user_id": target.id})
    db.commit()
    return ContactOut(
        user_id=target.id,
        display_name=target.first_name,
        telegram_url=url,
        username_available=bool(target.username),
        notice=None
        if target.username
        else "Переход без username зависит от настроек приватности Telegram",
    )


@router.post("/activities/{activity_id}/confirm-result")
def confirm_result(
    activity_id: str,
    body: ResultInput,
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
):
    activity = get_visible_activity(db, activity_id, actor, lock=True)
    eligible = actor.id == activity.author_id or bool(
        db.scalar(
            select(Response.id).where(
                Response.activity_id == activity.id,
                Response.user_id == actor.id,
                Response.status == "accepted",
            )
        )
    )
    if (
        not eligible
        or as_utc(activity.starts_at) > utcnow()
        or activity.status in {"cancelled", "expired"}
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Подтверждение результата недоступно")
    existing = db.scalar(
        select(AttendanceConfirmation).where(
            AttendanceConfirmation.activity_id == activity.id,
            AttendanceConfirmation.user_id == actor.id,
        )
    )
    if existing:
        return {"occurred": existing.occurred, "status": "already_confirmed"}
    db.add(
        AttendanceConfirmation(activity_id=activity.id, user_id=actor.id, occurred=body.occurred)
    )
    activity.status = "completed"
    track(db, "meeting_result_confirmed", actor, activity, {"occurred": body.occurred})
    track(db, "activity_completed", actor, activity, {"source": "confirmation"})
    db.commit()
    return {"occurred": body.occurred, "status": "confirmed"}


@router.post("/activities/{activity_id}/ratings", status_code=201)
def rate(
    activity_id: str,
    body: RatingInput,
    actor: User = Depends(require_onboarded),
    db: Session = Depends(get_db),
):
    activity = get_visible_activity(db, activity_id, actor)
    confirmation = db.scalar(
        select(AttendanceConfirmation).where(
            AttendanceConfirmation.activity_id == activity.id,
            AttendanceConfirmation.user_id == actor.id,
            AttendanceConfirmation.occurred.is_(True),
        )
    )
    if not confirmation or as_utc(activity.starts_at) > utcnow() or activity.status != "completed":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Сначала подтвердите, что встреча состоялась"
        )
    if body.target_user_id == actor.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нельзя оценить себя")
    participants = {
        activity.author_id,
        *db.scalars(
            select(Response.user_id).where(
                Response.activity_id == activity.id, Response.status == "accepted"
            )
        ).all(),
    }
    if body.target_user_id not in participants or blocked_between(
        db, actor.id, body.target_user_id
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Этого пользователя нельзя оценить")
    existing = db.scalar(
        select(Rating).where(
            Rating.activity_id == activity.id,
            Rating.author_id == actor.id,
            Rating.target_id == body.target_user_id,
        )
    )
    if existing:
        return {"id": existing.id, "status": "already_submitted"}
    rating = Rating(
        activity_id=activity.id,
        author_id=actor.id,
        target_id=body.target_user_id,
        score=body.score,
        review=body.review.strip(),
    )
    db.add(rating)
    db.flush()
    track(
        db,
        "rating_submitted",
        actor,
        activity,
        {"target_user_id": body.target_user_id, "score": body.score},
    )
    db.commit()
    return {"id": rating.id, "status": "submitted"}
