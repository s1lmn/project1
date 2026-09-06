import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import and_, or_, select

from .config import get_settings
from .database import SessionLocal
from .models import Activity, NotificationJob, Response, User, UserBlock, as_utc, utcnow
from .services import track

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("sports_mate.worker")


def close_stale_activities() -> int:
    changed = 0
    with SessionLocal() as db:
        activities = db.scalars(
            select(Activity)
            .where(Activity.status.in_(["active", "filled"]))
            .with_for_update(skip_locked=True)
        ).all()
        now = utcnow()
        for activity in activities:
            if as_utc(activity.starts_at) <= now:
                accepted = any(x.status == "accepted" for x in activity.responses)
                if not accepted:
                    activity.status = "expired"
                    for response in activity.responses:
                        if response.status == "pending":
                            response.status = "rejected"
                            response.rejected_at = now
                            response.decision_reason = "recruitment_closed"
                    changed += 1
                elif (
                    as_utc(activity.starts_at) + timedelta(hours=settings.auto_complete_hours_after)
                    <= now
                ):
                    activity.status = "completed"
                    track(
                        db,
                        "activity_completed",
                        activity=activity,
                        properties={"source": "worker", "confirmed": False},
                    )
                    changed += 1
            elif as_utc(activity.expires_at) <= now and not activity.had_response:
                activity.status = "expired"
                changed += 1
        db.commit()
    return changed


def _valid_job(db, job: NotificationJob) -> tuple[bool, User | None, Activity | None]:
    recipient = db.get(User, job.recipient_id)
    activity = db.get(Activity, job.activity_id) if job.activity_id else None
    if not recipient or recipient.globally_blocked_at:
        return False, recipient, activity
    counterpart_id = job.payload.get("counterpart_id")
    if counterpart_id and db.scalar(
        select(UserBlock.blocker_id).where(
            or_(
                and_(
                    UserBlock.blocker_id == recipient.id,
                    UserBlock.blocked_id == counterpart_id,
                ),
                and_(
                    UserBlock.blocker_id == counterpart_id,
                    UserBlock.blocked_id == recipient.id,
                ),
            )
        )
    ):
        return False, recipient, activity
    if activity and job.event_type in {"reminder", "result_request"}:
        if activity.status in {"cancelled", "expired"}:
            return False, recipient, activity
        eligible = recipient.id == activity.author_id or bool(
            db.scalar(
                select(Response.id).where(
                    Response.activity_id == activity.id,
                    Response.user_id == recipient.id,
                    Response.status == "accepted",
                )
            )
        )
        if not eligible:
            return False, recipient, activity
        if job.event_type == "result_request" and not db.scalar(
            select(Response.id).where(
                Response.activity_id == activity.id, Response.status == "accepted"
            )
        ):
            return False, recipient, activity
    return True, recipient, activity


def _message(job: NotificationJob, activity: Activity | None) -> str:
    sport = activity.sport.name if activity else "активность"
    starts = activity.starts_at.strftime("%d.%m %H:%M") if activity else ""
    messages = {
        "new_response": f"Новый отклик на {sport} {starts}.",
        "response_accepted": f"Ваш отклик на {sport} принят!",
        "response_rejected": f"Организатор отклонил отклик на {sport}.",
        "activity_cancelled": f"Активность {sport} {starts} отменена.",
        "reminder": f"Напоминание: {sport} начнётся {starts}.",
        "result_request": f"Как прошла встреча {sport}? Подтвердите результат и оставьте оценку.",
    }
    return messages.get(job.event_type, "Обновление SPORTS MATE")


def deliver_jobs() -> int:
    delivered = 0
    with SessionLocal() as db:
        jobs = db.scalars(
            select(NotificationJob)
            .where(NotificationJob.status == "pending", NotificationJob.scheduled_at <= utcnow())
            .order_by(NotificationJob.scheduled_at)
            .limit(50)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            valid, recipient, activity = _valid_job(db, job)
            if not valid:
                job.status = "suppressed"
                continue
            job.attempts += 1
            if not settings.telegram_notifications_enabled or not settings.telegram_bot_token:
                logger.info(
                    "DEV notification type=%s recipient=%s activity=%s",
                    job.event_type,
                    job.recipient_id,
                    job.activity_id,
                )
                job.status = "delivered"
                job.delivered_at = utcnow()
                delivered += 1
                continue
            try:
                url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
                deep_link = (
                    f"{settings.telegram_webapp_url}/activities/{activity.id}"
                    if activity
                    else settings.telegram_webapp_url
                )
                response = httpx.post(
                    url,
                    json={
                        "chat_id": recipient.telegram_id,
                        "text": _message(job, activity),
                        "reply_markup": {
                            "inline_keyboard": [
                                [{"text": "Открыть SPORTS MATE", "web_app": {"url": deep_link}}]
                            ]
                        },
                    },
                    timeout=10,
                )
                response.raise_for_status()
                job.status = "delivered"
                job.delivered_at = utcnow()
                delivered += 1
            except Exception as exc:
                job.last_error = type(exc).__name__
                if job.attempts >= settings.notification_max_attempts:
                    job.status = "failed"
                else:
                    job.scheduled_at = utcnow() + timedelta(minutes=min(2**job.attempts, 60))
        db.commit()
    return delivered


def run_once() -> tuple[int, int]:
    return close_stale_activities(), deliver_jobs()


def main() -> None:
    logger.info("SPORTS MATE worker started")
    while True:
        try:
            changed, delivered = run_once()
            if changed or delivered:
                logger.info("worker changed=%s delivered=%s", changed, delivered)
        except Exception:
            logger.exception("worker iteration failed")
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
