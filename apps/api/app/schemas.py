from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .models import Level


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=10000)


class DevAuthRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=128)
    username: str | None = Field(default=None, max_length=64)


class SessionResponse(BaseModel):
    access_token: str
    expires_in: int
    onboarding_completed: bool


class UserSportInput(BaseModel):
    sport_id: str = Field(min_length=1, max_length=40)
    level: Level


class ProfileUpdate(BaseModel):
    age: int = Field(ge=1, le=120)
    bio: str = Field(default="", max_length=500)
    district_id: str = Field(min_length=1, max_length=40)
    sports: list[UserSportInput] = Field(min_length=1, max_length=10)

    @field_validator("sports")
    @classmethod
    def unique_sports(cls, value: list[UserSportInput]):
        if len({item.sport_id for item in value}) != len(value):
            raise ValueError("Вид спорта можно выбрать только один раз")
        return value


class PublicProfile(BaseModel):
    id: str
    first_name: str
    last_name: str | None
    photo_url: str | None
    age: int | None
    bio: str
    district_id: str | None
    sports: list[UserSportInput]
    rating_average: float | None
    rating_count: int


class OwnProfile(PublicProfile):
    username: str | None
    onboarding_completed: bool


class LookupItem(BaseModel):
    id: str
    name: str
    emoji: str | None = None
    timezone: str | None = None


class ActivityCreate(BaseModel):
    sport_id: str = Field(min_length=1, max_length=40)
    district_id: str = Field(min_length=1, max_length=40)
    level: Level
    starts_at: datetime
    place: str = Field(min_length=2, max_length=200)
    players_needed: int | None
    comment: str = Field(default="", max_length=1000)
    client_request_id: str = Field(min_length=8, max_length=64)

    @field_validator("starts_at")
    @classmethod
    def timezone_required(cls, value: datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите часовой пояс")
        return value

    @field_validator("place")
    @classmethod
    def non_blank_place(cls, value: str):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Укажите место встречи")
        return value


class ActivityUpdate(BaseModel):
    sport_id: str | None = Field(default=None, min_length=1, max_length=40)
    district_id: str | None = Field(default=None, min_length=1, max_length=40)
    level: Level | None = None
    starts_at: datetime | None = None
    place: str | None = Field(default=None, min_length=2, max_length=200)
    players_needed: int | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("starts_at")
    @classmethod
    def optional_timezone_required(cls, value: datetime | None):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Укажите часовой пояс")
        return value

    @field_validator("place")
    @classmethod
    def optional_non_blank_place(cls, value: str | None):
        if value is None:
            return None
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Укажите место встречи")
        return value


class ActivityAuthor(BaseModel):
    id: str
    first_name: str
    age: int | None
    photo_url: str | None
    rating_average: float | None
    rating_count: int


class ActivityOut(BaseModel):
    id: str
    author: ActivityAuthor
    sport_id: str
    sport_name: str
    sport_emoji: str
    district_id: str
    district_name: str
    level: str
    starts_at: datetime
    timezone: str
    place: str
    players_needed: int | None
    accepted_count: int
    remaining_places: int | None
    response_count: int
    comment: str
    status: str
    is_owner: bool
    my_response_id: str | None
    my_response_status: str | None
    can_respond: bool
    can_confirm_result: bool = False
    meeting_result: str = "unknown"


class Page(BaseModel):
    items: list[ActivityOut]
    page: int
    page_size: int
    has_more: bool


class ResponseOut(BaseModel):
    id: str
    status: str
    decision_reason: str | None
    created_at: datetime
    user: PublicProfile


class ContactOut(BaseModel):
    user_id: str
    display_name: str
    telegram_url: str
    username_available: bool
    notice: str | None = None


class ResultInput(BaseModel):
    occurred: bool


class RatingInput(BaseModel):
    target_user_id: str
    score: int = Field(ge=1, le=5)
    review: str = Field(default="", max_length=500)


class ReportInput(BaseModel):
    target_user_id: str
    activity_id: str | None = None
    reason: Literal["spam", "abuse", "suspicious", "no_show", "other"]
    details: str = Field(default="", max_length=500)


class BlockInput(BaseModel):
    target_user_id: str


class ClientEventInput(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)
    event_name: str
    activity_id: str | None = None
    properties: dict[str, str | int | bool | None] = Field(default_factory=dict)


class MetricsOut(BaseModel):
    period_start: date
    period_end: date
    registrations: int
    onboarding_completed: int
    activation_users: int
    activities_created: int
    activities_with_response: int
    responses_sent: int
    responses_accepted: int
    completed_activities: int
    successful_matches: int
    cancelled_activities: int
    reports: int
    notification_queue_pending: int
    notification_queue_failed: int
    past_activities: int
    pending_responses: int
    system_closed_responses: int
    reported_users: int
    active_users: int
    no_show_report_activities: int
    past_activities_with_accepted: int
    retention_d1_retained: int
    retention_d1_eligible: int
    retention_d7_retained: int
    retention_d7_eligible: int
    retention_d30_retained: int
    retention_d30_eligible: int
    onboarding_completion_rate: float | None
    activation_rate: float | None
    activities_with_response_rate: float | None
    responses_per_activity: float | None
    median_first_response_minutes: float | None
    activities_without_response_rate: float | None
    acceptance_rate: float | None
    pending_response_rate: float | None
    system_closed_response_rate: float | None
    completion_rate: float | None
    cancellation_rate: float | None
    reported_users_rate: float | None
    no_show_reports_rate: float | None
    successful_matches_per_week: float | None
    retention_d1: float | None
    retention_d7: float | None
    retention_d30: float | None
    cohort_age_days: int
    activities_by_day: dict[str, int]
    filter_sports: list[LookupItem]
    filter_districts: list[LookupItem]
    filter_levels: list[str]
    filter_sources: list[str]


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    fields: dict | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
