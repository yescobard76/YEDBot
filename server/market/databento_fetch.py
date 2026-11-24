"""Descarga Databento y construye el CSV del protocolo de backtest.

El módulo hace tres cosas, en este orden:

1. Lee las definiciones de los 24 contratos trimestrales del protocolo
   (``H25`` … ``Z26`` para MNQ, NQ y ES) y calcula la sesión de roll de cada
   contrato con la regla pre-registrada ``expiry − 8 días``.
2. Descarga ``ohlcv-1m`` solo para esos contratos y deja una única fila por
   símbolo, minuto y contrato activo. Convierte ``ts_event`` a
   ``America/New_York``, filtra la ventana operativa y descarta contratos que
   no estén activos ese día.
3. Rellena únicamente minutos aislados sin operaciones con una barra plana
   (``open=high=low=close=cierre anterior``, ``volume=0``). Si hay dos minutos
   consecutivos ausentes, aborta: el protocolo no permite inventar ese hueco.
   Cada relleno queda registrado en un CSV auxiliar.

Uso real (la clave se lee de ``DATABENTO_API_KEY``)::

    python -m server.market.databento_fetch

Prueba local sin credenciales ni red::

    python -m server.market.databento_fetch \
        --fixture tests/fixtures/databento_small.json \
        --start 2025-07-03 --end 2025-07-04 \
        --out /tmp/bars.csv --fills-out /tmp/fills.csv --summary /tmp/summary.json

El CSV resultante tiene el encabezado del protocolo::

    timestamp,symbol,open,high,low,close,volume,contract,expiry

El comando rechaza cualquier ventana que termine dentro del holdout sellado y,
con ``--activate``, deja ``data/config.json`` apuntando al CSV solo después de
que la validación lo acepte. El CSV se escribe en un temporal y se renombra al
final: un fallo no deja un archivo a medias ni activa una configuración rota.

No ejecuta backtests ni arranca el motor. Las salidas por defecto van a
``data/real/`` (ignorado por git); con ``--dates``, el registro de rellenos y
el resumen se escriben junto al CSV del piloto (``<nombre>_fills.csv`` y
``<nombre>_summary.json``) para no pisar las rutas del dataset completo. No
toca ``data/`` de la demo ni ``profiles/dryrun/``.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..config import BASE_DIR, CONFIG_PATH, load_settings, save_settings
from ..timeutil import et_date, et_minutes, hm_to_minutes, local_dt, timestamp_for
from .contracts import CODE_MONTHS, MONTH_CODES
from .csv_data import HOLDOUT_END, HOLDOUT_START, REQUIRED_SYMBOLS, inspect_csv
from .sessions import early_close_time, is_trading_day

DATASET = "GLBX.MDP3"
DEFINITION_LEAD_DAYS = 120
ROOTS: tuple[str, ...] = ("MNQ", "NQ", "ES")
QUARTERS: tuple[tuple[int, int], ...] = (
    (2025, 3),
    (2025, 6),
    (2025, 9),
    (2025, 12),
    (2026, 3),
    (2026, 6),
    (2026, 9),
    (2026, 12),
)
EXPECTED_CODES: tuple[str, ...] = tuple(
    f"{root}{CODE_MONTHS[month]}{year % 100:02d}"
    for root in ROOTS
    for year, month in QUARTERS
)
DEFAULT_START = date(2025, 1, 10)
DEFAULT_END = date(2026, 6, 30)
DEFAULT_OUT = Path("data/real/bars_mnq_nq_es_1m.csv")
DEFAULT_FILLS_OUT = Path("data/real/bars_mnq_nq_es_1m_fills.csv")
DEFAULT_SUMMARY = Path("data/real/bars_mnq_nq_es_1m_summary.json")
SESSION_START_MINUTE = 9 * 60
MAX_FLAT_FILLED_BARS = 570
CONTRACT_RE = re.compile(
    r"^(?P<root>[A-Z]{1,5})(?P<month>[FGHJKMNQUVXZ])(?P<year>\d{1,2})$"
)
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
DOWNLOAD_ATTEMPTS = 3
RETRY_BASE_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class Definition:
    """Definición de un contrato, ya normalizada al código del CSV."""

    root: str
    raw_symbol: str
    code: str
    expiry: date
    instrument_id: int | None = None

    @property
    def roll_date(self) -> date:
        """Sesión de roll: última sesión en la que este contrato sigue activo."""
        return roll_out(self.expiry)


@dataclass(frozen=True, slots=True)
class BarRow:
    """Una fila del CSV del protocolo."""

    ts: int
    day: date
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    contract: str
    expiry: date


@dataclass(frozen=True, slots=True)
class FillRow:
    """Un minuto rellenado con barra plana."""

    ts: int
    symbol: str
    contract: str
    expiry: date
    previous_close: float


@dataclass(slots=True)
class ConversionResult:
    rows: list[BarRow]
    fills: list[FillRow]
    definitions: dict[str, Definition]
    summary: dict[str, Any]


def _records(value: Any) -> list[dict[str, Any]]:
    """Convierte una respuesta de Databento (DataFrame o iterable) en dicts."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if hasattr(value, "to_dict") and not isinstance(value, (str, bytes)):
        try:
            records = value.to_dict("records")
        except TypeError:
            records = value.to_dict()
        if isinstance(records, dict):
            return [records]
        return [dict(record) for record in records]
    return [dict(record) if not isinstance(record, dict) else record for record in value]


def _definition_symbol(record: dict[str, Any]) -> str:
    raw = record.get("raw_symbol")
    if raw is None or (isinstance(raw, float) and math.isnan(raw)):
        raw = record.get("symbol")
    return str(raw or "").strip().upper()


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number > 1e17:
            number /= 1e9
        elif number > 1e14:
            number /= 1e6
        elif number > 1e11:
            number /= 1e3
        return datetime.fromtimestamp(number, tz=timezone.utc).date()
    text = str(value or "").strip()
    if not text or text.lower() in {"nat", "none"}:
        raise ValueError("expiration vacío o inválido")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"expiration inválido: {text!r}") from None
        return parsed.date()


def _as_epoch(value: Any) -> int:
    """Convierte ts_event (ns, ms, epoch o ISO UTC) a segundos UTC."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        seconds = int(value.timestamp())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("ts_event no finito")
        if abs(number) >= 1e17:
            number /= 1e9
        elif abs(number) >= 1e14:
            number /= 1e6
        elif abs(number) >= 1e11:
            number /= 1e3
        seconds = int(number)
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("ts_event vacío")
        try:
            number = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                raise ValueError(f"ts_event inválido: {text!r}") from None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            seconds = int(parsed.timestamp())
        else:
            seconds = _as_epoch(number)
    if seconds % 60:
        raise ValueError(f"ts_event no está alineado al minuto: {value!r}")
    return seconds


def _as_float(value: Any, field: str, ts: int, symbol: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{symbol} {local_dt(ts):%Y-%m-%d %H:%M}: {field} no numérico") from None
    if not math.isfinite(number):
        raise ValueError(f"{symbol} {local_dt(ts):%Y-%m-%d %H:%M}: {field} no finito")
    return number


def roll_out(expiry: date) -> date:
    """Sesión de roll: primera sesión hábil con fecha >= ``expiry − 8 días``."""
    day = expiry - timedelta(days=8)
    while not is_trading_day(day):
        day += timedelta(days=1)
    return day


def parse_definitions(records: Iterable[dict[str, Any]]) -> dict[str, Definition]:
    """Selecciona exactamente los 24 contratos del protocolo."""
    expected = set(EXPECTED_CODES)
    found: dict[str, Definition] = {}
    for record in records:
        raw = _definition_symbol(record)
        match = CONTRACT_RE.fullmatch(raw)
        if not match:
            # Las definiciones incluyen spreads y otros productos; se ignoran.
            continue
        root = match.group("root")
        if root not in ROOTS:
            continue
        month = MONTH_CODES[match.group("month")]
        year_digits = match.group("year")
        # Databento usa un dígito para la década actual (NQH5 = 2025) y el
        # proyecto exige dos en el CSV (NQH25). Los contratos del protocolo
        # están todos en 2025-2026.
        year = 2020 + int(year_digits) if len(year_digits) == 1 else 2000 + int(year_digits)
        code = f"{root}{CODE_MONTHS[month]}{year % 100:02d}"
        if code not in expected:
            continue
        if "expiration" not in record:
            raise ValueError(f"{code}: la definición no trae expiration")
        expiry = _as_date(record.get("expiration"))
        if (expiry.year, expiry.month) != (year, month):
            raise ValueError(
                f"{code}: expiration {expiry.isoformat()} no corresponde al mes del contrato"
            )
        instrument_id = record.get("instrument_id")
        try:
            instrument_id = int(instrument_id) if instrument_id is not None else None
        except (TypeError, ValueError):
            instrument_id = None
        existing = found.get(code)
        if existing is not None:
            if existing.expiry != expiry:
                raise ValueError(
                    f"{code}: dos vencimientos distintos "
                    f"({existing.expiry.isoformat()} y {expiry.isoformat()})"
                )
            continue
        found[code] = Definition(
            root=root,
            raw_symbol=raw,
            code=code,
            expiry=expiry,
            instrument_id=instrument_id,
        )
    missing = [code for code in EXPECTED_CODES if code not in found]
    if missing:
        raise ValueError(
            "Faltan definiciones para los contratos del protocolo: " + ", ".join(missing)
        )
    return {code: found[code] for code in EXPECTED_CODES}


def roll_dates_for_window(
    definitions: dict[str, Definition], start: date, end: date
) -> dict[str, list[date]]:
    """Sesiones de roll por raíz dentro de la ventana solicitada."""
    result: dict[str, list[date]] = {}
    for root in ROOTS:
        dates = sorted(
            {
                definition.roll_date
                for definition in definitions.values()
                if definition.root == root and start <= definition.roll_date <= end
            }
        )
        result[root] = dates
    baseline = result[ROOTS[0]]
    for root in ROOTS[1:]:
        if result[root] != baseline:
            raise ValueError(
                f"Los rolls de {root} no coinciden con {ROOTS[0]}: "
                f"{[d.isoformat() for d in result[root]]} != {[d.isoformat() for d in baseline]}"
            )
    return result


def active_definition(
    definitions: dict[str, Definition], root: str, day: date
) -> Definition:
    """Contrato activo: el saliente en la sesión de roll; el entrante después.

    La sesión de roll es la última del contrato saliente. Se conserva ese
    contrato para que la sesión excluida tenga la cobertura real del contrato
    líquido; el entrante empieza la sesión siguiente.
    """
    candidates = sorted(
        (definition for definition in definitions.values() if definition.root == root),
        key=lambda definition: (definition.expiry, definition.code),
    )
    for definition in candidates:
        if definition.roll_date >= day:
            return definition
    raise ValueError(f"{day.isoformat()}: no hay contrato activo para {root}")


def expected_sessions(start: date, end: date) -> list[date]:
    sessions: list[date] = []
    day = start
    while day <= end:
        if is_trading_day(day):
            sessions.append(day)
        day += timedelta(days=1)
    return sessions


def _session_end_minute(day: date) -> int:
    return hm_to_minutes(early_close_time(day) or "16:00")


def _hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _normalize_bars(
    records: Iterable[dict[str, Any]],
    definitions: dict[str, Definition],
    start: date,
    end: date,
) -> list[BarRow]:
    by_raw = {definition.raw_symbol.upper(): definition for definition in definitions.values()}
    by_code = {definition.code: definition for definition in definitions.values()}
    by_id = {
        definition.instrument_id: definition
        for definition in definitions.values()
        if definition.instrument_id is not None
    }
    active_cache: dict[tuple[str, date], Definition] = {}
    rows: list[BarRow] = []
    seen: set[tuple[date, str, int]] = set()

    for record in records:
        raw = _definition_symbol(record)
        definition = by_raw.get(raw) or by_code.get(raw)
        if definition is None:
            instrument_id = record.get("instrument_id")
            try:
                definition = by_id.get(int(instrument_id)) if instrument_id is not None else None
            except (TypeError, ValueError):
                definition = None
        if definition is None:
            raise ValueError(f"Vela de un contrato no declarado: {raw or record.get('instrument_id')!r}")

        ts_raw = record.get("ts_event")
        if ts_raw is None:
            ts_raw = record.get("timestamp")
        if ts_raw is None:
            raise ValueError(f"{definition.code}: vela sin ts_event")
        ts = _as_epoch(ts_raw)
        day = et_date(ts)
        if day < start or day > end:
            continue
        if not is_trading_day(day):
            continue
        minute = et_minutes(ts)
        if not SESSION_START_MINUTE <= minute < _session_end_minute(day):
            continue

        root = definition.root
        key = (root, day)
        active = active_cache.get(key)
        if active is None:
            active = active_definition(definitions, root, day)
            active_cache[key] = active
        if definition.code != active.code:
            continue

        values = {
            field: _as_float(record.get(field), field, ts, root)
            for field in ("open", "high", "low", "close")
        }
        volume = _as_float(record.get("volume", 0), "volume", ts, root)
        if volume < 0:
            raise ValueError(f"{root} {local_dt(ts):%Y-%m-%d %H:%M}: volumen negativo")
        if min(values.values()) <= 0:
            raise ValueError(f"{root} {local_dt(ts):%Y-%m-%d %H:%M}: precios no positivos")
        if values["high"] < max(values["open"], values["close"]) or values["low"] > min(
            values["open"], values["close"]
        ):
            raise ValueError(f"{root} {local_dt(ts):%Y-%m-%d %H:%M}: OHLC incoherente")

        duplicate_key = (day, root, ts)
        if duplicate_key in seen:
            raise ValueError(
                f"{root} {local_dt(ts):%Y-%m-%d %H:%M}: timestamp duplicado "
                f"({definition.code})"
            )
        seen.add(duplicate_key)
        rows.append(
            BarRow(
                ts=ts,
                day=day,
                symbol=root,
                open=values["open"],
                high=values["high"],
                low=values["low"],
                close=values["close"],
                volume=volume,
                contract=definition.code,
                expiry=definition.expiry,
            )
        )
    rows.sort(key=lambda row: (row.ts, ROOTS.index(row.symbol)))
    return rows


def _fill_session(
    bars: list[BarRow], day: date, root: str
) -> tuple[list[BarRow], list[FillRow]]:
    """Rellena solo minutos aislados; dos ausentes consecutivos son un error."""
    if not bars:
        raise ValueError(f"{day.isoformat()} {root}: sesión sin velas")
    by_minute = {et_minutes(bar.ts): bar for bar in bars}
    expected_minutes = range(SESSION_START_MINUTE, _session_end_minute(day))
    unexpected = sorted(set(by_minute) - set(expected_minutes))
    if unexpected:
        raise ValueError(f"{day.isoformat()} {root}: velas fuera de la ventana operativa")

    missing = [minute for minute in expected_minutes if minute not in by_minute]
    groups: list[list[int]] = []
    for minute in missing:
        if groups and minute == groups[-1][-1] + 1:
            groups[-1].append(minute)
        else:
            groups.append([minute])
    for group in groups:
        if len(group) > 1:
            raise ValueError(
                f"{day.isoformat()} {root}: {len(group)} minutos consecutivos sin "
                f"operaciones ({_hhmm(group[0])} -> {_hhmm(group[-1] + 1)}); "
                "el protocolo solo permite rellenar minutos aislados"
            )

    fills: list[FillRow] = []
    for minute in missing:
        previous = by_minute.get(minute - 1)
        if previous is None:
            raise ValueError(
                f"{day.isoformat()} {root}: falta el primer minuto de la sesión y no "
                "hay cierre anterior para rellenarlo"
            )
        filled = BarRow(
            ts=timestamp_for(day, f"{minute // 60:02d}:{minute % 60:02d}"),
            day=day,
            symbol=root,
            open=previous.close,
            high=previous.close,
            low=previous.close,
            close=previous.close,
            volume=0.0,
            contract=previous.contract,
            expiry=previous.expiry,
        )
        by_minute[minute] = filled
        fills.append(
            FillRow(
                ts=filled.ts,
                symbol=root,
                contract=filled.contract,
                expiry=filled.expiry,
                previous_close=previous.close,
            )
        )
    return [by_minute[minute] for minute in expected_minutes], fills


def convert(
    definition_records: Iterable[dict[str, Any]],
    bar_records: Iterable[dict[str, Any]],
    start: date,
    end: date,
    *,
    dates: Sequence[date] | None = None,
) -> ConversionResult:
    """Normaliza, valida cobertura y rellena una descarga ya obtenida.

    Con ``dates`` solo exige esas sesiones, no todas las del calendario entre
    ``start`` y ``end``: es el modo del piloto, que no cubre la ventana entera.
    """
    if start > end:
        raise ValueError("start no puede ser posterior a end")
    definitions = parse_definitions(definition_records)
    rolls = roll_dates_for_window(definitions, start, end)
    rows = _normalize_bars(bar_records, definitions, start, end)

    grouped: dict[tuple[date, str], list[BarRow]] = {}
    for row in rows:
        grouped.setdefault((row.day, row.symbol), []).append(row)

    expected = list(dict.fromkeys(dates)) if dates is not None else expected_sessions(start, end)
    actual_days = sorted({row.day for row in rows})
    missing_sessions = [day for day in expected if day not in set(actual_days)]
    if missing_sessions:
        preview = ", ".join(day.isoformat() for day in missing_sessions[:5])
        raise ValueError(
            f"Faltan {len(missing_sessions)} sesiones completas en la descarga: {preview}"
        )

    converted: list[BarRow] = []
    fills: list[FillRow] = []
    for day in actual_days:
        for root in ROOTS:
            session_bars = grouped.get((day, root), [])
            if not session_bars:
                raise ValueError(f"{day.isoformat()}: falta la serie {root}")
            filled, session_fills = _fill_session(session_bars, day, root)
            converted.extend(filled)
            fills.extend(session_fills)

    converted.sort(key=lambda row: (row.ts, ROOTS.index(row.symbol)))
    fills.sort(key=lambda fill: (fill.ts, ROOTS.index(fill.symbol)))
    if len(fills) > MAX_FLAT_FILLED_BARS:
        raise ValueError(
            f"La descarga necesita {len(fills)} barras planas y el protocolo admite "
            f"como máximo {MAX_FLAT_FILLED_BARS} (D6); no se escribe un CSV inválido"
        )
    expected_minutes = len(converted)
    summary = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "expected_sessions": len(expected),
        "session_count": len(actual_days),
        "first_session": actual_days[0].isoformat() if actual_days else None,
        "last_session": actual_days[-1].isoformat() if actual_days else None,
        "rows": len(converted),
        "fills": len(fills),
        "fill_share": round(len(fills) / expected_minutes, 6) if expected_minutes else 0.0,
        "max_flat_filled_bars": MAX_FLAT_FILLED_BARS,
        "contracts": [
            {
                "code": definition.code,
                "raw_symbol": definition.raw_symbol,
                "expiry": definition.expiry.isoformat(),
                "roll": definition.roll_date.isoformat(),
            }
            for definition in sorted(
                definitions.values(), key=lambda item: (ROOTS.index(item.root), item.expiry)
            )
        ],
        "rolls": {
            root: [day.isoformat() for day in rolls[root]]
            for root in ROOTS
        },
    }
    return ConversionResult(
        rows=converted,
        fills=fills,
        definitions=definitions,
        summary=summary,
    )


def _fmt_number(value: float) -> str:
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def _fmt_timestamp(ts: int) -> str:
    return local_dt(ts).isoformat(timespec="seconds")


def write_csv(path: Path, rows: Sequence[BarRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "contract",
        "expiry",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "timestamp": _fmt_timestamp(row.ts),
                    "symbol": row.symbol,
                    "open": _fmt_number(row.open),
                    "high": _fmt_number(row.high),
                    "low": _fmt_number(row.low),
                    "close": _fmt_number(row.close),
                    "volume": _fmt_number(row.volume),
                    "contract": row.contract,
                    "expiry": row.expiry.isoformat(),
                }
            )


def write_fills(path: Path, fills: Sequence[FillRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["timestamp", "symbol", "contract", "expiry", "previous_close"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for fill in fills:
            writer.writerow(
                {
                    "timestamp": _fmt_timestamp(fill.ts),
                    "symbol": fill.symbol,
                    "contract": fill.contract,
                    "expiry": fill.expiry.isoformat(),
                    "previous_close": _fmt_number(fill.previous_close),
                }
            )


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "definitions" not in data or "bars" not in data:
        raise ValueError("El fixture debe tener las claves 'definitions' y 'bars'")
    return data


def _import_databento() -> Any:
    try:
        import databento as db
    except ImportError as exc:
        raise SystemExit(
            "Falta el paquete databento. Instala con "
            "`python -m pip install 'databento>=0.40,<1.0'`."
        ) from exc
    return db


_CHECK_HISTORICAL_ACCESS = (
    'python -c "import os, databento as db; '
    "print(db.Historical(os.environ['{env}']).metadata.list_datasets())"
    '"'
)


def explain_databento_error(exc: BaseException, api_key_env: str) -> str | None:
    """Traduce un error HTTP de credenciales a una indicación accionable.

    Devuelve ``None`` para cualquier otro error, de modo que el llamante lo deje
    pasar sin taparlo.
    """
    status = getattr(exc, "http_status", None)
    if status == 401:
        return (
            f"Databento rechazó la clave (401): no es válida. Revisa que "
            f"{api_key_env} contenga la clave completa, 32 caracteres que empiezan "
            "por db-, sin comillas ni espacios."
        )
    if status == 402:
        return (
            "Databento rechazó la descarga (402, pago): la cuenta tiene un problema "
            "de facturación. Revisa en el portal el método de pago y el saldo de "
            "crédito antes de reintentar."
        )
    if status == 403:
        return (
            "Databento rechazó la descarga (403): la clave autentica, pero no tiene "
            "permisos de histórico (una clave inválida daría 401). Comprueba el "
            "acceso con\n"
            f"  {_CHECK_HISTORICAL_ACCESS.format(env=api_key_env)}\n"
            "y revisa en el portal, en API keys, que la clave tenga datos históricos "
            "habilitados y que la cuenta pueda consultar el dataset; si ese comando "
            "también da 403, crea una clave nueva."
        )
    return None


def _request_start(value: date) -> str:
    return f"{value.isoformat()}T00:00:00Z"


def _request_end(value: date) -> str:
    return f"{(value + timedelta(days=1)).isoformat()}T00:00:00Z"


def _is_transient_error(error: BaseException) -> bool:
    """¿Es un fallo de red que merece reintento?

    Los 429 y 5xx llegan como ``BentoServerError`` con ``http_status``. Un
    corte a mitad del stream (``Response ended prematurely``) lo envuelve
    Databento en el ``BentoError`` base, sin estado HTTP; ahí también entran
    los fallos de conexión de ``requests``, que son ``OSError``. Los 4xx
    (clave, permisos, simbología) y los errores de programación no se repiten.
    """
    status = getattr(error, "http_status", None)
    if status is not None:
        return status in TRANSIENT_STATUSES
    if isinstance(error, OSError):
        return True
    try:
        from databento.common.error import BentoError
    except ImportError:
        return False
    return type(error) is BentoError


def _get_range(client: Any, **kwargs: Any) -> Any:
    """``timeseries.get_range`` reintentando solo fallos transitorios.

    El 504 del gateway de Databento y los cortes de stream aparecen de forma
    intermitente en ventanas grandes; reintentar con espera evita abortar una
    descarga de 10 sesiones por un corte puntual.
    """
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            return client.timeseries.get_range(**kwargs)
        except Exception as error:  # noqa: BLE001 - se rellanza sin tocar
            if not _is_transient_error(error) or attempt == DOWNLOAD_ATTEMPTS:
                raise
            status = getattr(error, "http_status", None)
            motivo = f"HTTP {status}" if status is not None else "corte de conexión"
            delay = RETRY_BASE_SECONDS * 2 ** (attempt - 1)
            print(
                f"Databento falló ({motivo}, {kwargs.get('schema')}); "
                f"reintento {attempt}/{DOWNLOAD_ATTEMPTS - 1} en {delay:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
    raise AssertionError("reintentos agotados")


def download_definitions(
    client: Any,
    dataset: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    definition_start = start - timedelta(days=DEFINITION_LEAD_DAYS)
    definition_end = min(end + timedelta(days=DEFINITION_LEAD_DAYS), date.today())
    if definition_end < definition_start:
        definition_end = date.today()
    # Con stype_in="parent" Databento solo admite stype_out="instrument_id"
    # (matriz de simbología); el raw_symbol va en su propia columna.
    data = _get_range(
        client,
        dataset=dataset,
        schema="definition",
        stype_in="parent",
        symbols=[f"{root}.FUT" for root in ROOTS],
        start=_request_start(definition_start),
        end=_request_end(definition_end),
    )
    return _records(data.to_df())


def download_bars(
    client: Any,
    dataset: str,
    definitions: dict[str, Definition],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    # Igual que arriba: raw_symbol como entrada solo admite instrument_id como
    # salida. ``to_df()`` vuelve a mapear cada instrument_id al símbolo pedido.
    data = _get_range(
        client,
        dataset=dataset,
        schema="ohlcv-1m",
        stype_in="raw_symbol",
        symbols=[definition.raw_symbol for definition in definitions.values()],
        start=_request_start(start),
        end=_request_end(end),
    )
    frame = data.to_df()
    # ``to_df()`` deja ``ts_event`` como índice; sin reset_index las velas
    # llegan sin timestamp y la normalización aborta.
    if hasattr(frame, "reset_index"):
        frame = frame.reset_index()
    return _records(frame)


def relative_path(path: Path) -> str:
    """Ruta del CSV relativa al proyecto cuando sea posible."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def activate_dataset(path: Path) -> None:
    """Deja la configuración apuntando al CSV validado, sin arrancar el motor."""
    settings = load_settings()
    settings.feed.provider = "csv"
    settings.feed.csv_path = relative_path(path)
    settings.feed.series_mode = "raw"
    settings.feed.exclude_roll_sessions = True
    settings.feed.loop_sessions = False
    settings.feed.start_date = ""
    settings.mode = "paper"
    settings.live.live_enabled = False
    settings.live.live_confirmation = ""
    save_settings(settings)


def _parse_dates(value: str) -> list[date]:
    """``2025-01-16,2025-06-12`` -> sesiones ordenadas y sin repetir."""
    dates: list[date] = []
    for item in value.split(","):
        text = item.strip()
        if not text:
            continue
        try:
            day = date.fromisoformat(text)
        except ValueError:
            raise ValueError(f"Fecha inválida en --dates: {text!r} (usa YYYY-MM-DD)") from None
        if day not in dates:
            dates.append(day)
    if not dates:
        raise ValueError("--dates no contiene ninguna fecha")
    return sorted(dates)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga Databento y genera el CSV de 1m del protocolo, con "
            "normalización ET y registro de minutos rellenados."
        )
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="JSON local con definitions y bars; no usa red ni credenciales.",
    )
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=None,
        help="Primera fecha ET (por defecto 2025-01-10; el fixture puede fijarla).",
    )
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        default=None,
        help="Última fecha ET (por defecto 2026-06-30; nunca entra en el holdout).",
    )
    parser.add_argument(
        "--dates",
        help=(
            "Sesiones concretas separadas por coma (YYYY-MM-DD). Descarga solo esas, "
            "una petición por sesión, valida cada una por separado y no activa."
        ),
    )
    parser.add_argument("--dataset", default=DATASET)
    parser.add_argument("--api-key-env", default="DATABENTO_API_KEY")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--fills-out",
        type=Path,
        default=None,
        help=(
            "CSV de minutos rellenados. Por defecto, junto al CSV "
            "(<nombre>_fills.csv); con el dataset completo, la ruta canónica."
        ),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help=(
            "Resumen JSON. Por defecto, junto al CSV (<nombre>_summary.json); "
            "con el dataset completo, la ruta canónica."
        ),
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Activa el CSV en data/config.json solo si la validación es correcta.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    dates: list[date] | None = None
    if args.dates:
        if args.fixture is not None:
            parser.error("--dates no se combina con --fixture")
        if args.start or args.end:
            parser.error("--dates ya fija la ventana; no uses --start/--end")
        if args.activate:
            parser.error("Un piloto con --dates no se activa; genera el CSV y revísalo antes.")
        if args.out == DEFAULT_OUT:
            parser.error("Con --dates indica --out con una ruta propia, p. ej. data/real/pilot.csv")
        try:
            dates = _parse_dates(args.dates)
        except ValueError as exc:
            parser.error(str(exc))
        closed = [day for day in dates if not is_trading_day(day)]
        if closed:
            parser.error(
                "No son sesiones de trading: " + ", ".join(day.isoformat() for day in closed)
            )

    if dates is not None:
        # Un piloto no debe escribir en las rutas canónicas del dataset completo.
        if args.fills_out is None:
            args.fills_out = args.out.with_name(f"{args.out.stem}_fills.csv")
        if args.summary is None:
            args.summary = args.out.with_name(f"{args.out.stem}_summary.json")
    else:
        if args.fills_out is None:
            args.fills_out = DEFAULT_FILLS_OUT
        if args.summary is None:
            args.summary = DEFAULT_SUMMARY

    payload = load_fixture(args.fixture) if args.fixture is not None else None
    if dates is not None:
        start, end = dates[0], dates[-1]
    elif payload is not None:
        start = args.start or date.fromisoformat(payload.get("start", DEFAULT_START.isoformat()))
        end = args.end or date.fromisoformat(payload.get("end", DEFAULT_END.isoformat()))
    else:
        start = args.start or DEFAULT_START
        end = args.end or DEFAULT_END
    if start > end:
        parser.error("--start no puede ser posterior a --end")
    if end >= HOLDOUT_START:
        parser.error(
            "La ventana termina dentro del holdout sellado (2026-07-01 -> 2026-10-30). "
            "Usa --end 2026-06-30 para el dataset de desarrollo."
        )

    if payload is not None:
        definition_records = payload["definitions"]
        bar_records = payload["bars"]
        source = f"fixture:{args.fixture}"
    else:
        api_key = os.environ.get(args.api_key_env, "").strip()
        if not api_key:
            raise SystemExit(
                f"Falta {args.api_key_env}. Exporta la clave de Databento o usa "
                "--fixture para probar sin credenciales."
            )
        db = _import_databento()
        try:
            client = db.Historical(api_key)
            definition_records = download_definitions(
                client, args.dataset, start, end
            )
            definitions = parse_definitions(definition_records)
            if dates is not None:
                bar_records = []
                for day in dates:
                    piece = download_bars(client, args.dataset, definitions, day, day)
                    print(f"{day.isoformat()}: {len(piece)} velas", flush=True)
                    bar_records.extend(piece)
            else:
                bar_records = download_bars(
                    client, args.dataset, definitions, start, end
                )
        except Exception as exc:
            message = explain_databento_error(exc, args.api_key_env)
            if message is None:
                raise
            raise SystemExit(message)
        source = f"databento:{args.dataset}"

    result = convert(definition_records, bar_records, start, end, dates=dates)
    summary = dict(result.summary)
    summary.update(
        {
            "source": source,
            "out": str(args.out),
            "fills_out": str(args.fills_out),
            "dataset": args.dataset,
        }
    )
    if dates is not None:
        summary["dates"] = [day.isoformat() for day in dates]
    tmp = args.out.with_name(args.out.name + ".tmp")
    write_csv(tmp, result.rows)
    if dates is None:
        try:
            report = inspect_csv(
                tmp, REQUIRED_SYMBOLS, series_mode="raw", exclude_roll_sessions=True
            )
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        if not report.get("ok"):
            tmp.unlink(missing_ok=True)
            details = "; ".join(report.get("errors") or ["validación fallida"])
            raise SystemExit(f"El CSV no pasó la validación; no se activa. {details}")
    # Con --dates no se llama a inspect_csv: exige todas las sesiones del
    # calendario entre extremos y un piloto no las tiene. La cobertura ya la
    # comprobó convert, sesión completa por sesión y símbolo.
    tmp.replace(args.out)
    write_fills(args.fills_out, result.fills)
    write_summary(args.summary, summary)

    print(
        f"Contratos: {len(result.definitions)} | sesiones: "
        f"{summary['session_count']} | filas: {summary['rows']} | "
        f"rellenos: {summary['fills']} ({summary['fill_share']:.4%})"
    )
    for root in ROOTS:
        dates = summary["rolls"][root]
        print(f"  {root}: rolls {', '.join(dates) if dates else 'ninguno en la ventana'}")
    print(f"CSV: {args.out}")
    print(f"Rellenos: {args.fills_out}")
    print(f"Resumen: {args.summary}")
    if args.activate:
        activate_dataset(args.out)
        print(
            f"Configuración activada en {relative_path(CONFIG_PATH)}; "
            "el motor espera inicio manual."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
