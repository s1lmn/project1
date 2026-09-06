import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.auth import validate_telegram_init_data


def signed_data(token: str, auth_date: int = 1_700_000_000, signature: str | None = None) -> str:
    data = {
        "auth_date": str(auth_date),
        "query_id": "query-1",
        "user": json.dumps(
            {"id": 42, "first_name": "Анна", "username": "anna"}, separators=(",", ":")
        ),
    }
    if signature:
        data["signature"] = signature
    check = "\n".join(f"{key}={data[key]}" for key in sorted(data))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def test_valid_telegram_signature():
    identity = validate_telegram_init_data(signed_data("token"), "token", 3600, now=1_700_000_100)
    assert identity.telegram_id == 42
    assert identity.username == "anna"
    signed_identity = validate_telegram_init_data(
        signed_data("token", signature="telegram-ed25519-value"),
        "token",
        3600,
        now=1_700_000_100,
    )
    assert signed_identity.telegram_id == 42


def test_invalid_and_expired_telegram_data():
    with pytest.raises(ValueError, match="подпись"):
        validate_telegram_init_data(signed_data("wrong"), "token", 3600, now=1_700_000_100)
    with pytest.raises(ValueError, match="устарели"):
        validate_telegram_init_data(signed_data("token"), "token", 10, now=1_700_000_100)
    with pytest.raises(ValueError, match="повторяющиеся"):
        validate_telegram_init_data(
            f"{signed_data('token')}&auth_date=1700000000",
            "token",
            3600,
            now=1_700_000_100,
        )


def test_production_dev_auth_disabled(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_DEV_AUTH", "true")
    with pytest.raises(ValueError, match="ENABLE_DEV_AUTH"):
        Settings()
