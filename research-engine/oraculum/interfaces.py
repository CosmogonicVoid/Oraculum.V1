"""Pure integration ports. Qwen/Kimi implement these in their own modules.

These Protocols are type contracts, not executable placeholder implementations.
The core CLI is fully runnable without either extension.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, Sequence

from .contracts import ResearchBundle


@dataclass(frozen=True)
class PriceBar:
    instrument_id: str
    session: date
    open_at: datetime
    close_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover_inr: Decimal
    source_id: str
    adjustment_version: str


class ResearchProvider(Protocol):
    def load_bundle(self, *, as_of: datetime, last_session: date) -> ResearchBundle: ...


class PriceFeatureBuilder(Protocol):
    def build_metrics(self, bars: Sequence[PriceBar], *, as_of: datetime) -> dict: ...


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    instrument_id: str
    side: Literal["buy", "sell"]
    quantity: int
    submitted_at: datetime
    signal_run_id: str


@dataclass(frozen=True)
class PaperFill:
    order_id: str
    instrument_id: str
    side: Literal["buy", "sell"]
    quantity: int
    price_inr: Decimal
    fee_inr: Decimal
    filled_at: datetime


@dataclass(frozen=True)
class Position:
    instrument_id: str
    quantity: int
    average_cost_inr: Decimal


@dataclass(frozen=True)
class PortfolioState:
    cash_inr: Decimal
    positions: tuple[Position, ...]
    processed_order_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrderRejection:
    order_id: str
    reason: str


@dataclass(frozen=True)
class SessionResult:
    state: PortfolioState
    fills: tuple[PaperFill, ...]
    rejections: tuple[OrderRejection, ...]


class PaperSimulator(Protocol):
    def execute_session(
        self, state: PortfolioState, orders: Sequence[PaperOrder],
        bars: Sequence[PriceBar], *, fee_bps: Decimal, slippage_bps: Decimal,
    ) -> SessionResult: ...
