"""Initial SPORTS MATE schema and configurable dev lookups.

Revision ID: 0001
Revises:
"""

from alembic import op

from app import models  # noqa: F401
from app.database import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    sports = models.Sport.__table__
    districts = models.District.__table__
    op.bulk_insert(
        sports,
        [
            {"id": "basketball", "name": "Баскетбол", "emoji": "🏀", "is_enabled": True},
            {"id": "football", "name": "Футбол", "emoji": "⚽", "is_enabled": True},
            {"id": "volleyball", "name": "Волейбол", "emoji": "🏐", "is_enabled": True},
            {"id": "running", "name": "Бег", "emoji": "🏃", "is_enabled": True},
        ],
    )
    op.bulk_insert(
        districts,
        [
            {
                "id": "test-cluster",
                "name": "Тестовый район",
                "timezone": "Europe/Moscow",
                "is_enabled": True,
            }
        ],
    )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
