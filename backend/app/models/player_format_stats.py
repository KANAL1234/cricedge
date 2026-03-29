import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime, Enum as SAEnum, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import enum

from app.core.database import Base


class CricketFormat(str, enum.Enum):
    T20 = "T20"
    ODI = "ODI"
    TEST = "TEST"


class PlayerFormatStats(Base):
    __tablename__ = "player_format_stats"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4)
    player_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=False), ForeignKey("players.id"), nullable=False, index=True
    )
    format: Mapped[CricketFormat] = mapped_column(
        SAEnum(CricketFormat, native_enum=False), nullable=False
    )

    # Batting
    innings: Mapped[int] = mapped_column(Integer, default=0)
    runs: Mapped[int] = mapped_column(Integer, default=0)
    avg: Mapped[float] = mapped_column(Float, default=0.0)
    strike_rate: Mapped[float] = mapped_column(Float, default=0.0)
    hundreds: Mapped[int] = mapped_column(Integer, default=0)
    fifties: Mapped[int] = mapped_column(Integer, default=0)

    # Bowling
    wickets: Mapped[int] = mapped_column(Integer, default=0)
    bowling_avg: Mapped[float] = mapped_column(Float, default=0.0)
    economy: Mapped[float] = mapped_column(Float, default=0.0)
    best_bowling: Mapped[str | None] = mapped_column(String(20))

    last_synced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    player: Mapped["Player"] = relationship("Player", back_populates="format_stats", lazy="select")


# Avoid circular import
from app.models.player import Player  # noqa: E402
