import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db
from .models import User


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None
    photo_url: str | None
    acquisition_source: str


def validate_telegram_init_data(
    init_data: str, bot_token: str, max_age_seconds: int, now: int | None = None
) -> TelegramIdentity:
    if not init_data or not bot_token:
        raise ValueError("Telegram-авторизация не настроена")
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", None)
    if not received_hash:
        raise ValueError("Отсутствует подпись Telegram")
    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        raise ValueError("Неверная подпись Telegram")
    try:
        auth_date = int(values["auth_date"])
    except (KeyError, ValueError) as exc:
        raise ValueError("Некорректная дата Telegram") from exc
    current = int(time.time()) if now is None else now
    if auth_date > current + 30 or current - auth_date > max_age_seconds:
        raise ValueError("Данные Telegram устарели")
    try:
        user = json.loads(values["user"])
        telegram_id = int(user["id"])
        first_name = str(user["first_name"]).strip()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Некорректные данные пользователя Telegram") from exc
    if not first_name:
        raise ValueError("Telegram не передал имя")
    start_param = str(values.get("start_param", "unknown"))[:80]
    return TelegramIdentity(
        telegram_id=telegram_id,
        username=user.get("username"),
        first_name=first_name[:128],
        last_name=(user.get("last_name") or None),
        photo_url=(user.get("photo_url") or None),
        acquisition_source=start_param or "unknown",
    )


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="sports-mate-session-v1")


def issue_session(user: User, settings: Settings) -> str:
    return _serializer(settings).dumps({"sub": user.id, "v": 1})


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация")
    try:
        payload = _serializer(settings).loads(
            authorization.removeprefix("Bearer "), max_age=settings.session_ttl_seconds
        )
    except SignatureExpired as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Сессия истекла") from exc
    except BadSignature as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Некорректная сессия") from exc
    user = db.scalar(select(User).where(User.id == payload.get("sub")))
    if not user or user.globally_blocked_at:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Доступ ограничен")
    return user


def require_onboarded(user: User = Depends(get_current_user)) -> User:
    if not user.onboarding_completed_at:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Сначала завершите профиль")
    return user
