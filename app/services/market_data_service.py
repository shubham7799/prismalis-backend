import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, FrozenSet, Mapping, Optional, Sequence, Type

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import func

from app.core.orm import Base, get_session
from app.models.market_data import (
    BalanceSheet,
    CashFlowStatement,
    EnterpriseValue,
    FinancialGrowth,
    IncomeStatement,
    KeyMetrics,
    Profile,
    Quote,
    Ratios,
)

PROFILE_TTL = timedelta(hours=24)
QUOTE_TTL = timedelta(minutes=5)
DAILY_TTL = timedelta(hours=24)


# ---------------------------------------------------------------------------
# Value parsing/serialization shared by every cached table
# ---------------------------------------------------------------------------

def _parse_date(value: Any) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _parse_timestamp(value: Any) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def _parse_epoch(value: Any) -> Optional[datetime]:
    return datetime.fromtimestamp(int(value), tz=timezone.utc) if value not in (None, "") else None


def _parse_int(value: Any) -> Optional[int]:
    return int(value) if value not in (None, "") else None


def is_stale(timestamp: Optional[datetime], ttl: timedelta) -> bool:
    if timestamp is None:
        return True
    return datetime.now(timezone.utc) - timestamp >= ttl


@dataclass(frozen=True)
class TableSpec:
    model: Type[Base]
    field_map: Mapping[str, str]  # column_name -> FMP JSON key
    pk_columns: Sequence[str]
    ttl: timedelta
    freshness_column: str = "updated_at"
    order_by: Optional[str] = None
    periodic: bool = False  # filter by annual ("FY") vs quarterly ("Q%") period
    date_columns: FrozenSet[str] = field(default_factory=frozenset)
    timestamp_columns: FrozenSet[str] = field(default_factory=frozenset)
    epoch_columns: FrozenSet[str] = field(default_factory=frozenset)
    int_columns: FrozenSet[str] = field(default_factory=frozenset)
    stub_name_field: Optional[str] = None  # FMP key to use as a profile-stub company name hint


def _to_row(raw: Mapping[str, Any], spec: TableSpec) -> dict:
    row: dict = {"symbol": raw["symbol"].upper()}
    for column, api_key in spec.field_map.items():
        value = raw.get(api_key)
        if column in spec.date_columns:
            value = _parse_date(value)
        elif column in spec.timestamp_columns:
            value = _parse_timestamp(value)
        elif column in spec.epoch_columns:
            value = _parse_epoch(value)
        elif column in spec.int_columns:
            value = _parse_int(value)
        row[column] = value
    return row


def _to_api_dict(row: Base, spec: TableSpec) -> dict:
    result: dict = {"symbol": row.symbol}
    for column, api_key in spec.field_map.items():
        value = getattr(row, column)
        if column in spec.epoch_columns:
            value = int(value.timestamp()) if value is not None else None
        elif column in spec.timestamp_columns and value is not None:
            value = value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(value, (date, datetime)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        result[api_key] = value
    return result


def _period_filter(model: Type[Base], period: str):
    return model.period.like("Q%") if period == "quarter" else model.period == "FY"


# ---------------------------------------------------------------------------
# Table specs: one declarative entry per cached table
# ---------------------------------------------------------------------------

PROFILE_SPEC = TableSpec(
    model=Profile,
    ttl=PROFILE_TTL,
    pk_columns=("symbol",),
    date_columns=frozenset({"ipo_date"}),
    int_columns=frozenset({"full_time_employees"}),
    field_map={
        "company_name": "companyName",
        "currency": "currency",
        "cik": "cik",
        "isin": "isin",
        "cusip": "cusip",
        "exchange_full_name": "exchangeFullName",
        "sector": "sector",
        "industry": "industry",
        "website": "website",
        "description": "description",
        "ceo": "ceo",
        "country": "country",
        "ipo_date": "ipoDate",
        "full_time_employees": "fullTimeEmployees",
        "phone": "phone",
        "address": "address",
        "city": "city",
        "state": "state",
        "zip": "zip",
        "image": "image",
        "last_dividend": "lastDividend",
        "beta": "beta",
        "is_etf": "isEtf",
        "is_fund": "isFund",
        "is_adr": "isAdr",
        "is_actively_trading": "isActivelyTrading",
    },
)

QUOTE_SPEC = TableSpec(
    model=Quote,
    ttl=QUOTE_TTL,
    pk_columns=("symbol",),
    epoch_columns=frozenset({"quote_timestamp"}),
    int_columns=frozenset({"volume", "average_volume", "market_cap"}),
    stub_name_field="name",
    field_map={
        "exchange": "exchange",
        "price": "price",
        "change": "change",
        "change_percentage": "changePercentage",
        "volume": "volume",
        "average_volume": "avgVolume",
        "day_low": "dayLow",
        "day_high": "dayHigh",
        "year_low": "yearLow",
        "year_high": "yearHigh",
        "market_cap": "marketCap",
        "price_avg_50": "priceAvg50",
        "price_avg_200": "priceAvg200",
        "open": "open",
        "previous_close": "previousClose",
        "quote_timestamp": "timestamp",
    },
)

_FILING_DATE_COLUMNS = frozenset({"date", "filing_date"})
_ACCEPTED_DATE_COLUMNS = frozenset({"accepted_date"})

INCOME_STATEMENT_SPEC = TableSpec(
    model=IncomeStatement,
    ttl=DAILY_TTL,
    freshness_column="fetched_at",
    pk_columns=("symbol", "fiscal_year", "period"),
    order_by="fiscal_year",
    periodic=True,
    date_columns=_FILING_DATE_COLUMNS,
    timestamp_columns=_ACCEPTED_DATE_COLUMNS,
    field_map={
        "date": "date",
        "reported_currency": "reportedCurrency",
        "cik": "cik",
        "filing_date": "filingDate",
        "accepted_date": "acceptedDate",
        "fiscal_year": "fiscalYear",
        "period": "period",
        "revenue": "revenue",
        "cost_of_revenue": "costOfRevenue",
        "gross_profit": "grossProfit",
        "research_and_development_expenses": "researchAndDevelopmentExpenses",
        "general_and_administrative_expenses": "generalAndAdministrativeExpenses",
        "selling_and_marketing_expenses": "sellingAndMarketingExpenses",
        "selling_general_and_admin_expenses": "sellingGeneralAndAdministrativeExpenses",
        "other_expenses": "otherExpenses",
        "operating_expenses": "operatingExpenses",
        "cost_and_expenses": "costAndExpenses",
        "net_interest_income": "netInterestIncome",
        "interest_income": "interestIncome",
        "interest_expense": "interestExpense",
        "depreciation_and_amortization": "depreciationAndAmortization",
        "ebitda": "ebitda",
        "ebit": "ebit",
        "non_operating_income_excl_interest": "nonOperatingIncomeExcludingInterest",
        "operating_income": "operatingIncome",
        "total_other_income_expenses_net": "totalOtherIncomeExpensesNet",
        "income_before_tax": "incomeBeforeTax",
        "income_tax_expense": "incomeTaxExpense",
        "net_income_from_continuing_ops": "netIncomeFromContinuingOperations",
        "net_income_from_discontinued_ops": "netIncomeFromDiscontinuedOperations",
        "other_adjustments_to_net_income": "otherAdjustmentsToNetIncome",
        "net_income": "netIncome",
        "net_income_deductions": "netIncomeDeductions",
        "bottom_line_net_income": "bottomLineNetIncome",
        "eps": "eps",
        "eps_diluted": "epsDiluted",
        "weighted_avg_shs_out": "weightedAverageShsOut",
        "weighted_avg_shs_out_dil": "weightedAverageShsOutDil",
    },
)

BALANCE_SHEET_SPEC = TableSpec(
    model=BalanceSheet,
    ttl=DAILY_TTL,
    freshness_column="fetched_at",
    pk_columns=("symbol", "fiscal_year", "period"),
    order_by="fiscal_year",
    periodic=True,
    date_columns=_FILING_DATE_COLUMNS,
    timestamp_columns=_ACCEPTED_DATE_COLUMNS,
    field_map={
        "date": "date",
        "reported_currency": "reportedCurrency",
        "cik": "cik",
        "filing_date": "filingDate",
        "accepted_date": "acceptedDate",
        "fiscal_year": "fiscalYear",
        "period": "period",
        "cash_and_cash_equivalents": "cashAndCashEquivalents",
        "short_term_investments": "shortTermInvestments",
        "cash_and_short_term_investments": "cashAndShortTermInvestments",
        "net_receivables": "netReceivables",
        "accounts_receivables": "accountsReceivables",
        "other_receivables": "otherReceivables",
        "inventory": "inventory",
        "prepaids": "prepaids",
        "other_current_assets": "otherCurrentAssets",
        "total_current_assets": "totalCurrentAssets",
        "property_plant_equipment_net": "propertyPlantEquipmentNet",
        "goodwill": "goodwill",
        "intangible_assets": "intangibleAssets",
        "goodwill_and_intangible_assets": "goodwillAndIntangibleAssets",
        "long_term_investments": "longTermInvestments",
        "tax_assets": "taxAssets",
        "other_non_current_assets": "otherNonCurrentAssets",
        "total_non_current_assets": "totalNonCurrentAssets",
        "other_assets": "otherAssets",
        "total_assets": "totalAssets",
        "total_payables": "totalPayables",
        "account_payables": "accountPayables",
        "other_payables": "otherPayables",
        "accrued_expenses": "accruedExpenses",
        "short_term_debt": "shortTermDebt",
        "capital_lease_obligations_current": "capitalLeaseObligationsCurrent",
        "tax_payables": "taxPayables",
        "deferred_revenue": "deferredRevenue",
        "other_current_liabilities": "otherCurrentLiabilities",
        "total_current_liabilities": "totalCurrentLiabilities",
        "long_term_debt": "longTermDebt",
        "capital_lease_obligations_noncurrent": "capitalLeaseObligationsNonCurrent",
        "deferred_revenue_non_current": "deferredRevenueNonCurrent",
        "deferred_tax_liabilities_non_current": "deferredTaxLiabilitiesNonCurrent",
        "other_non_current_liabilities": "otherNonCurrentLiabilities",
        "total_non_current_liabilities": "totalNonCurrentLiabilities",
        "other_liabilities": "otherLiabilities",
        "capital_lease_obligations": "capitalLeaseObligations",
        "total_liabilities": "totalLiabilities",
        "treasury_stock": "treasuryStock",
        "preferred_stock": "preferredStock",
        "common_stock": "commonStock",
        "retained_earnings": "retainedEarnings",
        "additional_paid_in_capital": "additionalPaidInCapital",
        "accumulated_other_comprehensive_inc": "accumulatedOtherComprehensiveIncomeLoss",
        "other_total_stockholders_equity": "otherTotalStockholdersEquity",
        "total_stockholders_equity": "totalStockholdersEquity",
        "total_equity": "totalEquity",
        "minority_interest": "minorityInterest",
        "total_liabilities_and_equity": "totalLiabilitiesAndTotalEquity",
        "total_investments": "totalInvestments",
        "total_debt": "totalDebt",
        "net_debt": "netDebt",
    },
)

CASH_FLOW_SPEC = TableSpec(
    model=CashFlowStatement,
    ttl=DAILY_TTL,
    freshness_column="fetched_at",
    pk_columns=("symbol", "fiscal_year", "period"),
    order_by="fiscal_year",
    periodic=True,
    date_columns=_FILING_DATE_COLUMNS,
    timestamp_columns=_ACCEPTED_DATE_COLUMNS,
    field_map={
        "date": "date",
        "reported_currency": "reportedCurrency",
        "cik": "cik",
        "filing_date": "filingDate",
        "accepted_date": "acceptedDate",
        "fiscal_year": "fiscalYear",
        "period": "period",
        "net_income": "netIncome",
        "depreciation_and_amortization": "depreciationAndAmortization",
        "deferred_income_tax": "deferredIncomeTax",
        "stock_based_compensation": "stockBasedCompensation",
        "change_in_working_capital": "changeInWorkingCapital",
        "accounts_receivables": "accountsReceivables",
        "inventory": "inventory",
        "accounts_payables": "accountsPayables",
        "other_working_capital": "otherWorkingCapital",
        "other_non_cash_items": "otherNonCashItems",
        "net_cash_from_operating_activities": "netCashProvidedByOperatingActivities",
        "investments_in_ppe": "investmentsInPropertyPlantAndEquipment",
        "acquisitions_net": "acquisitionsNet",
        "purchases_of_investments": "purchasesOfInvestments",
        "sales_maturities_of_investments": "salesMaturitiesOfInvestments",
        "other_investing_activities": "otherInvestingActivities",
        "net_cash_from_investing_activities": "netCashProvidedByInvestingActivities",
        "net_debt_issuance": "netDebtIssuance",
        "long_term_net_debt_issuance": "longTermNetDebtIssuance",
        "short_term_net_debt_issuance": "shortTermNetDebtIssuance",
        "net_stock_issuance": "netStockIssuance",
        "net_common_stock_issuance": "netCommonStockIssuance",
        "common_stock_issuance": "commonStockIssuance",
        "common_stock_repurchased": "commonStockRepurchased",
        "net_preferred_stock_issuance": "netPreferredStockIssuance",
        "net_dividends_paid": "netDividendsPaid",
        "common_dividends_paid": "commonDividendsPaid",
        "preferred_dividends_paid": "preferredDividendsPaid",
        "other_financing_activities": "otherFinancingActivities",
        "net_cash_from_financing_activities": "netCashProvidedByFinancingActivities",
        "effect_of_forex_changes_on_cash": "effectOfForexChangesOnCash",
        "net_change_in_cash": "netChangeInCash",
        "cash_at_end_of_period": "cashAtEndOfPeriod",
        "cash_at_beginning_of_period": "cashAtBeginningOfPeriod",
        "operating_cash_flow": "operatingCashFlow",
        "capital_expenditure": "capitalExpenditure",
        "free_cash_flow": "freeCashFlow",
        "income_taxes_paid": "incomeTaxesPaid",
        "interest_paid": "interestPaid",
    },
)

_PERIODIC_DATE_COLUMN = frozenset({"date"})

KEY_METRICS_SPEC = TableSpec(
    model=KeyMetrics,
    ttl=DAILY_TTL,
    freshness_column="fetched_at",
    pk_columns=("symbol", "fiscal_year", "period"),
    order_by="fiscal_year",
    periodic=True,
    date_columns=_PERIODIC_DATE_COLUMN,
    field_map={
        "date": "date",
        "fiscal_year": "fiscalYear",
        "period": "period",
        "reported_currency": "reportedCurrency",
        "market_cap": "marketCap",
        "enterprise_value": "enterpriseValue",
        "ev_to_sales": "evToSales",
        "ev_to_operating_cash_flow": "evToOperatingCashFlow",
        "ev_to_free_cash_flow": "evToFreeCashFlow",
        "ev_to_ebitda": "evToEBITDA",
        "net_debt_to_ebitda": "netDebtToEBITDA",
        "current_ratio": "currentRatio",
        "income_quality": "incomeQuality",
        "graham_number": "grahamNumber",
        "graham_net_net": "grahamNetNet",
        "tax_burden": "taxBurden",
        "interest_burden": "interestBurden",
        "working_capital": "workingCapital",
        "invested_capital": "investedCapital",
        "return_on_assets": "returnOnAssets",
        "operating_return_on_assets": "operatingReturnOnAssets",
        "return_on_tangible_assets": "returnOnTangibleAssets",
        "return_on_equity": "returnOnEquity",
        "return_on_invested_capital": "returnOnInvestedCapital",
        "return_on_capital_employed": "returnOnCapitalEmployed",
        "earnings_yield": "earningsYield",
        "free_cash_flow_yield": "freeCashFlowYield",
        "capex_to_operating_cash_flow": "capexToOperatingCashFlow",
        "capex_to_depreciation": "capexToDepreciation",
        "capex_to_revenue": "capexToRevenue",
        "sga_to_revenue": "salesGeneralAndAdministrativeToRevenue",
        "rd_to_revenue": "researchAndDevelopementToRevenue",
        "stock_based_comp_to_revenue": "stockBasedCompensationToRevenue",
        "intangibles_to_total_assets": "intangiblesToTotalAssets",
        "average_receivables": "averageReceivables",
        "average_payables": "averagePayables",
        "average_inventory": "averageInventory",
        "days_of_sales_outstanding": "daysOfSalesOutstanding",
        "days_of_payables_outstanding": "daysOfPayablesOutstanding",
        "days_of_inventory_outstanding": "daysOfInventoryOutstanding",
        "operating_cycle": "operatingCycle",
        "cash_conversion_cycle": "cashConversionCycle",
        "free_cash_flow_to_equity": "freeCashFlowToEquity",
        "free_cash_flow_to_firm": "freeCashFlowToFirm",
        "tangible_asset_value": "tangibleAssetValue",
        "net_current_asset_value": "netCurrentAssetValue",
    },
)

RATIOS_SPEC = TableSpec(
    model=Ratios,
    ttl=DAILY_TTL,
    freshness_column="fetched_at",
    pk_columns=("symbol", "fiscal_year", "period"),
    order_by="fiscal_year",
    periodic=True,
    date_columns=_PERIODIC_DATE_COLUMN,
    field_map={
        "date": "date",
        "fiscal_year": "fiscalYear",
        "period": "period",
        "reported_currency": "reportedCurrency",
        "gross_profit_margin": "grossProfitMargin",
        "ebit_margin": "ebitMargin",
        "ebitda_margin": "ebitdaMargin",
        "operating_profit_margin": "operatingProfitMargin",
        "pretax_profit_margin": "pretaxProfitMargin",
        "continuous_operations_profit_margin": "continuousOperationsProfitMargin",
        "net_profit_margin": "netProfitMargin",
        "bottom_line_profit_margin": "bottomLineProfitMargin",
        "receivables_turnover": "receivablesTurnover",
        "payables_turnover": "payablesTurnover",
        "inventory_turnover": "inventoryTurnover",
        "fixed_asset_turnover": "fixedAssetTurnover",
        "asset_turnover": "assetTurnover",
        "current_ratio": "currentRatio",
        "quick_ratio": "quickRatio",
        "solvency_ratio": "solvencyRatio",
        "cash_ratio": "cashRatio",
        "price_to_earnings_ratio": "priceToEarningsRatio",
        "price_to_earnings_growth_ratio": "priceToEarningsGrowthRatio",
        "forward_price_to_earnings_growth_ratio": "forwardPriceToEarningsGrowthRatio",
        "price_to_book_ratio": "priceToBookRatio",
        "price_to_sales_ratio": "priceToSalesRatio",
        "price_to_free_cash_flow_ratio": "priceToFreeCashFlowRatio",
        "price_to_operating_cash_flow_ratio": "priceToOperatingCashFlowRatio",
        "debt_to_assets_ratio": "debtToAssetsRatio",
        "debt_to_equity_ratio": "debtToEquityRatio",
        "debt_to_capital_ratio": "debtToCapitalRatio",
        "long_term_debt_to_capital_ratio": "longTermDebtToCapitalRatio",
        "financial_leverage_ratio": "financialLeverageRatio",
        "working_capital_turnover_ratio": "workingCapitalTurnoverRatio",
        "operating_cash_flow_ratio": "operatingCashFlowRatio",
        "operating_cash_flow_sales_ratio": "operatingCashFlowSalesRatio",
        "free_cash_flow_operating_cf_ratio": "freeCashFlowOperatingCashFlowRatio",
        "debt_service_coverage_ratio": "debtServiceCoverageRatio",
        "interest_coverage_ratio": "interestCoverageRatio",
        "short_term_operating_cf_coverage_ratio": "shortTermOperatingCashFlowCoverageRatio",
        "operating_cash_flow_coverage_ratio": "operatingCashFlowCoverageRatio",
        "capital_expenditure_coverage_ratio": "capitalExpenditureCoverageRatio",
        "dividend_paid_and_capex_coverage_ratio": "dividendPaidAndCapexCoverageRatio",
        "dividend_payout_ratio": "dividendPayoutRatio",
        "dividend_yield": "dividendYield",
        "dividend_yield_percentage": "dividendYieldPercentage",
        "revenue_per_share": "revenuePerShare",
        "net_income_per_share": "netIncomePerShare",
        "interest_debt_per_share": "interestDebtPerShare",
        "cash_per_share": "cashPerShare",
        "book_value_per_share": "bookValuePerShare",
        "tangible_book_value_per_share": "tangibleBookValuePerShare",
        "shareholders_equity_per_share": "shareholdersEquityPerShare",
        "operating_cash_flow_per_share": "operatingCashFlowPerShare",
        "capex_per_share": "capexPerShare",
        "free_cash_flow_per_share": "freeCashFlowPerShare",
        "net_income_per_ebt": "netIncomePerEBT",
        "ebt_per_ebit": "ebtPerEbit",
        "price_to_fair_value": "priceToFairValue",
        "debt_to_market_cap": "debtToMarketCap",
        "effective_tax_rate": "effectiveTaxRate",
        "enterprise_value_multiple": "enterpriseValueMultiple",
        "dividend_per_share": "dividendPerShare",
    },
)

FINANCIAL_GROWTH_SPEC = TableSpec(
    model=FinancialGrowth,
    ttl=DAILY_TTL,
    freshness_column="fetched_at",
    pk_columns=("symbol", "fiscal_year", "period"),
    order_by="fiscal_year",
    periodic=True,
    date_columns=_PERIODIC_DATE_COLUMN,
    field_map={
        "date": "date",
        "fiscal_year": "fiscalYear",
        "period": "period",
        "reported_currency": "reportedCurrency",
        "revenue_growth": "revenueGrowth",
        "gross_profit_growth": "grossProfitGrowth",
        "ebit_growth": "ebitgrowth",
        "operating_income_growth": "operatingIncomeGrowth",
        "net_income_growth": "netIncomeGrowth",
        "eps_growth": "epsgrowth",
        "eps_diluted_growth": "epsdilutedGrowth",
        "weighted_avg_shares_growth": "weightedAverageSharesGrowth",
        "weighted_avg_shares_diluted_growth": "weightedAverageSharesDilutedGrowth",
        "dividends_per_share_growth": "dividendsPerShareGrowth",
        "operating_cash_flow_growth": "operatingCashFlowGrowth",
        "receivables_growth": "receivablesGrowth",
        "inventory_growth": "inventoryGrowth",
        "asset_growth": "assetGrowth",
        "book_value_per_share_growth": "bookValueperShareGrowth",
        "debt_growth": "debtGrowth",
        "rd_expense_growth": "rdexpenseGrowth",
        "sga_expenses_growth": "sgaexpensesGrowth",
        "free_cash_flow_growth": "freeCashFlowGrowth",
        "ten_y_revenue_growth_per_share": "tenYRevenueGrowthPerShare",
        "five_y_revenue_growth_per_share": "fiveYRevenueGrowthPerShare",
        "three_y_revenue_growth_per_share": "threeYRevenueGrowthPerShare",
        "ten_y_operating_cf_growth_per_share": "tenYOperatingCFGrowthPerShare",
        "five_y_operating_cf_growth_per_share": "fiveYOperatingCFGrowthPerShare",
        "three_y_operating_cf_growth_per_share": "threeYOperatingCFGrowthPerShare",
        "ten_y_net_income_growth_per_share": "tenYNetIncomeGrowthPerShare",
        "five_y_net_income_growth_per_share": "fiveYNetIncomeGrowthPerShare",
        "three_y_net_income_growth_per_share": "threeYNetIncomeGrowthPerShare",
        "ten_y_shareholders_equity_growth_per_share": "tenYShareholdersEquityGrowthPerShare",
        "five_y_shareholders_equity_growth_per_share": "fiveYShareholdersEquityGrowthPerShare",
        "three_y_shareholders_equity_growth_per_share": "threeYShareholdersEquityGrowthPerShare",
        "ten_y_dividend_per_share_growth_per_share": "tenYDividendperShareGrowthPerShare",
        "five_y_dividend_per_share_growth_per_share": "fiveYDividendperShareGrowthPerShare",
        "three_y_dividend_per_share_growth_per_share": "threeYDividendperShareGrowthPerShare",
        "ebitda_growth": "ebitdaGrowth",
        "growth_capital_expenditure": "growthCapitalExpenditure",
        "ten_y_bottom_line_net_income_growth_per_share": "tenYBottomLineNetIncomeGrowthPerShare",
        "five_y_bottom_line_net_income_growth_per_share": "fiveYBottomLineNetIncomeGrowthPerShare",
        "three_y_bottom_line_net_income_growth_per_share": "threeYBottomLineNetIncomeGrowthPerShare",
    },
)

ENTERPRISE_VALUE_SPEC = TableSpec(
    model=EnterpriseValue,
    ttl=DAILY_TTL,
    freshness_column="fetched_at",
    pk_columns=("symbol", "date"),
    order_by="date",
    date_columns=_PERIODIC_DATE_COLUMN,
    field_map={
        "date": "date",
        "stock_price": "stockPrice",
        "number_of_shares": "numberOfShares",
        "market_capitalization": "marketCapitalization",
        "minus_cash_and_equivalents": "minusCashAndCashEquivalents",
        "add_total_debt": "addTotalDebt",
        "enterprise_value": "enterpriseValue",
    },
)


# ---------------------------------------------------------------------------
# Generic cache engine: every table above is read/written through this
# ---------------------------------------------------------------------------

class MarketDataService:
    async def ensure_profile_stub(self, symbol: str, company_name: Optional[str] = None) -> None:
        stmt = insert(Profile).values(symbol=symbol.upper(), company_name=company_name)
        stmt = stmt.on_conflict_do_nothing(index_elements=[Profile.symbol])

        async with get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def _get_rows(self, spec: TableSpec, symbol: str, limit: int, period: str) -> list:
        query = select(spec.model).where(spec.model.symbol == symbol)
        if spec.periodic:
            query = query.where(_period_filter(spec.model, period))
        if spec.order_by:
            query = query.order_by(getattr(spec.model, spec.order_by).desc())
        query = query.limit(limit)

        async with get_session() as session:
            result = await session.execute(query)
            return list(result.scalars().all())

    async def _upsert_many(self, spec: TableSpec, payload: Sequence[Mapping[str, Any]]) -> None:
        if not payload:
            return

        if spec.model is not Profile:
            stub_names: dict = {}
            for item in payload:
                symbol = item["symbol"].upper()
                if symbol not in stub_names:
                    stub_names[symbol] = item.get(spec.stub_name_field) if spec.stub_name_field else None
            for symbol, name in stub_names.items():
                await self.ensure_profile_stub(symbol, name)

        rows = [_to_row(item, spec) for item in payload]
        stmt = insert(spec.model).values(rows)
        update_columns = {
            column.name: stmt.excluded[column.name]
            for column in spec.model.__table__.columns
            if column.name not in spec.pk_columns and column.name != spec.freshness_column
        }
        update_columns[spec.freshness_column] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=spec.pk_columns, set_=update_columns)

        async with get_session() as session:
            await session.execute(stmt)
            await session.commit()

    async def get_or_fetch(
        self,
        spec: TableSpec,
        symbol: str,
        limit: int,
        fetch: Callable[[], Awaitable[list]],
        period: str = "annual",
    ) -> list:
        symbol = symbol.upper()
        rows = await self._get_rows(spec, symbol, limit, period)
        if len(rows) >= limit and not any(is_stale(getattr(r, spec.freshness_column), spec.ttl) for r in rows):
            return [_to_api_dict(r, spec) for r in rows]

        payload = await fetch()
        await self._upsert_many(spec, payload)

        rows = await self._get_rows(spec, symbol, limit, period)
        return [_to_api_dict(r, spec) for r in rows] if rows else list(payload)


# ---------------------------------------------------------------------------
# Route-facing orchestration: composes FMP + the cache engine per table
# ---------------------------------------------------------------------------

class StockDataService:
    def __init__(self, fmp_service, market_data_service: Optional[MarketDataService] = None):
        self.fmp_service = fmp_service
        self.market_data_service = market_data_service or MarketDataService()

    async def _get_profile(self, symbol: str) -> dict:
        rows = await self.market_data_service.get_or_fetch(
            PROFILE_SPEC, symbol, 1, lambda: self.fmp_service.get_company_profile(symbol),
        )
        return rows[0] if rows else {}

    async def _get_quote(self, symbol: str) -> dict:
        rows = await self.market_data_service.get_or_fetch(
            QUOTE_SPEC, symbol, 1, lambda: self.fmp_service.get_quote(symbol),
        )
        return rows[0] if rows else {}

    async def get_profile_with_quote(self, symbol: str) -> dict:
        profile, quote = await asyncio.gather(self._get_profile(symbol), self._get_quote(symbol))
        return {**profile, **quote}

    async def get_quote_only(self, symbol: str) -> dict:
        return await self._get_quote(symbol)

    async def get_company_dataset(self, symbol: str, period: str = "annual", limit: int = 5) -> dict:
        symbol = symbol.upper()
        mds = self.market_data_service
        fmp = self.fmp_service

        (
            profile,
            quote,
            income_statements,
            balance_sheets,
            cash_flow_statements,
            key_metrics,
            ratios,
            financial_growth,
            enterprise_values,
        ) = await asyncio.gather(
            mds.get_or_fetch(PROFILE_SPEC, symbol, 1, lambda: fmp.get_company_profile(symbol)),
            mds.get_or_fetch(QUOTE_SPEC, symbol, 1, lambda: fmp.get_quote(symbol)),
            mds.get_or_fetch(
                INCOME_STATEMENT_SPEC, symbol, limit,
                lambda: fmp.get_income_statements(symbol, period=period, limit=limit), period,
            ),
            mds.get_or_fetch(
                BALANCE_SHEET_SPEC, symbol, limit,
                lambda: fmp.get_balance_sheets(symbol, period=period, limit=limit), period,
            ),
            mds.get_or_fetch(
                CASH_FLOW_SPEC, symbol, limit,
                lambda: fmp.get_cash_flow_statements(symbol, period=period, limit=limit), period,
            ),
            mds.get_or_fetch(
                KEY_METRICS_SPEC, symbol, limit,
                lambda: fmp.get_key_metrics(symbol, period=period, limit=limit), period,
            ),
            mds.get_or_fetch(
                RATIOS_SPEC, symbol, limit,
                lambda: fmp.get_ratios(symbol, period=period, limit=limit), period,
            ),
            mds.get_or_fetch(
                FINANCIAL_GROWTH_SPEC, symbol, limit,
                lambda: fmp.get_financial_growth(symbol, period=period, limit=limit), period,
            ),
            mds.get_or_fetch(
                ENTERPRISE_VALUE_SPEC, symbol, limit,
                lambda: fmp.get_enterprise_values(symbol, period=period, limit=limit), period,
            ),
        )

        return {
            "symbol": symbol,
            "profile": profile,
            "quote": quote,
            "income_statements": income_statements,
            "balance_sheets": balance_sheets,
            "cash_flow_statements": cash_flow_statements,
            "key_metrics": key_metrics,
            "ratios": ratios,
            "financial_growth": financial_growth,
            "enterprise_values": enterprise_values,
        }
