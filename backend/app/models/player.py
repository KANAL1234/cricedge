import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Float, Integer, DateTime, Enum as SAEnum, ForeignKey, Boolean, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import enum

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.innings import PlayerMatchStats, BallByBall
    from app.models.player_format_stats import PlayerFormatStats


class PlayerRole(str, enum.Enum):
    BATSMAN = "BAT"
    BOWLER = "BOWL"
    ALL_ROUNDER = "AR"
    WICKET_KEEPER = "WK"


class Player(Base):
    __tablename__ = "players"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(300))
    short_name: Mapped[str | None] = mapped_column(String(50))
    cricbuzz_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    cricsheet_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    espn_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    country: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    role: Mapped[PlayerRole] = mapped_column(
        SAEnum(PlayerRole, native_enum=False), nullable=False, default=PlayerRole.BATSMAN
    )
    batting_style: Mapped[str | None] = mapped_column(String(50))
    bowling_style: Mapped[str | None] = mapped_column(String(100))
    ipl_team: Mapped[str | None] = mapped_column(String(100))
    ipl_squad_id: Mapped[int | None] = mapped_column(Integer)
    stats_last_synced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dream11_price: Mapped[float] = mapped_column(Float, default=8.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    match_stats: Mapped[list["PlayerMatchStats"]] = relationship(
        "PlayerMatchStats", back_populates="player", lazy="select"
    )
    balls_faced_as_batter: Mapped[list["BallByBall"]] = relationship(
        "BallByBall",
        foreign_keys="BallByBall.batter_id",
        back_populates="batter",
        lazy="select",
    )
    balls_bowled: Mapped[list["BallByBall"]] = relationship(
        "BallByBall",
        foreign_keys="BallByBall.bowler_id",
        back_populates="bowler",
        lazy="select",
    )
    format_stats: Mapped[list["PlayerFormatStats"]] = relationship(
        "PlayerFormatStats", back_populates="player", lazy="select"
    )
