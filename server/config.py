"""Configuración centralizada.

Todo el estado configurable de la aplicación vive en :class:`Settings`.
Se persiste de forma atómica y se valida con Pydantic antes de aplicarse, de
modo que un valor inválido nunca llega al motor. Por defecto usa ``data/``;
``YED_PROFILE_DIR`` (o ``YED_CONFIG_PATH``/``YED_DB_PATH``) permite un perfil
aislado sin tocar la demo.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _profile_path(raw: str | None, default: Path) -> Path:
    """Resuelve una ruta de perfil; las relativas parten del proyecto."""
    if not raw or not raw.strip():
        return default
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


# Un perfil aislado puede usar su propio directorio, configuración y SQLite.
# Sin variables de entorno se conserva exactamente el comportamiento de data/.
PROFILE_DIR = _profile_path(os.environ.get("YED_PROFILE_DIR"), DATA_DIR)
CONFIG_PATH = _profile_path(os.environ.get("YED_CONFIG_PATH"), PROFILE_DIR / "config.json")
DB_PATH = _profile_path(os.environ.get("YED_DB_PATH"), CONFIG_PATH.parent / "yedbot.db")

TIMEZONE = "America/New_York"


class ORBConfig(BaseModel):
    """Opening Range (Fase A)."""

    start: str = "09:00"
    end: str = "10:00"
    timezone: str = TIMEZONE
    max_width_pct: float = Field(
        default=1.2,
        ge=0.05,
        le=10.0,
        description="Si el rango supera este % del precio se considera demasiado amplio.",
    )

    @field_validator("start", "end")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        parts = v.split(":")
        if len(parts) != 2:
            raise ValueError("Formato de hora inválido, use HH:MM")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Hora fuera de rango")
        return f"{h:02d}:{m:02d}"

    @model_validator(mode="after")
    def _order(self) -> "ORBConfig":
        if self.start >= self.end:
            raise ValueError("El inicio del Opening Range debe ser anterior al fin")
        return self


class SMTConfig(BaseModel):
    """Divergencias intermarket NQ vs ES (Fase C)."""

    enabled: bool = True
    pivot_depth: int = Field(default=5, ge=2, le=30)
    window_minutes: int = Field(default=60, ge=5, le=240)
    tolerance_ticks: int = Field(default=8, ge=0, le=100)
    min_break_ticks: int = Field(default=2, ge=0, le=100)
    validity_minutes: int = Field(default=120, ge=10, le=480)
    detect_tf: Literal["1m", "5m", "15m"] = "1m"
    require_recovery: bool = True


class StrategyConfig(BaseModel):
    """Fases B, D y E."""

    name: str = "YED ORB+SMT"
    confirm_tf: Literal["1m", "5m", "15m", "30m"] = "15m"
    require_close_breakout: bool = True
    breakout_buffer_ticks: int = Field(default=2, ge=0, le=80)
    min_range_ticks: int = Field(default=10, ge=0, le=400)
    setup_validity_minutes: int = Field(default=150, ge=15, le=480)
    use_smt: bool = True
    allow_reentry_after_false_breakout: bool = False
    # Referencia de entrada. Ver docs/ESTRATEGIA.md para la fórmula exacta.
    #   or_mid         -> 50% del Opening Range: (High + Low) / 2
    #   or_retracement -> retroceso superficial medido desde ORH/ORL
    #                     (p. ej. 30% o 38.2% del ancho del rango)
    #   breakout_level -> nivel roto (OR High / OR Low)
    #   half_leg       -> 50% del recorrido de la pierna de ruptura
    #   none           -> entrada directa a la ruptura
    entry_reference: Literal[
        "or_mid", "or_retracement", "breakout_level", "half_leg", "none"
    ] = "or_mid"
    or_retracement_pct: float = Field(
        default=0.382,
        ge=0.1,
        le=0.49,
        description=(
            "Retroceso del ancho del OR para entry_reference=or_retracement. "
            "0.30 = 30%, 0.382 = 38.2%; 0.50 equivale a or_mid."
        ),
    )
    # E-1: profundidad del retesteo sobre el camino ORH/ORL -> mid.
    # 0 = borde del OR, 0.25 = retesteo superficial, 1 = 50% del OR (or_mid).
    # El default 1.0 conserva exactamente la referencia histórica.
    retest_depth: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Profundidad del retesteo para entry_reference=or_mid. "
            "0 = borde del OR; 0.25 = un cuarto del camino al mid; 1 = mid."
        ),
    )
    retest_tolerance_ticks: int = Field(default=12, ge=0, le=200)
    # Independiente de entry_trigger: si es False, basta el rechazo dentro de
    # la tolerancia y no se espera una vela de recuperación.
    require_recovery_close: bool = True
    entry_trigger: Literal["close", "touch"] = "close"
    # Stop loss
    # "confirmation" es la geometría de stop de E-1: estructura de 15m sin
    # anclaje al mid del OR. No se activa por defecto ni en ningún preset vivo.
    sl_mode: Literal["structural", "or_mid", "atr", "confirmation"] = "structural"
    sl_buffer_ticks: int = Field(default=4, ge=0, le=100)
    atr_period: int = Field(default=14, ge=2, le=100)
    atr_sl_mult: float = Field(default=1.2, ge=0.2, le=5.0)
    # Take profit
    tp_rr: float = Field(default=3.0, ge=0.5, le=10.0)
    structural_depth: int = Field(default=3, ge=1, le=20)


class RiskConfig(BaseModel):
    """Gestión de riesgo (módulo independiente)."""

    initial_capital: float = Field(default=25_000.0, gt=0)
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=10)
    max_daily_loss_pct: float = Field(default=3.0, gt=0, le=50)
    max_daily_profit_pct: float = Field(default=0.0, ge=0, le=100, description="0 = sin límite")
    max_trades_per_day: int = Field(default=3, ge=1, le=50)
    max_concurrent_positions: int = Field(default=1, ge=1, le=5)
    max_contracts: int = Field(default=5, ge=1, le=100)
    max_sl_ticks: int = Field(default=200, ge=5, le=2000)
    # Rechaza entradas cuyo stop sea menor que esta fracción del ancho del
    # Opening Range. 0 = desactivado; no cambia el comportamiento histórico.
    min_stop_or_ratio: float = Field(default=0.0, ge=0, le=1)
    trade_window_start: str = "09:00"
    trade_window_end: str = "15:30"
    # Ventana opcional para no abrir entradas (p. ej. la pausa del mediodía).
    # Ambas horas vacías = desactivada. Se expresa en la zona del ORB.
    entry_exclusion_start: str = ""
    entry_exclusion_end: str = ""
    close_at_session_end: bool = True
    session_close_time: str = "15:55"
    cooldown_minutes: int = Field(default=5, ge=0, le=240)
    no_trade_after_consecutive_losses: int = Field(default=0, ge=0, le=10)

    @field_validator("entry_exclusion_start", "entry_exclusion_end")
    @classmethod
    def _optional_hhmm(cls, v: str) -> str:
        raw = (v or "").strip()
        if not raw:
            return ""
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError("Formato de hora inválido, use HH:MM")
        try:
            h, m = int(parts[0]), int(parts[1])
        except ValueError:
            raise ValueError("Formato de hora inválido, use HH:MM") from None
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Hora fuera de rango")
        return f"{h:02d}:{m:02d}"

    @model_validator(mode="after")
    def _entry_exclusion(self) -> "RiskConfig":
        start = self.entry_exclusion_start
        end = self.entry_exclusion_end
        if bool(start) != bool(end):
            raise ValueError("La ventana de exclusión requiere hora de inicio y fin")
        if start and start >= end:
            raise ValueError("El inicio de la exclusión debe ser anterior al fin")
        return self


class ExecutionConfig(BaseModel):
    """Modelo de ejecución y costes."""

    tick_size: float = 0.25
    tick_value: float = 0.50
    point_value: float = 2.00
    slippage_ticks: int = Field(default=1, ge=0, le=20)
    commission_per_contract_side: float = Field(default=0.62, ge=0, le=20)
    fill_model: Literal["next_open", "signal_price"] = "next_open"
    simulate_partial_fills: bool = False
    partial_fill_ratio: float = Field(default=0.6, gt=0, le=1)
    max_slippage_ticks: int = Field(default=4, ge=0, le=50)


class FeedConfig(BaseModel):
    """Origen de datos y velocidad de replay."""

    provider: Literal["simulated", "csv", "live"] = "simulated"
    csv_path: str = "data/bars.csv"
    series_mode: Literal["raw", "adjusted"] = "adjusted"
    exclude_roll_sessions: bool = True
    replay_speed: float = Field(default=2.5, gt=0.1, le=200, description="Velas de 1m por segundo")
    loop_sessions: bool = True
    start_date: str = ""
    latency_ms: int = Field(default=0, ge=0, le=5000)


class LiveConfig(BaseModel):
    """Parámetros del adaptador de broker (nunca contienen secretos)."""

    broker: Literal["none", "tradovate", "ibkr", "rithmic"] = "none"
    environment: Literal["demo", "live"] = "demo"
    account_ref: str = ""
    data_feed: str = ""
    live_enabled: bool = False
    live_confirmation: str = ""


class Settings(BaseModel):
    instrument: str = "MNQ"
    reference_symbol: str = "NQ"
    comparison_symbol: str = "ES"
    mode: Literal["paper", "live"] = "paper"
    orb: ORBConfig = Field(default_factory=ORBConfig)
    smt: SMTConfig = Field(default_factory=SMTConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    feed: FeedConfig = Field(default_factory=FeedConfig)
    live: LiveConfig = Field(default_factory=LiveConfig)

    def confirm_minutes(self) -> int:
        return int(self.strategy.confirm_tf.rstrip("m"))


def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".cfg-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_settings() -> Settings:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        settings = Settings()
        save_settings(settings)
        return settings
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return Settings.model_validate(raw)
    except Exception:
        # Una configuración corrupta no debe impedir arrancar el motor:
        # se respalda el archivo y se vuelve a los valores por defecto.
        try:
            CONFIG_PATH.replace(CONFIG_PATH.with_suffix(".json.broken"))
        except OSError:
            pass
        settings = Settings()
        save_settings(settings)
        return settings


def save_settings(settings: Settings) -> None:
    _atomic_write(CONFIG_PATH, settings.model_dump_json(indent=2))


def apply_settings(current: Settings, patch: dict) -> Settings:
    """Aplica un patch parcial validado y devuelve la nueva configuración."""
    merged = current.model_dump()
    _deep_merge(merged, patch)
    return Settings.model_validate(merged)


def _deep_merge(base: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
