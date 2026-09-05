import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./sports_mate_test.db")
os.environ.setdefault("ENABLE_DEV_AUTH", "true")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-that-is-long-enough")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app
from app.models import District, Sport


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            Sport.__table__.insert(),
            [
                {"id": "running", "name": "Бег", "emoji": "🏃", "is_enabled": True},
                {"id": "football", "name": "Футбол", "emoji": "⚽", "is_enabled": True},
            ],
        )
        connection.execute(
            District.__table__.insert(),
            [
                {
                    "id": "test",
                    "name": "Тестовый район",
                    "timezone": "Europe/Moscow",
                    "is_enabled": True,
                }
            ],
        )
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def dev_login(client: TestClient, telegram_id: int, name: str, username: str | None = None) -> str:
    response = client.post(
        "/auth/dev",
        json={"telegram_id": telegram_id, "first_name": name, "username": username},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def onboard(client: TestClient, token: str) -> None:
    response = client.patch(
        "/me",
        headers=headers(token),
        json={
            "age": 28,
            "bio": "Тренируюсь по вечерам",
            "district_id": "test",
            "sports": [{"sport_id": "running", "level": "intermediate"}],
        },
    )
    assert response.status_code == 200, response.text
