import asyncio
from typing import Any, Dict, List, Mapping, Optional

import httpx


JsonValue = Any
JsonObject = Dict[str, JsonValue]


class FMPServiceError(Exception):
    """Base error raised by the FMP service."""


class FMPConfigurationError(FMPServiceError):
    """Raised when required FMP configuration is missing."""


class FMPRateLimitError(FMPServiceError):
    """Raised when FMP returns 429. Not retried — retrying a rate limit only makes it worse."""

    status_code = 429


class FMPRequestError(FMPServiceError):
    """Raised when FMP returns an error response or invalid payload."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FMPService:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://financialmodelingprep.com/",
        api_version: str = "stable",
        timeout_seconds: float = 20,
        max_retries: int = 2,
    ) -> None:
        if not api_key:
            raise FMPConfigurationError("FMP_API_KEY is required.")

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.api_version = api_version.strip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max(0, max_retries)

    async def fetch(
        self,
        endpoint: str,
        params: Optional[Mapping[str, Any]] = None,
        api_version: Optional[str] = None,
        stock_symbol: str = None,
    ) -> JsonValue:
        version = (api_version or self.api_version).strip("/")
        path = endpoint.strip("/")
        url = f"{self.base_url}/{version}/{path}"
        request_params: Dict[str, Any] = {"apikey": self.api_key}
        
        if params:
            request_params.update(
                {key: value for key, value in params.items() if value is not None}
            )

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(url, params=request_params)

                if response.status_code == 429:
                    raise FMPRateLimitError(
                        "FMP rate limit exceeded. Please try again shortly.",
                    )

                if 500 <= response.status_code < 600:
                    response.raise_for_status()

                if response.status_code >= 400:
                    raise FMPRequestError(
                        f"FMP request failed: {response.text}",
                        status_code=response.status_code,
                    )

                try:
                    return response.json()
                except ValueError as exc:
                    raise FMPRequestError("FMP returned a non-JSON response.") from exc
            except FMPRateLimitError:
                raise
            except (httpx.HTTPError, FMPRequestError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(0.5 * (2**attempt))

        if isinstance(last_error, FMPRequestError):
            raise last_error

        raise FMPRequestError(f"FMP request failed: {last_error}")

    async def search_symbols(
        self,
        query: str,
        limit: int = 10,
        exchange: Optional[str] = None,
    ) -> List[JsonObject]:
        return await self.fetch(
            "search",
            params={"query": query, "limit": limit, "exchange": exchange},
        )

    async def get_stock_list(self) -> List[JsonObject]:
        return await self.fetch("stock/list")

    async def get_company_profile(self, symbol: str) -> List[JsonObject]:
        return await self.fetch(f"profile", params={"symbol": symbol.upper()})

    async def get_quote(self, symbol: str) -> List[JsonObject]:
        return await self.fetch(f"quote", params={"symbol": symbol.upper()})

    async def get_income_statements(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[JsonObject]:
        return await self.fetch(
            f"income-statement",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    async def get_balance_sheets(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[JsonObject]:
        return await self.fetch(
            f"balance-sheet-statement",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    async def get_cash_flow_statements(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[JsonObject]:
        return await self.fetch(
            f"cash-flow-statement",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    async def get_key_metrics(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[JsonObject]:
        return await self.fetch(
            f"key-metrics",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    async def get_ratios(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[JsonObject]:
        return await self.fetch(
            f"ratios",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    async def get_financial_growth(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[JsonObject]:
        return await self.fetch(
            f"financial-growth",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    async def get_enterprise_values(
        self,
        symbol: str,
        period: str = "annual",
        limit: int = 5,
    ) -> List[JsonObject]:
        return await self.fetch(
            f"enterprise-values",
            params={"symbol": symbol.upper(), "period": period, "limit": limit},
        )

    async def screen_stocks(
        self,
        market_cap_min: Optional[float] = None,
        market_cap_max: Optional[float] = None,
        pe_min: Optional[float] = None,
        pe_max: Optional[float] = None,
        price_min: Optional[float] = None,
        price_max: Optional[float] = None,
        beta_min: Optional[float] = None,
        beta_max: Optional[float] = None,
        volume_min: Optional[float] = None,
        dividend_min: Optional[float] = None,
        sector: Optional[str] = None,
        industry: Optional[str] = None,
        exchange: Optional[str] = None,
        country: Optional[str] = None,
        limit: int = 20,
    ) -> List[JsonObject]:
        return await self.fetch(
            "stock-screener",
            api_version="v3",
            params={
                "marketCapMoreThan": market_cap_min,
                "marketCapLowerThan": market_cap_max,
                "peMoreThan": pe_min,
                "peLowerThan": pe_max,
                "priceMoreThan": price_min,
                "priceLowerThan": price_max,
                "betaMoreThan": beta_min,
                "betaLowerThan": beta_max,
                "volumeMoreThan": volume_min,
                "dividendMoreThan": dividend_min,
                "sector": sector,
                "industry": industry,
                "exchange": exchange,
                "country": country,
                "limit": limit,
            },
        )

    async def get_historical_prices(
        self,
        symbol: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        timeseries: Optional[int] = None,
    ) -> JsonObject:
        return await self.fetch(
            f"historical-price-full",
            params={"symbol": symbol.upper(), "from": from_date, "to": to_date, "timeseries": timeseries},
        )

