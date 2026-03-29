"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-03-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- venues ---
    op.create_table(
        "venues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("city", sa.String(100), nullable=False, server_default=""),
        sa.Column("country", sa.String(100), nullable=False, server_default=""),
        sa.Column(
            "pitch_type",
            sa.Enum("batting", "bowling", "balanced", name="pitchtype"),
            nullable=False,
            server_default="balanced",
        ),
        sa.Column("avg_first_innings_score_t20", sa.Float, nullable=True),
        sa.Column("avg_second_innings_score_t20", sa.Float, nullable=True),
        sa.Column("pace_wickets_pct", sa.Float, nullable=True),
        sa.Column("spin_wickets_pct", sa.Float, nullable=True),
        sa.Column("dew_factor", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("capacity", sa.Integer, nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
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
    op.create_index("ix_venues_name", "venues", ["name"])

    # --- players ---
    op.create_table(
        "players",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("full_name", sa.String(300), nullable=True),
        sa.Column("short_name", sa.String(50), nullable=True),
        sa.Column("cricbuzz_id", sa.String(50), nullable=True, unique=True),
        sa.Column("cricsheet_id", sa.String(100), nullable=True, unique=True),
        sa.Column("espn_id", sa.String(50), nullable=True, unique=True),
        sa.Column("country", sa.String(50), nullable=False, server_default=""),
        sa.Column(
            "role",
            sa.Enum("BAT", "BOWL", "AR", "WK", name="playerrole"),
            nullable=False,
            server_default="BAT",
        ),
        sa.Column("batting_style", sa.String(50), nullable=True),
        sa.Column("bowling_style", sa.String(100), nullable=True),
        sa.Column("ipl_team", sa.String(100), nullable=True),
        sa.Column("dream11_price", sa.Float, nullable=False, server_default="8.0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
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
    op.create_index("ix_players_name", "players", ["name"])

    # --- matches ---
    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("match_code", sa.String(100), nullable=True, unique=True),
        sa.Column("cricbuzz_id", sa.String(50), nullable=True, unique=True),
        sa.Column("date", sa.Date, nullable=True),
        sa.Column(
            "venue_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("venues.id"),
            nullable=True,
        ),
        sa.Column("team1", sa.String(100), nullable=False, server_default=""),
        sa.Column("team2", sa.String(100), nullable=False, server_default=""),
        sa.Column("team1_short", sa.String(10), nullable=True),
        sa.Column("team2_short", sa.String(10), nullable=True),
        sa.Column(
            "format",
            sa.Enum("T20", "ODI", "TEST", "T10", name="matchformat"),
            nullable=False,
            server_default="T20",
        ),
        sa.Column(
            "status",
            sa.Enum("upcoming", "live", "completed", "abandoned", name="matchstatus"),
            nullable=False,
            server_default="upcoming",
        ),
        sa.Column("competition", sa.String(200), nullable=True),
        sa.Column("series_name", sa.String(200), nullable=True),
        sa.Column("match_number", sa.Integer, nullable=True),
        sa.Column("toss_winner", sa.String(100), nullable=True),
        sa.Column("toss_decision", sa.String(10), nullable=True),
        sa.Column("result", sa.String(50), nullable=True),
        sa.Column("winner", sa.String(100), nullable=True),
        sa.Column("margin", sa.String(100), nullable=True),
        sa.Column("playing_xi_team1", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("playing_xi_team2", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("xi_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_time_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("weather", postgresql.JSONB, nullable=False, server_default="{}"),
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
    op.create_index("ix_matches_match_code", "matches", ["match_code"])

    # --- player_match_stats ---
    op.create_table(
        "player_match_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "player_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id"),
            nullable=False,
        ),
        sa.Column(
            "match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("matches.id"),
            nullable=False,
        ),
        sa.Column("innings_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("balls_faced", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fours", sa.Integer, nullable=False, server_default="0"),
        sa.Column("sixes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("strike_rate", sa.Float, nullable=False, server_default="0"),
        sa.Column("batting_position", sa.Integer, nullable=True),
        sa.Column("is_out", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("wickets", sa.Integer, nullable=False, server_default="0"),
        sa.Column("overs_bowled", sa.Float, nullable=False, server_default="0"),
        sa.Column("runs_conceded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("economy", sa.Float, nullable=False, server_default="0"),
        sa.Column("maidens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("catches", sa.Integer, nullable=False, server_default="0"),
        sa.Column("stumpings", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_outs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_outs_direct", sa.Integer, nullable=False, server_default="0"),
        sa.Column("dream11_points", sa.Float, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_player_match_stats_player_id", "player_match_stats", ["player_id"])
    op.create_index("ix_player_match_stats_match_id", "player_match_stats", ["match_id"])

    # --- ball_by_ball ---
    op.create_table(
        "ball_by_ball",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "match_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("matches.id"),
            nullable=False,
        ),
        sa.Column("innings_number", sa.Integer, nullable=False),
        sa.Column("over_number", sa.Integer, nullable=False),
        sa.Column("ball_number", sa.Integer, nullable=False),
        sa.Column(
            "batter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("players.id"), nullable=False
        ),
        sa.Column(
            "bowler_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("players.id"), nullable=False
        ),
        sa.Column(
            "non_striker_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("players.id"), nullable=True
        ),
        sa.Column("runs_batter", sa.Integer, nullable=False, server_default="0"),
        sa.Column("runs_extras", sa.Integer, nullable=False, server_default="0"),
        sa.Column("runs_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("extras_type", sa.String(20), nullable=True),
        sa.Column("wicket_type", sa.String(50), nullable=True),
        sa.Column(
            "dismissed_player_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id"),
            nullable=True,
        ),
        sa.Column(
            "fielder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("players.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_ball_by_ball_match_id", "ball_by_ball", ["match_id"])


def downgrade() -> None:
    op.drop_table("ball_by_ball")
    op.drop_table("player_match_stats")
    op.drop_table("matches")
    op.drop_table("players")
    op.drop_table("venues")
    op.execute("DROP TYPE IF EXISTS pitchtype")
    op.execute("DROP TYPE IF EXISTS playerrole")
    op.execute("DROP TYPE IF EXISTS matchformat")
    op.execute("DROP TYPE IF EXISTS matchstatus")
