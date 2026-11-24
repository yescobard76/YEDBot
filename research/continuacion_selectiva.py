"""Harness de investigación para la continuación selectiva pre-registrada.

Este módulo implementa **solo** la hipótesis
``H-CONT-SELECTIVA-2024`` descrita en
``docs/HIPOTESIS_CONTINUACION_SELECTIVA.md``. No se importa desde el motor,
la API, los presets ni la configuración viva, y no modifica ``Settings``.

La regla es deliberadamente estrecha: continuación de una ruptura de 15m
joven, extendida y dentro de la ventana de la mañana, sin retesteo del 50 %
del Opening Range. El harness también aplica las guardas de muestra: rechaza
cualquier sesión de W1-W6 o del holdout sellado.

Uso mínimo::

    from research.continuacion_selectiva import (
        ContinuationRule,
        assert_allowed_dates,
        load_hypothesis_lock,
        scan_session,
    )

    lock = load_hypothesis_lock()
    rule = ContinuationRule.from_lock(lock)
    assert_allowed_dates([date(2024, 3, 12)])
    result = scan_session(date(2024, 3, 12), nq_bars, es_bars, rule=rule)
    if result.signal:
        print(result.signal)

El harness no descarga datos ni ejecuta el holdout. La muestra primaria es
2024 y debe proporcionarse explícitamente; este módulo no la sustituye.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from server.config import Settings
from server.models import Bar, Direction, Divergence
from server.strategy.indicators import aggregate, atr
from server.strategy.orb import build_opening_range
from server.strategy.smt import detect_divergences
from server.timeutil import et_date, et_minutes, hm_to_minutes, timestamp_for

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = ROOT / "docs" / "hipotesis_continuacion_selectiva.lock.json"

# Muestra primaria pre-registrada. No se sustituye por otro periodo.
VALIDATION_START = date(2024, 1, 2)
VALIDATION_END = date(2024, 12, 30)

# Muestras prohibidas por el lock. Las fechas son inclusivas.
W1_START = date(2025, 1, 10)
W1_END = date(2026, 6, 30)
HOLDOUT_START = date(2026, 7, 1)
HOLDOUT_END = date(2026, 10, 30)

PAYLOAD_KEYS: tuple[str, ...] = ("control", "rule", "validation", "gates", "decision")
HYPOTHESIS_STATUS = "pre_registered_not_executed"

# Control congelado del protocolo v1.2. Si Settings cambia (por ejemplo, al
# cargar el perfil vivo 240/24/300), el harness se detiene antes de escanear.
CONTROL: dict[str, Any] = {
    "entry_reference": "or_mid",
    "use_smt": True,
    "setup_validity_minutes": 150,
    "retest_tolerance_ticks": 12,
    "max_sl_ticks": 200,
    "tp_rr": 3.0,
    "breakout_buffer_ticks": 2,
    "min_range_ticks": 10,
    "atr_period": 14,
    "sl_buffer_ticks": 4,
    "confirm_tf": "15m",
    "entry_trigger": "close",
    "require_recovery_close": True,
    "tick_size": 0.25,
    "fill_model": "next_open",
    "risk_per_trade_pct": 1.0,
    "max_contracts": 5,
    "commission_per_contract_side": 0.62,
    "slippage_ticks": 1,
    "orb_start": "09:00",
    "orb_end": "10:00",
    "smt_enabled": True,
    "smt_require_recovery": True,
}

GateStatus = Literal["pass", "fail", "inconclusive"]


class HypothesisLockError(ValueError):
    """El lock no coincide con su payload congelado o no está vigente."""


class ValidationWindowError(ValueError):
    """La muestra solicitada toca W1-W6, el holdout o sale de 2024."""


def _date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _canonical_payload(lock: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in PAYLOAD_KEYS if key not in lock]
    if missing:
        raise HypothesisLockError(f"Lock incompleto: faltan {', '.join(missing)}")
    return {key: lock[key] for key in PAYLOAD_KEYS}


def payload_sha256(lock: Mapping[str, Any]) -> str:
    """Hash canónico del payload congelado, sin metadatos editoriales."""
    encoded = json.dumps(
        _canonical_payload(lock),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_hypothesis_lock(path: str | Path = DEFAULT_LOCK_PATH) -> dict[str, Any]:
    """Carga el lock y rechaza un payload alterado o ya ejecutado."""
    target = Path(path)
    try:
        lock = json.loads(target.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:  # pragma: no cover - entorno incompleto
        raise HypothesisLockError(f"No existe el lock: {target}") from exc
    if not isinstance(lock, dict):
        raise HypothesisLockError("El lock debe ser un objeto JSON")
    expected = lock.get("payload_sha256")
    if not isinstance(expected, str) or not expected:
        raise HypothesisLockError("El lock no declara payload_sha256")
    actual = payload_sha256(lock)
    if actual != expected:
        raise HypothesisLockError(
            f"Payload del lock alterado: esperado {expected}, calculado {actual}"
        )
    if lock.get("status") != HYPOTHESIS_STATUS:
        raise HypothesisLockError(
            "El lock no está en estado pre_registered_not_executed; "
            "no se permite otra ejecución"
        )
    control = lock.get("control") or {}
    for key in (
        "entry_reference",
        "use_smt",
        "setup_validity_minutes",
        "retest_tolerance_ticks",
        "max_sl_ticks",
    ):
        if control.get(key) != CONTROL[key]:
            raise HypothesisLockError(
                f"Control del lock distinto del protocolo v1.2: {key}="
                f"{control.get(key)!r}, esperado {CONTROL[key]!r}"
            )
    validation = lock.get("validation") or {}
    try:
        start = _date(validation["start"])
        end = _date(validation["end"])
    except (KeyError, ValueError) as exc:
        raise HypothesisLockError("El lock no declara una ventana de validación válida") from exc
    assert_allowed_window(start, end)
    return lock


def assert_allowed_dates(days: Iterable[date | str]) -> tuple[date, ...]:
    """Rechaza cualquier sesión de W1-W6 o del holdout sellado.

    También exige que todas las sesiones pertenezcan a la muestra 2024. La
    comprobación es por sesión, no por rango: un CSV que mezcle 2024 con
    desarrollo se rechaza completo.
    """
    checked: list[date] = []
    for raw in days:
        day = _date(raw)
        if W1_START <= day <= W1_END:
            raise ValidationWindowError(
                f"{day.isoformat()} pertenece a W1-W6 "
                f"({W1_START.isoformat()}..{W1_END.isoformat()}); muestra prohibida"
            )
        if HOLDOUT_START <= day <= HOLDOUT_END:
            raise ValidationWindowError(
                f"{day.isoformat()} pertenece al holdout sellado "
                f"({HOLDOUT_START.isoformat()}..{HOLDOUT_END.isoformat()})"
            )
        if not (VALIDATION_START <= day <= VALIDATION_END):
            raise ValidationWindowError(
                f"{day.isoformat()} está fuera de la muestra 2024 "
                f"({VALIDATION_START.isoformat()}..{VALIDATION_END.isoformat()})"
            )
        checked.append(day)
    return tuple(checked)


def assert_allowed_window(start: date | str, end: date | str) -> None:
    """Rechaza una ventana que solape W1-W6, el holdout o salga de 2024."""
    first, last = _date(start), _date(end)
    if first > last:
        raise ValidationWindowError("La ventana de validación está invertida")
    for label, bad_start, bad_end in (
        ("W1-W6", W1_START, W1_END),
        ("holdout sellado", HOLDOUT_START, HOLDOUT_END),
    ):
        if first <= bad_end and last >= bad_start:
            raise ValidationWindowError(
                f"La ventana {first.isoformat()}..{last.isoformat()} toca {label} "
                f"({bad_start.isoformat()}..{bad_end.isoformat()})"
            )
    if first < VALIDATION_START or last > VALIDATION_END:
        raise ValidationWindowError(
            f"La ventana debe estar dentro de 2024 "
            f"({VALIDATION_START.isoformat()}..{VALIDATION_END.isoformat()})"
        )


def assert_control_settings(settings: Settings) -> None:
    """Rechaza un Settings que no sea el control 150/12/200 del lock v1.2."""
    actual = {
        "entry_reference": settings.strategy.entry_reference,
        "use_smt": settings.strategy.use_smt,
        "setup_validity_minutes": settings.strategy.setup_validity_minutes,
        "retest_tolerance_ticks": settings.strategy.retest_tolerance_ticks,
        "max_sl_ticks": settings.risk.max_sl_ticks,
        "tp_rr": settings.strategy.tp_rr,
        "breakout_buffer_ticks": settings.strategy.breakout_buffer_ticks,
        "min_range_ticks": settings.strategy.min_range_ticks,
        "atr_period": settings.strategy.atr_period,
        "sl_buffer_ticks": settings.strategy.sl_buffer_ticks,
        "confirm_tf": settings.strategy.confirm_tf,
        "entry_trigger": settings.strategy.entry_trigger,
        "require_recovery_close": settings.strategy.require_recovery_close,
        "tick_size": settings.execution.tick_size,
        "fill_model": settings.execution.fill_model,
        "risk_per_trade_pct": settings.risk.risk_per_trade_pct,
        "max_contracts": settings.risk.max_contracts,
        "commission_per_contract_side": settings.execution.commission_per_contract_side,
        "slippage_ticks": settings.execution.slippage_ticks,
        "orb_start": settings.orb.start,
        "orb_end": settings.orb.end,
        "smt_enabled": settings.smt.enabled,
        "smt_require_recovery": settings.smt.require_recovery,
    }
    mismatches = [
        f"{key}: lock={CONTROL[key]!r}, activo={actual[key]!r}"
        for key in CONTROL
        if actual[key] != CONTROL[key]
    ]
    if mismatches:
        raise ValueError("Control distinto del lock v1.2: " + "; ".join(mismatches))


def assert_gate_sample(sample: Mapping[str, Any]) -> None:
    """Liga las métricas de C1-C8 a una muestra 2024 con contratos completos."""
    try:
        start = _date(sample["start"])
        end = _date(sample["end"])
        calendar_sessions = int(sample["calendar_sessions"])
        evaluated_sessions = int(sample["evaluated_sessions"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationWindowError(
            "La muestra de gates debe declarar start, end, calendar_sessions y "
            "evaluated_sessions"
        ) from exc
    assert_allowed_window(start, end)

    validation = load_hypothesis_lock()["validation"]
    if start != _date(validation["start"]) or end != _date(validation["end"]):
        raise ValidationWindowError(
            "La muestra de gates no coincide con la ventana 2024 del lock"
        )
    if calendar_sessions != int(validation["expected_calendar_sessions"]):
        raise ValidationWindowError(
            f"La muestra declara {calendar_sessions} sesiones de calendario; "
            f"el lock exige {validation['expected_calendar_sessions']}"
        )
    if evaluated_sessions != int(validation["expected_evaluated_sessions"]):
        raise ValidationWindowError(
            f"La muestra declara {evaluated_sessions} sesiones evaluadas; "
            f"el lock exige {validation['expected_evaluated_sessions']}"
        )
    if sample.get("dataset_id") != validation["dataset_id"]:
        raise ValidationWindowError(
            f"La muestra debe declarar dataset_id={validation['dataset_id']!r}"
        )
    if sample.get("series_mode") != validation["series_mode"]:
        raise ValidationWindowError(
            f"La muestra debe usar series {validation['series_mode']!r}"
        )
    if sample.get("exclude_roll_sessions") is not True:
        raise ValidationWindowError("La muestra debe excluir las sesiones de roll")

    required = set(validation.get("contract_suffixes") or [])
    declared = set(sample.get("contract_suffixes") or [])
    missing = sorted(required - declared)
    if missing:
        raise ValidationWindowError(
            "La muestra de gates no declara los contratos 2024: " + ", ".join(missing)
        )


@dataclass(frozen=True, slots=True)
class ContinuationRule:
    """Parámetros congelados de la continuación selectiva."""

    entry_start: str = "10:30"
    entry_end: str = "13:00"
    min_age_minutes: float = 45.0
    max_age_minutes: float = 90.0
    min_extension_atr: float = 0.75
    stop_cap_ticks: int = 80
    tp_rr: float = 3.0
    breakout_buffer_ticks: int = 2
    stop_buffer_ticks: int = 4
    min_stop_ticks: int = 4
    tick_size: float = 0.25

    @classmethod
    def from_lock(
        cls,
        lock: Mapping[str, Any],
        *,
        tick_size: float = 0.25,
        breakout_buffer_ticks: int = 2,
    ) -> "ContinuationRule":
        rule = lock.get("rule") or {}
        window = rule.get("entry_window_et") or ["10:30", "13:00"]
        age = rule.get("breakout_age_minutes") or {}
        extension = rule.get("extension") or {}
        return cls(
            entry_start=str(window[0]),
            entry_end=str(window[1]),
            min_age_minutes=float(age.get("min", 45)),
            max_age_minutes=float(age.get("max", 90)),
            min_extension_atr=float(extension.get("min", 0.75)),
            stop_cap_ticks=int(rule.get("stop_cap_ticks", 80)),
            tp_rr=float(rule.get("tp_rr", 3.0)),
            breakout_buffer_ticks=int(breakout_buffer_ticks),
            tick_size=float(tick_size),
        )

    @property
    def entry_start_minute(self) -> int:
        return hm_to_minutes(self.entry_start)

    @property
    def entry_end_minute(self) -> int:
        return hm_to_minutes(self.entry_end)

    @property
    def buffer(self) -> float:
        return self.breakout_buffer_ticks * self.tick_size


@dataclass(frozen=True, slots=True)
class TrendBar:
    """Vela de 15m ya cerrada, sin volumen (no participa en la regla)."""

    ts: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class ContinuationCandidate:
    """Hechos causales disponibles en el cierre de la vela de señal."""

    session: date
    direction: Direction
    breakout_level: float
    breakout_close: float
    breakout_confirm_ts: int
    signal_bar_ts: int
    signal_ts: int
    signal_close: float
    entry_ts: int
    entry_price: float | None
    atr15: float | None
    trend_bars: tuple[TrendBar, ...]
    smt_bias: str | None = None
    smt_confirm_ts: int | None = None
    smt_expires_ts: int | None = None
    smt_recovered_ts: int | None = None
    retest_seen: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ContinuationCandidate":
        """Construye un candidato desde el fixture JSON (horas ET legibles)."""
        signal_bar_ts = _parse_et(str(data["signal_bar_et"]))
        signal_ts = int(data.get("signal_ts") or signal_bar_ts + 15 * 60)
        entry_ts = (
            _parse_et(str(data["entry_et"]))
            if data.get("entry_et")
            else signal_ts
        )
        smt = data.get("smt") or {}
        trend = tuple(
            TrendBar(
                ts=_parse_et(str(item["ts_et"])),
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
            )
            for item in data.get("trend_bars", [])
        )
        return cls(
            session=_date(data["session_date"]),
            direction=str(data["direction"]),  # type: ignore[arg-type]
            breakout_level=float(data["breakout_level"]),
            breakout_close=float(data["breakout_close"]),
            breakout_confirm_ts=_parse_et(str(data["breakout_confirm_et"])),
            signal_bar_ts=signal_bar_ts,
            signal_ts=signal_ts,
            signal_close=float(data["signal_close"]),
            entry_ts=entry_ts,
            entry_price=(
                None if data.get("entry_price") is None else float(data["entry_price"])
            ),
            atr15=None if data.get("atr15") is None else float(data["atr15"]),
            trend_bars=trend,
            smt_bias=smt.get("bias"),
            smt_confirm_ts=(
                _parse_et(str(smt["confirm_et"])) if smt.get("confirm_et") else None
            ),
            smt_expires_ts=(
                _parse_et(str(smt["expires_et"])) if smt.get("expires_et") else None
            ),
            smt_recovered_ts=(
                _parse_et(str(smt["recovered_et"])) if smt.get("recovered_et") else None
            ),
            retest_seen=bool(data.get("retest_seen", False)),
        )


@dataclass(frozen=True, slots=True)
class ContinuationSignal:
    id: str
    session: date
    direction: Direction
    breakout_level: float
    signal_bar_ts: int
    signal_ts: int
    entry_ts: int
    entry_price: float
    stop: float
    target: float
    stop_ticks: float
    age_minutes: float
    extension_atr: float
    smt_bias: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session": self.session.isoformat(),
            "direction": self.direction,
            "breakout_level": self.breakout_level,
            "signal_bar_ts": self.signal_bar_ts,
            "signal_ts": self.signal_ts,
            "entry_ts": self.entry_ts,
            "entry_price": self.entry_price,
            "stop": self.stop,
            "target": self.target,
            "stop_ticks": self.stop_ticks,
            "age_minutes": self.age_minutes,
            "extension_atr": self.extension_atr,
            "smt_bias": self.smt_bias,
        }


@dataclass(frozen=True, slots=True)
class ContinuationDecision:
    accepted: bool
    reasons: tuple[str, ...]
    age_minutes: float | None
    extension_atr: float | None
    signal: ContinuationSignal | None

    @property
    def reason(self) -> str | None:
        return self.reasons[0] if self.reasons else None


def _parse_et(value: str) -> int:
    """``YYYY-MM-DD HH:MM`` en America/New_York -> epoch."""
    text = value.strip().replace("T", " ")
    day_text, time_text = text.split()
    return timestamp_for(date.fromisoformat(day_text), time_text[:5])


def _trend_ok(bars: Sequence[TrendBar], direction: Direction) -> bool:
    if len(bars) < 3:
        return False
    recent = bars[-3:]
    if direction == "long":
        return all(
            cur.close > prev.close and cur.high > prev.high and cur.low > prev.low
            for prev, cur in zip(recent, recent[1:])
        )
    return all(
        cur.close < prev.close and cur.high < prev.high and cur.low < prev.low
        for prev, cur in zip(recent, recent[1:])
    )


def evaluate_candidate(
    candidate: ContinuationCandidate,
    rule: ContinuationRule | None = None,
) -> ContinuationDecision:
    """Aplica la regla congelada a un candidato causal.

    No lee barras futuras ni modifica el candidato. Cada condición fallida
    añade un código estable a ``reasons``; el primer código es el diagnóstico
    principal.
    """
    assert_allowed_dates([candidate.session])
    rule = rule or ContinuationRule()
    reasons: list[str] = []

    if candidate.direction not in ("long", "short"):
        reasons.append("invalid_direction")
    if candidate.signal_ts != candidate.signal_bar_ts + 15 * 60:
        reasons.append("invalid_signal_bar")
    if candidate.signal_ts <= candidate.breakout_confirm_ts:
        reasons.append("signal_before_breakout")
    if candidate.entry_ts < candidate.signal_ts:
        reasons.append("fill_before_signal")

    expected_bias = "bullish" if candidate.direction == "long" else "bearish"
    if candidate.smt_bias is None:
        reasons.append("smt_missing")
    elif candidate.smt_bias != expected_bias:
        reasons.append("smt_wrong_bias")
    if candidate.smt_confirm_ts is None:
        reasons.append("smt_unconfirmed")
    elif candidate.smt_confirm_ts > candidate.signal_ts:
        reasons.append("smt_not_confirmed_before_signal")
    if candidate.smt_expires_ts is None:
        reasons.append("smt_missing_expiry")
    elif candidate.smt_expires_ts < candidate.signal_ts:
        reasons.append("smt_expired")
    if candidate.smt_recovered_ts is None:
        reasons.append("smt_not_recovered")
    elif candidate.smt_recovered_ts > candidate.signal_ts:
        reasons.append("smt_recovered_after_signal")

    if candidate.retest_seen:
        reasons.append("retest_seen")

    if len(candidate.trend_bars) < 3:
        reasons.append("trend_bars_missing")
    else:
        if any(bar.ts + 15 * 60 > candidate.signal_ts for bar in candidate.trend_bars):
            reasons.append("trend_bar_not_closed")
        if not _trend_ok(candidate.trend_bars, candidate.direction):
            reasons.append("trend_not_consecutive")

    last_close = candidate.signal_close
    if candidate.direction == "long":
        if last_close <= candidate.breakout_level + rule.buffer:
            reasons.append("close_not_beyond_breakout")
    else:
        if last_close >= candidate.breakout_level - rule.buffer:
            reasons.append("close_not_beyond_breakout")

    age = (candidate.signal_ts - candidate.breakout_confirm_ts) / 60
    if age < rule.min_age_minutes:
        reasons.append("age_below_min")
    elif age > rule.max_age_minutes:
        reasons.append("age_above_max")

    extension: float | None = None
    if candidate.atr15 is None or candidate.atr15 <= 0:
        reasons.append("atr_unavailable")
    else:
        distance = (
            last_close - candidate.breakout_level
            if candidate.direction == "long"
            else candidate.breakout_level - last_close
        )
        extension = distance / candidate.atr15
        if extension < rule.min_extension_atr:
            reasons.append("extension_below_min")

    minute = et_minutes(candidate.signal_ts)
    if not (rule.entry_start_minute <= minute < rule.entry_end_minute):
        reasons.append("outside_window")

    entry = candidate.entry_price
    if entry is None or entry <= 0:
        reasons.append("missing_fill")
        entry = None

    stop: float | None = None
    target: float | None = None
    stop_ticks: float | None = None
    if entry is not None and candidate.trend_bars:
        recent = candidate.trend_bars[-3:]
        tick = rule.tick_size
        if candidate.direction == "long":
            structure = min(bar.low for bar in recent)
            stop = structure - rule.stop_buffer_ticks * tick
            floor = entry - rule.min_stop_ticks * tick
            if stop >= floor:
                stop = floor
            distance = entry - stop
        else:
            structure = max(bar.high for bar in recent)
            stop = structure + rule.stop_buffer_ticks * tick
            ceiling = entry + rule.min_stop_ticks * tick
            if stop <= ceiling:
                stop = ceiling
            distance = stop - entry
        if distance <= 0:
            reasons.append("invalid_stop")
        else:
            stop_ticks = min(distance / tick, float(rule.stop_cap_ticks))
            distance = stop_ticks * tick
            stop = entry - distance if candidate.direction == "long" else entry + distance
            target = (
                entry + rule.tp_rr * distance
                if candidate.direction == "long"
                else entry - rule.tp_rr * distance
            )
    elif entry is not None:
        reasons.append("no_structure")

    if reasons:
        return ContinuationDecision(
            accepted=False,
            reasons=tuple(dict.fromkeys(reasons)),
            age_minutes=round(age, 3),
            extension_atr=None if extension is None else round(extension, 4),
            signal=None,
        )

    assert entry is not None and stop is not None and target is not None
    assert stop_ticks is not None and extension is not None
    signal = ContinuationSignal(
        id=f"{candidate.session.isoformat()}-cont-{candidate.direction}-{candidate.breakout_confirm_ts}",
        session=candidate.session,
        direction=candidate.direction,
        breakout_level=candidate.breakout_level,
        signal_bar_ts=candidate.signal_bar_ts,
        signal_ts=candidate.signal_ts,
        entry_ts=candidate.entry_ts,
        entry_price=round(entry, 4),
        stop=round(stop, 4),
        target=round(target, 4),
        stop_ticks=round(stop_ticks, 2),
        age_minutes=round(age, 3),
        extension_atr=round(extension, 4),
        smt_bias=candidate.smt_bias or expected_bias,
    )
    return ContinuationDecision(
        accepted=True,
        reasons=(),
        age_minutes=round(age, 3),
        extension_atr=round(extension, 4),
        signal=signal,
    )


@dataclass(frozen=True, slots=True)
class ScanResult:
    session: date
    breakout: dict[str, Any] | None
    decisions: tuple[ContinuationDecision, ...]
    reason: str | None = None

    @property
    def signal(self) -> ContinuationSignal | None:
        return next((item.signal for item in self.decisions if item.signal), None)


def _recovery_ts(
    divergence: Divergence,
    bars: Sequence[Bar],
    buffer: float,
    signal_ts: int,
) -> int | None:
    for bar in bars:
        if bar.ts <= divergence.confirm_ts:
            continue
        if bar.ts + 60 > signal_ts:
            break
        if divergence.bias == "bullish" and bar.close > divergence.level + buffer:
            return bar.ts + 60
        if divergence.bias == "bearish" and bar.close < divergence.level - buffer:
            return bar.ts + 60
    return None


def _matching_divergence(
    divergences: Sequence[Divergence],
    direction: Direction,
    signal_ts: int,
) -> Divergence | None:
    wanted = "bullish" if direction == "long" else "bearish"
    matching = [
        item
        for item in divergences
        if item.bias == wanted
        and item.confirm_ts + 60 <= signal_ts
        and item.expires_ts >= signal_ts
    ]
    return max(matching, key=lambda item: item.confirm_ts) if matching else None


def scan_session(
    day: date,
    nq: Sequence[Bar],
    es: Sequence[Bar],
    *,
    settings: Settings | None = None,
    rule: ContinuationRule | None = None,
    divergences: Sequence[Divergence] | None = None,
) -> ScanResult:
    """Busca la primera continuación selectiva válida de una sesión 2024.

    ``settings`` es el control de la estrategia (por defecto ``Settings()``);
    nunca se carga la configuración viva. ``divergences`` permite inyectar un
    conjunto ya calculado y se filtra por causalidad antes de usarlo.
    """
    assert_allowed_dates([day])
    settings = settings or Settings()
    assert_control_settings(settings)
    frozen_rule = ContinuationRule.from_lock(load_hypothesis_lock())
    if rule is None:
        rule = frozen_rule
    elif rule != frozen_rule:
        raise ValueError("La regla del escáner no coincide con el lock pre-registrado")

    tick = settings.execution.tick_size
    session_nq = sorted((bar for bar in nq if et_date(bar.ts) == day), key=lambda bar: bar.ts)
    session_es = sorted((bar for bar in es if et_date(bar.ts) == day), key=lambda bar: bar.ts)
    if len(session_nq) < 60 or len(session_es) < 60:
        return ScanResult(day, None, (), "sin_datos")

    orb = build_opening_range(session_nq, settings.orb, tick)
    if orb is None or not orb.complete:
        return ScanResult(day, None, (), "or_incompleto")
    if orb.width_pct > settings.orb.max_width_pct:
        return ScanResult(day, None, (), "or_demasiado_amplio")
    if orb.width < settings.strategy.min_range_ticks * tick:
        return ScanResult(day, None, (), "or_demasiado_estrecho")

    post = [bar for bar in session_nq if bar.ts >= orb.end_ts]
    bars15 = aggregate(post, 15)
    buffer = settings.strategy.breakout_buffer_ticks * tick
    breakout_bar: Bar | None = None
    direction: Direction | None = None
    for bar in bars15:
        if bar.close > orb.high + buffer:
            breakout_bar, direction = bar, "long"
            break
        if bar.close < orb.low - buffer:
            breakout_bar, direction = bar, "short"
            break
    if breakout_bar is None or direction is None:
        return ScanResult(day, None, (), "sin_ruptura")

    breakout = {
        "direction": direction,
        "level": orb.high if direction == "long" else orb.low,
        "close": breakout_bar.close,
        "bar_ts": breakout_bar.ts,
        "confirm_ts": breakout_bar.ts + 15 * 60,
        "timeframe": "15m",
    }
    confirm_ts = int(breakout["confirm_ts"])
    decisions: list[ContinuationDecision] = []
    for bar in bars15:
        if bar.ts <= breakout_bar.ts:
            continue
        signal_ts = bar.ts + 15 * 60
        age = (signal_ts - confirm_ts) / 60
        if age > rule.max_age_minutes:
            break
        if et_minutes(signal_ts) >= rule.entry_end_minute:
            break
        if age < rule.min_age_minutes:
            continue
        if et_minutes(signal_ts) < rule.entry_start_minute:
            continue

        closed_nq = [item for item in session_nq if item.ts + 60 <= signal_ts]
        closed_es = [item for item in session_es if item.ts + 60 <= signal_ts]
        if divergences is None:
            es_map = {item.ts: item for item in closed_es}
            nq_aligned = [item for item in closed_nq if item.ts in es_map]
            es_aligned = [es_map[item.ts] for item in nq_aligned]
            found = detect_divergences(
                nq_aligned, es_aligned, settings.smt, tick
            ) if nq_aligned else []
        else:
            found = list(divergences)
        divergence = _matching_divergence(found, direction, signal_ts)
        recovered_ts = (
            _recovery_ts(divergence, closed_nq, buffer, signal_ts)
            if divergence is not None
            else None
        )

        reference = orb.mid
        tolerance = settings.strategy.retest_tolerance_ticks * tick
        after_confirm = [
            item
            for item in session_nq
            if item.ts >= confirm_ts and item.ts + 60 <= signal_ts
        ]
        if direction == "long":
            retest_seen = any(item.low <= reference + tolerance for item in after_confirm)
        else:
            retest_seen = any(item.high >= reference - tolerance for item in after_confirm)

        closed15 = [item for item in bars15 if item.ts + 15 * 60 <= signal_ts]
        atr15 = atr(closed15, settings.strategy.atr_period) if len(closed15) >= 2 else None
        trend_bars = tuple(
            TrendBar(item.ts, item.open, item.high, item.low, item.close)
            for item in closed15[-3:]
        )
        fill_bar = next((item for item in session_nq if item.ts == signal_ts), None)
        candidate = ContinuationCandidate(
            session=day,
            direction=direction,
            breakout_level=float(breakout["level"]),
            breakout_close=breakout_bar.close,
            breakout_confirm_ts=confirm_ts,
            signal_bar_ts=bar.ts,
            signal_ts=signal_ts,
            signal_close=bar.close,
            entry_ts=signal_ts,
            entry_price=None if fill_bar is None else fill_bar.open,
            atr15=atr15,
            trend_bars=trend_bars,
            smt_bias=divergence.bias if divergence is not None else None,
            smt_confirm_ts=(
                divergence.confirm_ts + 60 if divergence is not None else None
            ),
            smt_expires_ts=divergence.expires_ts if divergence is not None else None,
            smt_recovered_ts=recovered_ts,
            retest_seen=retest_seen,
        )
        decision = evaluate_candidate(candidate, rule)
        decisions.append(decision)
        if decision.accepted:
            break

    return ScanResult(day, breakout, tuple(decisions), None)


@dataclass(frozen=True, slots=True)
class GateCheck:
    id: str
    name: str
    status: GateStatus
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == "pass"


@dataclass(frozen=True, slots=True)
class HypothesisDecision:
    status: Literal["candidate_for_paper_not_live", "rejected", "inconclusive"]
    gates: tuple[GateCheck, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "gates": [
                {
                    "id": gate.id,
                    "name": gate.name,
                    "status": gate.status,
                    "detail": gate.detail,
                }
                for gate in self.gates
            ],
        }


def evaluate_gates(
    *,
    sample: Mapping[str, Any],
    integrity: bool,
    continuation: Mapping[str, Any],
    baseline: Mapping[str, Any],
    portfolio: Mapping[str, Any],
    quarters: Sequence[Mapping[str, Any]],
    cost_stress: Mapping[str, Any],
    determinism: Mapping[str, Any],
) -> HypothesisDecision:
    """Evalúa C1-C8 del lock sobre métricas ya calculadas.

    No ejecuta backtests: recibe los agregados B, C, V, trimestres y el
    contraste de costes. Un dato ausente produce ``inconclusive``, nunca un
    pase silencioso. ``sample`` debe declarar la muestra 2024 y sus contratos;
    sin esa preflight, las métricas no se evalúan.
    """
    assert_gate_sample(sample)
    gates: list[GateCheck] = []

    gates.append(
        GateCheck(
            "C1",
            "Integridad de la muestra 2024",
            "pass" if integrity else "fail",
            (
                f"{sample['calendar_sessions']} sesiones de calendario y "
                f"{sample['evaluated_sessions']} evaluadas"
                if integrity
                else "integridad fallida"
            ),
        )
    )

    trades = int(continuation.get("trades") or 0)
    if trades >= 20:
        c2_status: GateStatus = "pass"
        c2_detail = f"{trades} operaciones C (>=20)"
    else:
        c2_status = "inconclusive"
        c2_detail = f"{trades} operaciones C; se requieren >=20 para decidir"
    gates.append(GateCheck("C2", "Muestra de continuación", c2_status, c2_detail))

    continuation_pf = continuation.get("profit_factor")
    expectancy = continuation.get("expectancy_r")
    c3_ok = (
        continuation_pf is not None
        and expectancy is not None
        and float(continuation_pf) >= 1.25
        and float(expectancy) >= 0.10
    )
    gates.append(
        GateCheck(
            "C3",
            "Edge de la continuación",
            "pass" if c3_ok else "fail",
            f"PF={continuation_pf}, esperanza={expectancy} R",
        )
    )

    baseline_pf = baseline.get("profit_factor")
    baseline_net = baseline.get("net_profit")
    portfolio_pf = portfolio.get("profit_factor")
    portfolio_net = portfolio.get("net_profit")
    c4_ok = (
        baseline_pf is not None
        and baseline_net is not None
        and portfolio_pf is not None
        and portfolio_net is not None
        and float(portfolio_pf) >= float(baseline_pf)
        and float(portfolio_net) > float(baseline_net)
    )
    gates.append(
        GateCheck(
            "C4",
            "Portfolio frente a baseline",
            "pass" if c4_ok else "fail",
            f"PF V={portfolio_pf} vs B={baseline_pf}; neto V={portfolio_net} vs B={baseline_net}",
        )
    )

    baseline_dd = baseline.get("max_drawdown")
    portfolio_dd = portfolio.get("max_drawdown")
    c5_ok = (
        baseline_dd is not None
        and portfolio_dd is not None
        and float(portfolio_dd) <= float(baseline_dd) + 500.0
        and float(portfolio_dd) <= 2500.0
    )
    gates.append(
        GateCheck(
            "C5",
            "Drawdown del portfolio",
            "pass" if c5_ok else "fail",
            f"DD V={portfolio_dd}, B={baseline_dd}",
        )
    )

    if len(quarters) < 4:
        c6_status: GateStatus = "inconclusive"
        c6_detail = f"{len(quarters)} trimestres; se requieren 4"
    else:
        non_negative = sum(
            item.get("net_profit") is not None
            and float(item["net_profit"]) >= 0
            for item in quarters
        )
        bad = any(
            int(item.get("trades") or 0) >= 10
            and (item.get("profit_factor") is None or float(item["profit_factor"]) < 0.80)
            for item in quarters
        )
        c6_pass = non_negative >= 3 and not bad
        c6_status = "pass" if c6_pass else "fail"
        c6_detail = f"{non_negative}/4 trimestres no negativos; trimestre malo={bad}"
    gates.append(GateCheck("C6", "Consistencia trimestral", c6_status, c6_detail))

    cost_pf = cost_stress.get("profit_factor")
    c7_ok = cost_pf is not None and float(cost_pf) >= 1.10
    gates.append(
        GateCheck(
            "C7",
            "Costes duplicados",
            "pass" if c7_ok else "fail",
            f"PF con costes={cost_pf}",
        )
    )

    c8_ok = bool(
        determinism.get("baseline_repeat_identical")
        and determinism.get("signal_before_fill")
    )
    gates.append(
        GateCheck(
            "C8",
            "Determinismo y causalidad",
            "pass" if c8_ok else "fail",
            "baseline repetido y señal anterior al fill" if c8_ok else "falló determinismo/causalidad",
        )
    )

    if any(gate.status == "fail" for gate in gates):
        status = "rejected"
    elif any(gate.status == "inconclusive" for gate in gates):
        status = "inconclusive"
    else:
        status = "candidate_for_paper_not_live"
    return HypothesisDecision(status=status, gates=tuple(gates))
