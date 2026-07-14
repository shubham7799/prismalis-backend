from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Double, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.orm import Base


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[Optional[str]] = mapped_column(Text)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[float]] = mapped_column(Double)
    user_id: Mapped[Optional[str]] = mapped_column(Text, index=True)
    ip: Mapped[Optional[str]] = mapped_column(Text)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)
