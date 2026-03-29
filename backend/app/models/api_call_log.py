import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class ApiCallLog(Base):
    __tablename__ = "api_call_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True, native_uuid=False), primary_key=True, default=uuid.uuid4)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_code: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    called_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    month_year: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # e.g. "2026-03"
