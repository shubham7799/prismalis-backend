from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import func

from app.core.orm import get_session
from app.models.market_data import Profile, Quote

PROFILE_TTL = timedelta(hours=24)
QUOTE_TTL = timedelta(minutes=5)


def _to_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


def _to_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _to_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    return date.fromisoformat(value)


def is_stale(updated_at: Optional[datetime], ttl: timedelta) -> bool:
    if updated_at is None:
        return True
    return datetime.now(timezone.utc) - updated_at >= ttl


def profile_to_dict(profile: Profile) -> dict:
    return {
        "symbol": profile.symbol,
        "companyName": profile.company_name,
        "currency": profile.currency,
        "cik": profile.cik,
        "isin": profile.isin,
        "cusip": profile.cusip,
        "exchangeFullName": profile.exchange_full_name,
        "sector": profile.sector,
        "industry": profile.industry,
        "website": profile.website,
        "description": profile.description,
        "ceo": profile.ceo,
        "country": profile.country,
        "ipoDate": profile.ipo_date.isoformat() if profile.ipo_date else None,
        "fullTimeEmployees": profile.full_time_employees,
        "phone": profile.phone,
        "address": profile.address,
        "city": profile.city,
        "state": profile.state,
        "zip": profile.zip,
        "image": profile.image,
        "lastDividend": float(profile.last_dividend) if profile.last_dividend is not None else None,
        "beta": float(profile.beta) if profile.beta is not None else None,
        "isEtf": profile.is_etf,
        "isFund": profile.is_fund,
        "isAdr": profile.is_adr,
        "isActivelyTrading": profile.is_actively_trading,
    }


def quote_to_dict(quote: Quote) -> dict:
    return {
        "symbol": quote.symbol,
        "exchange": quote.exchange,
        "price": float(quote.price) if quote.price is not None else None,
        "change": float(quote.change) if quote.change is not None else None,
        "changePercentage": float(quote.change_percentage) if quote.change_percentage is not None else None,
        "volume": quote.volume,
        "avgVolume": quote.average_volume,
        "dayLow": float(quote.day_low) if quote.day_low is not None else None,
        "dayHigh": float(quote.day_high) if quote.day_high is not None else None,
        "yearLow": float(quote.year_low) if quote.year_low is not None else None,
        "yearHigh": float(quote.year_high) if quote.year_high is not None else None,
        "marketCap": quote.market_cap,
        "priceAvg50": float(quote.price_avg_50) if quote.price_avg_50 is not None else None,
        "priceAvg200": float(quote.price_avg_200) if quote.price_avg_200 is not None else None,
        "open": float(quote.open) if quote.open is not None else None,
        "previousClose": float(quote.previous_close) if quote.previous_close is not None else None,
        "timestamp": int(quote.quote_timestamp.timestamp()) if quote.quote_timestamp else None,
    }


class MarketDataService:
    async def get_profile(self, symbol: str) -> Optional[Profile]:
        async with get_session() as session:
            return await session.get(Profile, symbol.upper())

    async def get_quote(self, symbol: str) -> Optional[Quote]:
        async with get_session() as session:
            return await session.get(Quote, symbol.upper())

    async def upsert_profile(self, profile: Mapping[str, Any]) -> None:
        values = {
            "symbol": profile["symbol"].upper(),
            "company_name": profile.get("companyName"),
            "currency": profile.get("currency"),
            "cik": profile.get("cik"),
            "isin": profile.get("isin"),
            "cusip": profile.get("cusip"),
            "exchange_full_name": profile.get("exchangeFullName"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "website": profile.get("website"),
            "description": profile.get("description"),
            "ceo": profile.get("ceo"),
            "country": profile.get("country"),
            "ipo_date": _to_date(profile.get("ipoDate")),
            "full_time_employees": _to_int(profile.get("fullTimeEmployees")),
            "phone": profile.get("phone"),
            "address": profile.get("address"),
            "city": profile.get("city"),
            "state": profile.get("state"),
            "zip": profile.get("zip"),
            "image": profile.get("image"),
            "last_dividend": profile.get("lastDividend"),
            "beta": profile.get("beta"),
            "is_etf": profile.get("isEtf"),
            "is_fund": profile.get("isFund"),
            "is_adr": profile.get("isAdr"),
            "is_actively_trading": profile.get("isActivelyTrading"),
        }

        stmt = insert(Profile).values(**values)
        update_values = {column: stmt.excluded[column] for column in values if column != "symbol"}
        update_values["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=[Profile.symbol], set_=update_values)

        async with get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def ensure_profile_stub(self, symbol: str, company_name: Optional[str] = None) -> None:
        stmt = insert(Profile).values(symbol=symbol.upper(), company_name=company_name)
        stmt = stmt.on_conflict_do_nothing(index_elements=[Profile.symbol])

        async with get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def upsert_quote(self, quote: Mapping[str, Any]) -> None:
        symbol = quote["symbol"].upper()
        await self.ensure_profile_stub(symbol, quote.get("name"))

        values = {
            "symbol": symbol,
            "exchange": quote.get("exchange"),
            "price": quote.get("price"),
            "change": quote.get("change"),
            "change_percentage": quote.get("changePercentage"),
            "volume": _to_int(quote.get("volume")),
            "average_volume": _to_int(quote.get("avgVolume")),
            "day_low": quote.get("dayLow"),
            "day_high": quote.get("dayHigh"),
            "year_low": quote.get("yearLow"),
            "year_high": quote.get("yearHigh"),
            "market_cap": _to_int(quote.get("marketCap")),
            "price_avg_50": quote.get("priceAvg50"),
            "price_avg_200": quote.get("priceAvg200"),
            "open": quote.get("open"),
            "previous_close": quote.get("previousClose"),
            "quote_timestamp": _to_datetime(quote.get("timestamp")),
        }

        stmt = insert(Quote).values(**values)
        update_values = {column: stmt.excluded[column] for column in values if column != "symbol"}
        update_values["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=[Quote.symbol], set_=update_values)

        async with get_session() as session:
            await session.execute(stmt)
            await session.commit()


class StockDataService:
    def __init__(self, fmp_service, market_data_service: Optional[MarketDataService] = None):
        self.fmp_service = fmp_service
        self.market_data_service = market_data_service or MarketDataService()

    async def _fresh_profile(self, symbol: str, profile_row: Optional[Profile]) -> Optional[Profile]:
        if not is_stale(profile_row.updated_at if profile_row else None, PROFILE_TTL):
            return profile_row

        fetched = await self.fmp_service.get_company_profile(symbol)
        if not fetched:
            return profile_row

        await self.market_data_service.upsert_profile(fetched[0])
        return await self.market_data_service.get_profile(symbol)

    async def _fresh_quote(self, symbol: str, quote_row: Optional[Quote]) -> Optional[Quote]:
        if not is_stale(quote_row.updated_at if quote_row else None, QUOTE_TTL):
            return quote_row

        fetched = await self.fmp_service.get_quote(symbol)
        if not fetched:
            return quote_row

        await self.market_data_service.upsert_quote(fetched[0])
        return await self.market_data_service.get_quote(symbol)

    async def get_profile_with_quote(self, symbol: str) -> dict:
        symbol = symbol.upper()
        profile_row = await self._fresh_profile(symbol, await self.market_data_service.get_profile(symbol))
        quote_row = await self._fresh_quote(symbol, await self.market_data_service.get_quote(symbol))

        merged: dict = {}
        if profile_row:
            merged.update(profile_to_dict(profile_row))
        if quote_row:
            merged.update(quote_to_dict(quote_row))
        return merged

    async def get_quote_only(self, symbol: str) -> dict:
        symbol = symbol.upper()
        quote_row = await self._fresh_quote(symbol, await self.market_data_service.get_quote(symbol))
        return quote_to_dict(quote_row) if quote_row else {}
