"""Estructuras de datos compartidas por estrategia, ejecución y API."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

Direction = Literal["long", "short"]


@dataclass(slots=True)
class Bar:
    ts: int  # epoch segundos UTC, inicio de la vela
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "t": self.ts,
            "o": round(self.open, 4),
            "h": round(self.high, 4),
            "l": round(self.low, 4),
            "c": round(self.close, 4),
            "v": round(self.volume, 2),
        }


@dataclass(slots=True)
class Pivot:
    index: int
    ts: int
    price: float
    kind: Literal["high", "low"]
    confirmed_index: int


@dataclass(slots=True)
class Divergence:
    bias: Literal["bullish", "bearish"]
    level: float
    primary_prev: float
    primary_last: float
    reference_prev: float
    reference_last: float
    confirm_ts: int
    expires_ts: int
    pivot_ts: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Signal:
    id: str
    ts: int
    direction: Direction
    entry_price: float
    stop: float
    target: float
    qty: int
    risk_amount: float
    signal_type: str
    entry_reason: str
    reference_level: float
    breakout_level: float
    smt_bias: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Order:
    id: str
    symbol: str
    side: Literal["buy", "sell"]
    qty: int
    order_type: Literal["market", "limit", "stop"]
    limit_price: float | None
    role: Literal["entry", "stop", "target"]
    status: Literal["pending", "filled", "cancelled", "rejected"] = "pending"
    created_ts: int = field(default_factory=lambda: int(time.time()))
    filled_ts: int | None = None
    filled_price: float | None = None
    reason: str = ""

    @staticmethod
    def new(**kw: Any) -> "Order":
        kw.setdefault("id", uuid.uuid4().hex[:12])
        return Order(**kw)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Position:
    id: str
    symbol: str
    direction: Direction
    qty: int
    entry_price: float
    entry_ts: int
    stop: float
    target: float
    initial_stop: float
    risk_amount: float
    signal_id: str
    signal_type: str
    entry_reason: str
    mode: str = "paper"
    partial_exit_qty: int = 0
    # Excursiones y drawdown mientras la posición estuvo abierta. Los importes
    # son USD y las excursiones en R usan el stop inicial como denominador.
    mfe_r: float = 0.0
    mae_r: float = 0.0
    mfe_usd: float = 0.0
    mae_usd: float = 0.0
    open_drawdown: float = 0.0
    peak_unrealized: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def side(self) -> str:
        return "long" if self.direction == "long" else "short"

    def unrealized(self, price: float, point_value: float) -> float:
        diff = price - self.entry_price if self.direction == "long" else self.entry_price - price
        return round(diff * point_value * self.qty, 2)

    def r_multiple(self, price: float) -> float:
        risk = abs(self.entry_price - self.initial_stop)
        if risk <= 0:
            return 0.0
        diff = price - self.entry_price if self.direction == "long" else self.entry_price - price
        return round(diff / risk, 2)

    def as_dict(self, price: float | None = None, point_value: float = 2.0) -> dict[str, Any]:
        data = asdict(self)
        data["side"] = self.side
        if price is not None:
            data["current_price"] = round(price, 4)
            data["unrealized"] = self.unrealized(price, point_value)
            data["r_multiple"] = self.r_multiple(price)
        return data


@dataclass(slots=True)
class TradeRecord:
    id: str
    symbol: str
    direction: Direction
    qty: int
    entry_ts: int
    entry_price: float
    exit_ts: int
    exit_price: float
    stop: float
    target: float
    pnl: float
    gross_pnl: float
    fees: float
    r_multiple: float
    risk_amount: float
    signal_type: str
    entry_reason: str
    exit_reason: str
    duration_sec: int
    mode: str = "paper"
    mfe_r: float = 0.0
    mae_r: float = 0.0
    mfe_usd: float = 0.0
    mae_usd: float = 0.0
    open_drawdown: float = 0.0
    # Contrato y vencimiento de la serie usada. Cadena vacía cuando el feed no
    # declara contratos (replay sintético o CSV sin columna `contract`).
    contract: str = ""
    expiry: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
