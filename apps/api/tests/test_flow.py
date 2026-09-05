from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal, engine
from app.main import app
from app.models import Activity, AnalyticsEvent, Response, utcnow

from .conftest import dev_login, headers, onboard


def test_core_loop_contact_and_successful_match(client):
    organizer_token = dev_login(client, 101, "Олег", "oleg")
    participant_token = dev_login(client, 202, "Лена", "lena")
    onboard(client, organizer_token)
    onboard(client, participant_token)

    create = client.post(
        "/activities",
        headers=headers(organizer_token),
        json={
            "sport_id": "running",
            "district_id": "test",
            "level": "intermediate",
            "starts_at": (utcnow() + timedelta(hours=2)).isoformat(),
            "place": "Стадион у школы",
            "players_needed": 1,
            "comment": "Темп спокойный",
            "client_request_id": "request-0001",
        },
    )
    assert create.status_code == 201, create.text
    activity_id = create.json()["id"]
    participant_id = client.get("/me", headers=headers(participant_token)).json()["id"]
    public = client.get(f"/users/{participant_id}", headers=headers(organizer_token))
    assert public.status_code == 200
    assert "username" not in public.json()
    assert "telegram_id" not in public.json()
    edited = client.patch(
        f"/activities/{activity_id}",
        headers=headers(organizer_token),
        json={"comment": "Темп спокойный, встречаемся у входа"},
    )
    assert edited.status_code == 200, edited.text
    feed = client.get("/activities", headers=headers(participant_token))
    assert feed.status_code == 200, feed.text
    assert [item["id"] for item in feed.json()["items"]] == [activity_id]

    before = client.get(
        f"/activities/{activity_id}/contact/{participant_id}", headers=headers(organizer_token)
    )
    assert before.status_code == 403

    sent = client.post(f"/activities/{activity_id}/respond", headers=headers(participant_token))
    assert sent.status_code == 201, sent.text
    response_id = sent.json()["id"]
    duplicate = client.post(
        f"/activities/{activity_id}/respond", headers=headers(participant_token)
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == response_id

    accepted = client.patch(f"/responses/{response_id}/accept", headers=headers(organizer_token))
    assert accepted.status_code == 200, accepted.text
    accepted_again = client.patch(
        f"/responses/{response_id}/accept", headers=headers(organizer_token)
    )
    assert accepted_again.status_code == 200

    contact = client.get(
        f"/activities/{activity_id}/contact/{participant_id}", headers=headers(organizer_token)
    )
    assert contact.status_code == 200
    assert contact.json()["telegram_url"] == "https://t.me/lena"

    with SessionLocal() as db:
        activity = db.get(Activity, activity_id)
        activity.starts_at = utcnow() - timedelta(minutes=5)
        activity.status = "completed"
        db.commit()
    confirmed = client.post(
        f"/activities/{activity_id}/confirm-result",
        headers=headers(participant_token),
        json={"occurred": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    organizer_id = client.get("/me", headers=headers(organizer_token)).json()["id"]
    rating = client.post(
        f"/activities/{activity_id}/ratings",
        headers=headers(participant_token),
        json={"target_user_id": organizer_id, "score": 5, "review": "Отличная пробежка"},
    )
    assert rating.status_code == 201, rating.text

    metrics = client.get(
        "/internal/metrics?period_start=2020-01-01&period_end=2030-01-01",
        headers={"X-Internal-Key": "test-internal-key"},
    )
    assert metrics.status_code == 200, metrics.text
    assert metrics.json()["successful_matches"] == 1
    assert metrics.json()["activities_with_response_rate"] == 1.0
    assert metrics.json()["median_first_response_minutes"] is not None
    with SessionLocal() as db:
        assert db.query(AnalyticsEvent).filter_by(event_name="response_accepted").count() == 1


def test_owner_rights_self_response_and_block(client):
    owner = dev_login(client, 301, "Ира", "ira")
    stranger = dev_login(client, 302, "Макс", "max")
    onboard(client, owner)
    onboard(client, stranger)
    created = client.post(
        "/activities",
        headers=headers(owner),
        json={
            "sport_id": "football",
            "district_id": "test",
            "level": "beginner",
            "starts_at": (utcnow() + timedelta(days=1)).isoformat(),
            "place": "Поле",
            "players_needed": 2,
            "client_request_id": "request-0002",
        },
    ).json()
    activity_id = created["id"]
    assert (
        client.post(f"/activities/{activity_id}/respond", headers=headers(owner)).status_code == 409
    )
    assert (
        client.patch(
            f"/activities/{activity_id}", headers=headers(stranger), json={"comment": "hack"}
        ).status_code
        == 403
    )
    response = client.post(f"/activities/{activity_id}/respond", headers=headers(stranger))
    assert response.status_code == 201
    cancelled = client.patch(
        f"/responses/{response.json()['id']}/cancel", headers=headers(stranger)
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    owner_id = client.get("/me", headers=headers(owner)).json()["id"]
    assert (
        client.post(
            "/blocks", headers=headers(stranger), json={"target_user_id": owner_id}
        ).status_code
        == 201
    )
    assert client.get(f"/activities/{activity_id}", headers=headers(stranger)).status_code == 404


def test_concurrent_accept_last_place(client):
    if engine.dialect.name != "postgresql":
        pytest.skip("SELECT FOR UPDATE проверяется только на PostgreSQL")
    owner = dev_login(client, 401, "Автор", "owner")
    first = dev_login(client, 402, "Первый", "first")
    second = dev_login(client, 403, "Второй", "second")
    for token in (owner, first, second):
        onboard(client, token)
    activity_id = client.post(
        "/activities",
        headers=headers(owner),
        json={
            "sport_id": "running",
            "district_id": "test",
            "level": "intermediate",
            "starts_at": (utcnow() + timedelta(hours=2)).isoformat(),
            "place": "Парк",
            "players_needed": 1,
            "client_request_id": "concurrent-accept",
        },
    ).json()["id"]
    response_ids = [
        client.post(f"/activities/{activity_id}/respond", headers=headers(token)).json()["id"]
        for token in (first, second)
    ]

    def accept_one(response_id: str) -> int:
        with TestClient(app) as isolated:
            return isolated.patch(
                f"/responses/{response_id}/accept", headers=headers(owner)
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(accept_one, response_ids))
    assert sorted(statuses) == [200, 409]
    with SessionLocal() as db:
        accepted = db.query(Response).filter_by(activity_id=activity_id, status="accepted").count()
        assert accepted == 1
