import uuid
from datetime import datetime, date as date_type
from typing import TYPE_CHECKING
from sqlalchemy import String, DateTime, Date, Enum as SAEnum, ForeignKey, JSON, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import enum

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.venue import Venue
    from app.models.innings import PlayerMatchStats, BallByBall


class MatchFormat(str, enum.Enum):
    T20 = "T20"
    ODI = "ODI"
    TEST = "TEST"
    T10 = "T10"


class MatchStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    LIVE = "live"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4)
    match_code: Mapped[str | None] = mapped_column(String(100), unique=True, index=True)
    cricbuzz_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    cricbuzz_series_id: Mapped[int | None] = mapped_column(Integer, default=9241)
    venue_cricbuzz_id: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[date_type | None] = mapped_column(Date)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("venues.id")
    )
    team1: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    team2: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    team1_short: Mapped[str | None] = mapped_column(String(10))
    team2_short: Mapped[str | None] = mapped_column(String(10))
    format: Mapped[MatchFormat] = mapped_column(
        SAEnum(MatchFormat, native_enum=False), nullable=False, default=MatchFormat.T20
    )
    status: Mapped[MatchStatus] = mapped_column(
        SAEnum(MatchStatus, native_enum=False), default=MatchStatus.UPCOMING
    )
    competition: Mapped[str | None] = mapped_column(String(200))
    series_name: Mapped[str | None] = mapped_column(String(200))
    match_number: Mapped[int | None] = mapped_column(Integer)
    toss_winner: Mapped[str | None] = mapped_column(String(100))
    toss_decision: Mapped[str | None] = mapped_column(String(10))
    result: Mapped[str | None] = mapped_column(String(50))
    winner: Mapped[str | None] = mapped_column(String(100))
    margin: Mapped[str | None] = mapped_column(String(100))
    playing_xi_team1: Mapped[dict] = mapped_column(JSON, default=dict)
    playing_xi_team2: Mapped[dict] = mapped_column(JSON, default=dict)
    xi_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    match_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_time_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weather: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    venue: Mapped["Venue | None"] = relationship("Venue", back_populates="matches", lazy="select")
    player_stats: Mapped[list["PlayerMatchStats"]] = relationship(
        "PlayerMatchStats", back_populates="match", lazy="select"
    )
    balls: Mapped[list["BallByBall"]] = relationship("BallByBall", back_populates="match", lazy="select")
