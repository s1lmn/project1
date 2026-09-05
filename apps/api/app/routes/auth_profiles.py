from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user, issue_session, validate_telegram_init_data
from ..config import Settings, get_settings
from ..database import get_db
from ..models import District, Sport, User, UserSport
from ..schemas import (
    DevAuthRequest,
    LookupItem,
    OwnProfile,
    ProfileUpdate,
    PublicProfile,
    SessionResponse,
    TelegramAuthRequest,
)
from ..services import blocked_between, public_profile, track

router = APIRouter()


def _full_user(db: Session, user_id: str) -> User:
    user = db.scalar(select(User).options(selectinload(User.sports)).where(User.id == user_id))
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return user


def _own(db: Session, user: User) -> OwnProfile:
    profile = public_profile(db, _full_user(db, user.id))
    return OwnProfile(
        **profile.model_dump(),
        username=user.username,
        onboarding_completed=bool(user.onboarding_completed_at),
    )


@router.post("/auth/telegram", response_model=SessionResponse)
def telegram_auth(
    body: TelegramAuthRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        identity = validate_telegram_init_data(
            body.init_data, settings.telegram_bot_token, settings.telegram_init_data_max_age_seconds
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user = db.scalar(select(User).where(User.telegram_id == identity.telegram_id))
    if user and user.globally_blocked_at:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Доступ ограничен")
    if not user:
        user = User(
            telegram_id=identity.telegram_id,
            username=identity.username,
            first_name=identity.first_name,
            last_name=identity.last_name,
            photo_url=identity.photo_url,
            acquisition_source=identity.acquisition_source,
        )
        db.add(user)
        db.flush()
    else:
        user.username = identity.username
        user.first_name = identity.first_name
        user.last_name = identity.last_name
        user.photo_url = identity.photo_url
    track(db, "app_opened", user)
    db.commit()
    return SessionResponse(
        access_token=issue_session(user, settings),
        expires_in=settings.session_ttl_seconds,
        onboarding_completed=bool(user.onboarding_completed_at),
    )


@router.post("/auth/dev", response_model=SessionResponse)
def dev_auth(
    body: DevAuthRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.enable_dev_auth or settings.app_env not in {"development", "test"}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Маршрут не найден")
    user = db.scalar(select(User).where(User.telegram_id == body.telegram_id))
    if not user:
        user = User(
            telegram_id=body.telegram_id,
            username=body.username,
            first_name=body.first_name,
            is_dev=True,
        )
        db.add(user)
        db.flush()
    track(db, "app_opened", user, properties={"source": "dev_auth"})
    db.commit()
    return SessionResponse(
        access_token=issue_session(user, settings),
        expires_in=settings.session_ttl_seconds,
        onboarding_completed=bool(user.onboarding_completed_at),
    )


@router.get("/lookups", response_model=dict[str, list[LookupItem]])
def lookups(db: Session = Depends(get_db)):
    sports = db.scalars(select(Sport).where(Sport.is_enabled.is_(True)).order_by(Sport.name)).all()
    districts = db.scalars(
        select(District).where(District.is_enabled.is_(True)).order_by(District.name)
    ).all()
    return {
        "sports": [LookupItem(id=x.id, name=x.name, emoji=x.emoji) for x in sports],
        "districts": [LookupItem(id=x.id, name=x.name, timezone=x.timezone) for x in districts],
    }


@router.get("/me", response_model=OwnProfile)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _own(db, user)


@router.patch("/me", response_model=OwnProfile)
def update_me(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.min_user_age <= body.age <= settings.max_user_age:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Возраст вне допустимого диапазона"
        )
    if not db.scalar(
        select(District.id).where(District.id == body.district_id, District.is_enabled.is_(True))
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Район недоступен")
    available = set(
        db.scalars(
            select(Sport.id).where(
                Sport.id.in_([x.sport_id for x in body.sports]), Sport.is_enabled.is_(True)
            )
        ).all()
    )
    if len(available) != len(body.sports):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Один из видов спорта недоступен"
        )
    first_completion = user.onboarding_completed_at is None
    user.age = body.age
    user.bio = body.bio.strip()
    user.district_id = body.district_id
    db.execute(delete(UserSport).where(UserSport.user_id == user.id))
    db.add_all(
        [UserSport(user_id=user.id, sport_id=x.sport_id, level=x.level.value) for x in body.sports]
    )
    if first_completion:
        user.onboarding_completed_at = datetime.now(timezone.utc)
        track(db, "onboarding_completed", user)
    else:
        track(db, "profile_updated", user)
    db.commit()
    return _own(db, user)


@router.get("/users/{user_id}", response_model=PublicProfile)
def get_public_profile(
    user_id: str,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _full_user(db, user_id)
    if target.globally_blocked_at or blocked_between(db, actor.id, target.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return public_profile(db, target)
