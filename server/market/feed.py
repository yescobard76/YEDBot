"""Adaptadores de datos de mercado.

El motor solo conoce :class:`MarketFeed`. Cambiar de proveedor consiste en
implementar ``next_tick`` y ``describe``; ni la estrategia ni la UI cambian.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ..config import BASE_DIR, Settings
from ..models import Bar
from ..timeutil import et_date, et_minutes, next_weekday
from .csv_data import REQUIRED_SYMBOLS, CsvDataset
from .synthetic import build_session


@dataclass
class Tick:
    ts: int
    bars: dict[str, Bar]


class MarketFeed:
    kind = "abstract"
    label = "Sin proveedor"
    quality = "unknown"

    async def start(self) -> None:  # pragma: no cover - interfaz
        return None

    async def next_tick(self) -> Tick | None:  # pragma: no cover - interfaz
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - interfaz
        return None

    def rewind(self) -> None:
        """Vuelve al inicio del replay sin recargar el dataset."""
        return None

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "quality": self.quality,
            "connected": False,
            "detail": "",
            "simulated": self.quality == "simulated",
            "source": None,
            "bars": None,
            "first_ts": None,
            "last_ts": None,
            "aligned": None,
        }


def parse_start_date(raw: str) -> date | None:
    """Convierte ``YYYY-MM-DD`` en fecha; vacío significa sin fecha de inicio."""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"start_date inválida ({value!r}); usa YYYY-MM-DD") from None


class SimulatedFeed(MarketFeed):
    """Replay determinista de sesiones sintéticas, claramente etiquetado."""

    kind = "simulated"
    label = "REPLAY SIMULADO"
    quality = "simulated"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.start_date = parse_start_date(settings.feed.start_date)
        self.speed = settings.feed.replay_speed
        self.loop = settings.feed.loop_sessions
        self.latency = settings.feed.latency_ms / 1000
        self.day: date | None = None
        self.bars: dict[str, list[Bar]] = {}
        self.index = 0
        self.finished = False
        self._started = False

    async def start(self) -> None:
        self._started = True

    def rewind(self) -> None:
        self.day = None
        self.bars = {}
        self.index = 0
        self.finished = False
        self._started = False

    def _load_day(self, day: date) -> None:
        self.day = day
        self.bars = build_session(day, self.settings)
        self.index = 0
        # El replay arranca a las 09:00 ET para no perder tiempo en el pre-market.
        first = self.bars["NQ"]
        start_ts = next((b.ts for b in first if et_minutes(b.ts) >= 9 * 60), first[0].ts)
        self.index = next(i for i, b in enumerate(first) if b.ts >= start_ts)

    async def next_tick(self) -> Tick | None:
        if not self._started:
            await self.start()
        if self.day is None:
            start_day = self.start_date or et_date(int(time.time()))
            while start_day.weekday() >= 5:
                start_day = next_weekday(start_day)
            self._load_day(start_day)
        if self.index >= len(self.bars["NQ"]):
            if not self.loop:
                self.finished = True
                return None
            self._load_day(next_weekday(self.day))
        delay = 1.0 / self.speed + self.latency
        await asyncio.sleep(delay)
        ts = self.bars["NQ"][self.index].ts
        tick = Tick(ts=ts, bars={sym: bars[self.index] for sym, bars in self.bars.items()})
        self.index += 1
        return tick

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "quality": self.quality,
            "connected": True,
            "detail": "Datos sintéticos de replay; no son cotizaciones reales del mercado.",
            "session": self.day.isoformat() if self.day else None,
            "simulated": True,
            "source": "generador sintético",
            "bars": None,
            "first_ts": None,
            "last_ts": None,
            "aligned": None,
        }


class CSVFeed(MarketFeed):
    """Replay de una pasada de velas históricas reales, validadas y sincronizadas."""

    kind = "csv"
    label = "CSV HISTÓRICO REAL"
    quality = "historical"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.path = Path(settings.feed.csv_path).expanduser()
        if not self.path.is_absolute():
            self.path = BASE_DIR / self.path
        # Se valida la fecha antes de leer el CSV para no cargar un archivo
        # grande cuando el error está en la configuración.
        self.start_date = parse_start_date(settings.feed.start_date)
        self.dataset = CsvDataset.load(
            self.path,
            REQUIRED_SYMBOLS,
            series_mode=settings.feed.series_mode,
            exclude_roll_sessions=settings.feed.exclude_roll_sessions,
        )
        self.report = self.dataset.report
        self.manifest = self.dataset.manifest
        self.index = self._first_index_for(self.start_date)
        self.speed = settings.feed.replay_speed

    def _first_index_for(self, start: date | None) -> int:
        """Primera vela de la primera sesión en/después de ``start``.

        El CSV puede contener varias sesiones; el replay debe empezar en la
        fecha configurada, no en la primera vela del archivo.
        """
        if start is None:
            return 0
        for index, tick in enumerate(self.dataset.bars):
            if et_date(tick["NQ"].ts) >= start:
                return index
        last = et_date(self.dataset.bars[-1]["NQ"].ts).isoformat()
        raise ValueError(
            f"start_date {start.isoformat()} es posterior al último dato del CSV ({last})"
        )

    def rewind(self) -> None:
        self.index = self._first_index_for(self.start_date)

    async def next_tick(self) -> Tick | None:
        # Pasada única: repetir las mismas sesiones reabriría señales ya
        # evaluadas y mezclaría los contadores de riesgo del replay.
        if self.index >= len(self.dataset):
            return None
        await asyncio.sleep(1.0 / self.speed)
        bars = self.dataset.bars[self.index]
        self.index += 1
        return Tick(ts=bars["NQ"].ts, bars=bars)

    def describe(self) -> dict[str, Any]:
        manifest = self.manifest
        contracts = manifest.get("contracts") or {}
        declared = ", ".join(
            f"{symbol}:{'/'.join(values)}" for symbol, values in contracts.items() if values
        ) or "sin contrato declarado"
        rolls = manifest.get("roll_sessions") or []
        series_mode = manifest.get("series_mode") or "adjusted"
        mode_label = "ajustada" if series_mode == "adjusted" else "raw"
        roll_label = f" · {len(rolls)} roll(s)" if rolls else ""
        excluded = manifest.get("excluded_sessions") or []
        excluded_label = f" · {len(excluded)} sesión(es) de roll excluida(s)" if excluded else ""
        return {
            "kind": self.kind,
            "label": self.label,
            "quality": self.quality,
            "connected": True,
            "detail": (
                f"{self.path.name} · {len(self.dataset)} velas 1m sincronizadas (MNQ/NQ/ES) · "
                f"id {self.dataset.dataset_id[:12]} · serie {mode_label}{roll_label}{excluded_label} · {declared}"
            ),
            "session": None,
            "simulated": False,
            "source": self.path.name,
            "path": manifest.get("path"),
            "dataset_id": self.dataset.dataset_id,
            "series_id": self.dataset.series_id,
            "file_hash": self.dataset.file_hash,
            "schema_version": manifest.get("schema_version"),
            "contracts": contracts,
            "contract_column": manifest.get("contract_column", False),
            "contracts_declared": manifest.get("contracts_declared", False),
            "expiry_column": manifest.get("expiry_column", False),
            "contract_expiries": manifest.get("contract_expiries") or {},
            "series_mode": series_mode,
            "contracts_by_session": manifest.get("contracts_by_session") or {},
            "rolls": manifest.get("rolls") or [],
            "roll_sessions": rolls,
            "excluded_sessions": excluded,
            "range": manifest.get("range"),
            "sessions": manifest.get("session_count"),
            "all_sessions": manifest.get("all_sessions") or [],
            "bars": len(self.dataset),
            "first_ts": self.report["first_ts"],
            "last_ts": self.report["last_ts"],
            "aligned": True,
        }


class LiveFeed(MarketFeed):
    """Adaptador real: exige proveedor, credenciales y permisos configurados.

    No simula una conexión. Si falta configuración lanza un error explícito que
    la interfaz muestra tal cual.
    """

    kind = "live"
    label = "DATOS EN VIVO"
    quality = "live"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        broker = settings.live.broker
        if broker == "none":
            raise RuntimeError(
                "No hay proveedor de datos configurado. Elige broker (Tradovate, IBKR o Rithmic), "
                "completa credenciales en variables de entorno y vuelve a intentarlo. "
                "Mientras tanto usa Paper Trading con replay simulado."
            )
        raise RuntimeError(
            f"El adaptador {broker} todavía no está conectado a una cuenta real. "
            "Se requiere API key/suscripción y permisos de datos de futuros CME; "
            "consulta docs/PROVEEDORES.md y no operes con dinero real hasta validarlo."
        )

    async def next_tick(self) -> Tick | None:  # pragma: no cover
        return None


def build_feed(settings: Settings) -> MarketFeed:
    provider = settings.feed.provider
    if provider == "csv":
        return CSVFeed(settings)
    if provider == "live":
        return LiveFeed(settings)
    return SimulatedFeed(settings)


