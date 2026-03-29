import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, Boolean, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.player import Player
    from app.models.match import Match


class PlayerMatchStats(Base):
    """Aggregated per-player stats for a single match innings."""
    __tablename__ = "player_match_stats"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("players.id"), nullable=False, index=True
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("matches.id"), nullable=False, index=True
    )
    innings_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    balls_faced: Mapped[int] = mapped_column(Integer, default=0)
    fours: Mapped[int] = mapped_column(Integer, default=0)
    sixes: Mapped[int] = mapped_column(Integer, default=0)
    strike_rate: Mapped[float] = mapped_column(Float, default=0.0)
    batting_position: Mapped[int | None] = mapped_column(Integer)
    is_out: Mapped[bool] = mapped_column(Boolean, default=False)
    wickets: Mapped[int] = mapped_column(Integer, default=0)
    overs_bowled: Mapped[float] = mapped_column(Float, default=0.0)
    runs_conceded: Mapped[int] = mapped_column(Integer, default=0)
    economy: Mapped[float] = mapped_column(Float, default=0.0)
    maidens: Mapped[int] = mapped_column(Integer, default=0)
    catches: Mapped[int] = mapped_column(Integer, default=0)
    stumpings: Mapped[int] = mapped_column(Integer, default=0)
    run_outs: Mapped[int] = mapped_column(Integer, default=0)
    run_outs_direct: Mapped[int] = mapped_column(Integer, default=0)
    dream11_points: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    player: Mapped["Player"] = relationship("Player", back_populates="match_stats", lazy="select")
    match: Mapped["Match"] = relationship("Match", back_populates="player_stats", lazy="select")


class BallByBall(Base):
    """One row per delivery."""
    __tablename__ = "ball_by_ball"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4)
    match_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("matches.id"), nullable=False, index=True
    )
    innings_number: Mapped[int] = mapped_column(Integer, nullable=False)
    over_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ball_number: Mapped[int] = mapped_column(Integer, nullable=False)
    batter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("players.id"), nullable=False
    )
    bowler_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("players.id"), nullable=False
    )
    non_striker_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("players.id")
    )
    runs_batter: Mapped[int] = mapped_column(Integer, default=0)
    runs_extras: Mapped[int] = mapped_column(Integer, default=0)
    runs_total: Mapped[int] = mapped_column(Integer, default=0)
    extras_type: Mapped[str | None] = mapped_column(String(20))
    wicket_type: Mapped[str | None] = mapped_column(String(50))
    dismissed_player_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("players.id"), nullable=True
    )
    fielder_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("players.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    match: Mapped["Match"] = relationship("Match", back_populates="balls", lazy="select")
    batter: Mapped["Player"] = relationship(
        "Player", foreign_keys=[batter_id], back_populates="balls_faced_as_batter", lazy="select"
    )
    bowler: Mapped["Player"] = relationship(
        "Player", foreign_keys=[bowler_id], back_populates="balls_bowled", lazy="select"
    )
