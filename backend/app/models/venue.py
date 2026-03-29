import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import String, Float, Integer, DateTime, Enum as SAEnum, Boolean, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
import enum

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.match import Match


class PitchType(str, enum.Enum):
    BATTING = "batting"
    BOWLING = "bowling"
    BALANCED = "balanced"


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4)
    cricbuzz_venue_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    stats_last_synced: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    pitch_type: Mapped[PitchType] = mapped_column(
        SAEnum(PitchType, native_enum=False), default=PitchType.BALANCED
    )
    avg_first_innings_score_t20: Mapped[float | None] = mapped_column(Float)
    avg_second_innings_score_t20: Mapped[float | None] = mapped_column(Float)
    pace_wickets_pct: Mapped[float | None] = mapped_column(Float)
    spin_wickets_pct: Mapped[float | None] = mapped_column(Float)
    dew_factor: Mapped[bool] = mapped_column(Boolean, default=False)
    capacity: Mapped[int | None] = mapped_column(Integer)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    matches: Mapped[list["Match"]] = relationship("Match", back_populates="venue", lazy="select")
