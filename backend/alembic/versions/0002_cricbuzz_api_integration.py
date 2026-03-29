"""cricbuzz_api_integration

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- players: new columns ---
    op.add_column("players", sa.Column("ipl_squad_id", sa.Integer(), nullable=True))
    op.add_column("players", sa.Column("stats_last_synced", sa.DateTime(timezone=True), nullable=True))

    # --- matches: new columns ---
    op.add_column("matches", sa.Column("cricbuzz_series_id", sa.Integer(), nullable=True, server_default="9241"))
    op.add_column("matches", sa.Column("venue_cricbuzz_id", sa.Integer(), nullable=True))

    # --- venues: new columns ---
    op.add_column("venues", sa.Column("cricbuzz_venue_id", sa.Integer(), nullable=True))
    op.add_column("venues", sa.Column("stats_last_synced", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_venues_cricbuzz_venue_id", "venues", ["cricbuzz_venue_id"], unique=True)

    # --- player_format_stats (new table) ---
    op.create_table(
        "player_format_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id"),
            nullable=False,
        ),
        sa.Column(
            "format",
            sa.Enum("T20", "ODI", "TEST", name="cricketformat"),
            nullable=False,
        ),
        sa.Column("innings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("strike_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hundreds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fifties", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wickets", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bowling_avg", sa.Float(), nullable=False, server_default="0"),
        sa.Column("economy", sa.Float(), nullable=False, server_default="0"),
        sa.Column("best_bowling", sa.String(20), nullable=True),
        sa.Column("last_synced", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_player_format_stats_player_id", "player_format_stats", ["player_id"])
    op.create_unique_constraint(
        "uq_player_format_stats_player_format",
        "player_format_stats",
        ["player_id", "format"],
    )

    # --- api_call_log (new table) ---
    op.create_table(
        "api_call_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("response_code", sa.Integer(), nullable=False, server_default="200"),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("month_year", sa.String(7), nullable=False),
    )
    op.create_index("ix_api_call_log_endpoint", "api_call_log", ["endpoint"])
    op.create_index("ix_api_call_log_called_at", "api_call_log", ["called_at"])
    op.create_index("ix_api_call_log_month_year", "api_call_log", ["month_year"])


def downgrade() -> None:
    op.drop_table("api_call_log")
    op.drop_table("player_format_stats")
    op.execute("DROP TYPE IF EXISTS cricketformat")

    op.drop_index("ix_venues_cricbuzz_venue_id", table_name="venues")
    op.drop_column("venues", "stats_last_synced")
    op.drop_column("venues", "cricbuzz_venue_id")

    op.drop_column("matches", "venue_cricbuzz_id")
    op.drop_column("matches", "cricbuzz_series_id")

    op.drop_column("players", "stats_last_synced")
    op.drop_column("players", "ipl_squad_id")
