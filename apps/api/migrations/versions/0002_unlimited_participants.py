"""Allow activities without a participant limit.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_constraint("ck_activity_players", type_="check")
        batch_op.alter_column("players_needed", existing_type=sa.Integer(), nullable=True)
        batch_op.create_check_constraint(
            "ck_activity_players",
            "players_needed IS NULL OR players_needed BETWEEN 1 AND 20",
        )


def downgrade() -> None:
    op.execute(sa.text("UPDATE activities SET players_needed = 20 WHERE players_needed IS NULL"))
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_constraint("ck_activity_players", type_="check")
        batch_op.alter_column("players_needed", existing_type=sa.Integer(), nullable=False)
        batch_op.create_check_constraint(
            "ck_activity_players",
            "players_needed BETWEEN 1 AND 20",
        )
