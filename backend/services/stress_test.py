"""Deterministic scenario analysis (stress testing).

A scenario is a set of instantaneous factor shocks:

* ``us_equity_shock_pct``   – applied to US-listed holdings,
* ``bist_equity_shock_pct`` – applied to Borsa Istanbul (``.IS``) holdings,
* ``usd_try_shock_pct``     – % change in USD/TRY (TRY per 1 USD).

A TRY-denominated holding is hit twice: by the equity shock in lira and by the
currency translation back to USD, so its USD value is multiplied by
``(1 + equity) / (1 + fx)``. A +25% USD/TRY move alone therefore costs a
lira asset 1 − 1/1.25 = 20% in USD terms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

TRY_CURRENCY = "TRY"


class Scenario(StrEnum):
    COVID_CRASH = "covid_crash"
    TECH_SELLOFF = "tech_selloff"
    USD_TRY_SPIKE = "usd_try_spike"
    RATE_HIKE = "rate_hike"


class MarketSegment(StrEnum):
    US_EQUITY = "US_EQUITY"
    BIST_EQUITY = "BIST_EQUITY"


@dataclass(frozen=True)
class ShockSet:
    us_equity_shock_pct: float = 0.0
    bist_equity_shock_pct: float = 0.0
    usd_try_shock_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.us_equity_shock_pct < -100 or self.bist_equity_shock_pct < -100:
            raise ValueError("an equity shock cannot be below -100%")
        if self.usd_try_shock_pct <= -100:
            raise ValueError("the USD/TRY shock must be above -100%")


@dataclass(frozen=True)
class ScenarioDefinition:
    key: Scenario
    label: str
    description: str
    shocks: ShockSet


# Hypothetical shocks loosely calibrated to past episodes; illustrative, not forecasts.
PRESET_SCENARIOS: dict[Scenario, ScenarioDefinition] = {
    Scenario.COVID_CRASH: ScenarioDefinition(
        Scenario.COVID_CRASH,
        "COVID-19 Crash",
        "Feb–Mar 2020: S&P 500 fell ~34% peak-to-trough, BIST 100 ~33%, USD/TRY rose ~12%.",
        ShockSet(us_equity_shock_pct=-34, bist_equity_shock_pct=-33, usd_try_shock_pct=12),
    ),
    Scenario.TECH_SELLOFF: ScenarioDefinition(
        Scenario.TECH_SELLOFF,
        "Tech Selloff",
        "2022-style growth de-rating: US equities -25%, mild spill-over to BIST and the lira.",
        ShockSet(us_equity_shock_pct=-25, bist_equity_shock_pct=-10, usd_try_shock_pct=5),
    ),
    Scenario.USD_TRY_SPIKE: ScenarioDefinition(
        Scenario.USD_TRY_SPIKE,
        "Lira Crisis",
        "Aug 2018-style currency shock: USD/TRY +40%, BIST 100 -10% in lira, US equities flat.",
        ShockSet(us_equity_shock_pct=0, bist_equity_shock_pct=-10, usd_try_shock_pct=40),
    ),
    Scenario.RATE_HIKE: ScenarioDefinition(
        Scenario.RATE_HIKE,
        "Aggressive Fed Hike",
        "Surprise 100bp tightening: US equities -12%, EM equities -8%, stronger dollar (+8% USD/TRY).",
        ShockSet(us_equity_shock_pct=-12, bist_equity_shock_pct=-8, usd_try_shock_pct=8),
    ),
}


def segment_for_symbol(symbol: str) -> MarketSegment:
    """Borsa Istanbul listings carry the ``.IS`` suffix; everything else is treated as US."""
    return MarketSegment.BIST_EQUITY if symbol.strip().upper().endswith(".IS") else MarketSegment.US_EQUITY


@dataclass(frozen=True)
class Holding:
    symbol: str
    value_usd: float
    currency: str | None


@dataclass(frozen=True)
class HoldingImpact:
    symbol: str
    segment: MarketSegment
    currency: str | None
    value_before_usd: float
    value_after_usd: float
    pnl_usd: float
    pnl_pct: float
    equity_shock_pct: float
    fx_shock_pct: float


@dataclass(frozen=True)
class StressTestResult:
    impacts: list[HoldingImpact]
    total_before_usd: float
    total_after_usd: float
    total_pnl_usd: float
    total_pnl_pct: float | None
    worst_hit_symbol: str | None


def _value_multiplier(equity_shock_pct: float, fx_shock_pct: float) -> float:
    """USD value multiplier: local equity move, then translation at the shocked FX rate."""
    return (1 + equity_shock_pct / 100) / (1 + fx_shock_pct / 100)


def shock_holding(holding: Holding, shocks: ShockSet) -> HoldingImpact:
    """Apply the equity shock for the holding's market and, for lira assets, the FX shock."""
    segment = segment_for_symbol(holding.symbol)
    equity = shocks.bist_equity_shock_pct if segment is MarketSegment.BIST_EQUITY else shocks.us_equity_shock_pct
    is_try = (holding.currency or "").upper() == TRY_CURRENCY
    fx = shocks.usd_try_shock_pct if is_try else 0.0

    multiplier = _value_multiplier(equity, fx)
    after = holding.value_usd * multiplier
    pnl = after - holding.value_usd
    return HoldingImpact(
        symbol=holding.symbol,
        segment=segment,
        currency=holding.currency,
        value_before_usd=round(holding.value_usd, 2),
        value_after_usd=round(after, 2),
        pnl_usd=round(pnl, 2),
        pnl_pct=round((multiplier - 1) * 100, 2),
        equity_shock_pct=equity,
        fx_shock_pct=fx,
    )


def run_stress_test(holdings: Sequence[Holding], shocks: ShockSet) -> StressTestResult:
    """Revalue every holding under the shocks and aggregate the USD impact."""
    impacts = [shock_holding(h, shocks) for h in holdings]
    before = sum(h.value_usd for h in holdings)
    # Totals use unrounded per-holding values and are rounded once at the end.
    after = sum(
        h.value_usd * _value_multiplier(i.equity_shock_pct, i.fx_shock_pct)
        for h, i in zip(holdings, impacts, strict=True)
    )
    pnl = after - before
    losers = [i for i in impacts if i.pnl_usd < 0]
    worst = min(losers, key=lambda i: i.pnl_usd).symbol if losers else None
    return StressTestResult(
        impacts=impacts,
        total_before_usd=round(before, 2),
        total_after_usd=round(after, 2),
        total_pnl_usd=round(pnl, 2),
        total_pnl_pct=round(pnl / before * 100, 2) if before > 0 else None,
        worst_hit_symbol=worst,
    )
