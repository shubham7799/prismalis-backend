from datetime import date, datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.orm import Base


class Profile(Base):
    __tablename__ = "profiles"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(255))
    currency: Mapped[Optional[str]] = mapped_column(String(10))
    cik: Mapped[Optional[str]] = mapped_column(String(20))
    isin: Mapped[Optional[str]] = mapped_column(String(20))
    cusip: Mapped[Optional[str]] = mapped_column(String(20))
    exchange_full_name: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    sector: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    website: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    ceo: Mapped[Optional[str]] = mapped_column(String(255))
    country: Mapped[Optional[str]] = mapped_column(String(10))
    ipo_date: Mapped[Optional[date]] = mapped_column(Date)
    full_time_employees: Mapped[Optional[int]] = mapped_column(Integer)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    address: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(50))
    zip: Mapped[Optional[str]] = mapped_column(String(20))
    image: Mapped[Optional[str]] = mapped_column(String(255))
    last_dividend: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    beta: Mapped[Optional[float]] = mapped_column(Numeric(6, 3))
    is_etf: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_fund: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_adr: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_actively_trading: Mapped[Optional[bool]] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    quote: Mapped[Optional["Quote"]] = relationship(
        back_populates="profile", uselist=False, cascade="all, delete-orphan"
    )


class Quote(Base):
    __tablename__ = "quotes"

    symbol: Mapped[str] = mapped_column(
        String(10), ForeignKey("profiles.symbol", ondelete="CASCADE"), primary_key=True
    )
    exchange: Mapped[Optional[str]] = mapped_column(String(20))
    price: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    change: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    change_percentage: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    average_volume: Mapped[Optional[int]] = mapped_column(BigInteger)
    day_low: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    day_high: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    year_low: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    year_high: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    market_cap: Mapped[Optional[int]] = mapped_column(BigInteger)
    price_avg_50: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    price_avg_200: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    open: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    previous_close: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    quote_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    profile: Mapped["Profile"] = relationship(back_populates="quote")
