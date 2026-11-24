"""Carga, validación y alineación de CSV históricos reales.

Formato: CSV largo, una fila por símbolo y minuto::

    timestamp,symbol,open,high,low,close,volume[,contract][,expiry]
    2025-06-03T09:30:00-04:00,MNQ,20838.25,20840.00,20836.50,20839.75,1200,MNQZ26,2026-12-18
    2025-06-03T09:30:00-04:00,NQ,20841.00,20842.75,20839.25,20842.50,980,NQZ26,2026-12-18
    2025-06-03T09:30:00-04:00,ES,5730.25,5731.00,5729.75,5730.75,2100,ESZ26,2026-12-18

La columna ``contract`` identifica el contrato real. ``expiry`` es opcional:
si falta se deriva del código del contrato (tercer viernes del mes). El
contrato activo de cada sesión es el de vencimiento más próximo que todavía no
ha vencido; la última sesión del contrato saliente es la sesión de roll y el
cambio al entrante se materializa a la sesión siguiente.

La serie puede entregarse en modo ``raw`` (precios tal como los publica el
proveedor) o ``adjusted`` (el histórico del contrato antiguo se desplaza por el
spread del roll para que la serie sea continua). Las sesiones de roll se
excluyen por defecto del replay y del backtest; la validación de sesión completa
se sigue aplicando a todas las sesiones, incluidas las de roll.

Reglas que aplica el validador:

- ``timestamp`` ISO-8601 con zona horaria (o epoch en segundos) y alineado al minuto.
- Una fila por símbolo, contrato y timestamp; sin duplicados.
- OHLC coherente (``high >= max(open, close)``, ``low <= min(open, close)``).
- MNQ, NQ y ES deben compartir exactamente los mismos timestamps.
- Cada día hábil dentro del rango debe estar completo; una sesión completa ausente
  también invalida el dataset. Los cierres anticipados oficiales de CME para índices
  se validan contra su hora de cierre corta. El premarket no sustituye la ventana RTH.
- Si existe ``contract``, no puede estar vacío y debe corresponder al símbolo.
- Si existe ``expiry``, debe ser ``YYYY-MM-DD`` y no puede ser anterior a una
  vela de ese contrato. Sin ``contract`` no se admite ``expiry``.

El módulo también funciona como CLI::

    python -m server.market.csv_data ruta/al/bars.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from ..models import Bar
from ..timeutil import et_date, local_dt
from .contracts import ContractSpec, parse_contract, parse_expiry, select_active_contract
from .sessions import validate_sessions

DATA_SCHEMA_VERSION = "1.1"
HOLDOUT_START = date(2026, 7, 1)
HOLDOUT_END = date(2026, 10, 30)
REQUIRED_SYMBOLS: tuple[str, ...] = ("MNQ", "NQ", "ES")
REQUIRED_COLUMNS = {"timestamp", "symbol", "open", "high", "low", "close"}
OPTIONAL_COLUMNS = {"volume", "contract", "expiry"}
SERIES_MODES = {"raw", "adjusted"}
MIN_EPOCH = 1_000_000_000  # descarta fechas YYYYMMDD interpretadas como epoch
MAX_EPOCH = 4_102_444_800  # 2100-01-01; por encima es casi seguro epoch en milisegundos


def parse_timestamp(raw: str, line: int) -> int:
    """ISO-8601 con zona horaria o epoch en segundos -> epoch int."""
    value = raw.strip()
    if not value:
        raise ValueError(f"Línea {line}: timestamp vacío")
    try:
        number = float(value)
    except ValueError:
        number = None
    if number is not None:
        if number < MIN_EPOCH:
            raise ValueError(f"Línea {line}: epoch demasiado pequeño; usa segundos (no milisegundos ni YYYYMMDD)")
        if number >= MAX_EPOCH:
            raise ValueError(f"Línea {line}: epoch fuera de rango; usa segundos, no milisegundos")
        ts = int(number)
    else:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(f"Línea {line}: timestamp inválido {value!r}") from None
        if dt.tzinfo is None:
            raise ValueError(
                f"Línea {line}: timestamp sin zona horaria ({value!r}); usa ISO-8601 con offset o epoch"
            )
        ts = int(dt.timestamp())
    if ts % 60:
        raise ValueError(f"Línea {line}: timestamp no alineado al minuto ({value})")
    return ts


def _number(raw: str, field: str, line: int) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"Línea {line}: {field} no numérico ({raw!r})") from None
    if not math.isfinite(value):
        raise ValueError(f"Línea {line}: {field} no finito")
    return value


@dataclass(slots=True)
class CsvRows:
    """Filas crudas validadas, con contratos declarados si existen."""

    bars: dict[str, list[Bar]]
    contracts: dict[str, list[str]]
    bar_contracts: dict[str, dict[int, str]]
    contract_bars: dict[str, dict[str, list[Bar]]]
    contract_specs: dict[str, ContractSpec]
    contract_expiries: dict[str, str]
    columns: list[str]
    row_count: int
    expiry_column: bool


@dataclass(slots=True)
class ContractSelection:
    """Resultado de seleccionar el contrato activo y construir la serie."""

    rows: dict[str, list[Bar]]
    contracts_by_session: dict[str, dict[str, str]]
    expiry_by_session: dict[str, dict[str, str]]
    roll_events: list[dict[str, Any]]
    roll_sessions: list[str]
    excluded_sessions: list[str]
    adjustments: dict[str, dict[str, float]]
    series_mode: str
    exclude_roll_sessions: bool
    errors: list[str]
    warnings: list[str]


def _read_csv(path: Path) -> CsvRows:
    """Lee y valida el CSV. Lanza ``ValueError`` con la línea del primer error."""
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró el CSV {path}. Exporta velas de 1m con columnas "
            "timestamp,symbol,open,high,low,close[,volume][,contract][,expiry]."
        )
    out: dict[str, list[Bar]] = {}
    seen: set[tuple[str, str, int]] = set()
    contracts: dict[str, set[str]] = {}
    bar_contracts: dict[str, dict[int, str]] = {}
    contract_bars: dict[str, dict[str, list[Bar]]] = {}
    contract_specs: dict[str, ContractSpec] = {}
    contract_expiries: dict[str, str] = {}
    columns: list[str] = []
    row_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = [(f or "").strip().lower() for f in (reader.fieldnames or [])]
        fields = set(columns)
        missing = REQUIRED_COLUMNS - fields
        if missing:
            raise ValueError(
                "Faltan columnas requeridas: " + ", ".join(sorted(missing))
                + " (formato: timestamp,symbol,open,high,low,close,volume[,contract][,expiry])"
            )
        contract_column = "contract" in fields
        expiry_column = "expiry" in fields
        if expiry_column and not contract_column:
            raise ValueError("La columna expiry requiere la columna contract")
        for line, raw_row in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
            symbol = row.get("symbol", "").upper()
            if not symbol:
                raise ValueError(f"Línea {line}: symbol vacío")
            contract = row.get("contract", "").upper()
            expiry_raw = row.get("expiry", "").strip()
            if contract_column and not contract:
                raise ValueError(f"Línea {line}: contract vacío")
            if expiry_column and expiry_raw and not contract:
                raise ValueError(f"Línea {line}: expiry requiere la columna contract")
            spec: ContractSpec | None = None
            if contract:
                try:
                    spec = parse_contract(contract, symbol)
                except ValueError as exc:
                    raise ValueError(f"Línea {line}: {exc}") from None
                if expiry_raw:
                    try:
                        spec = spec.with_expiry(parse_expiry(expiry_raw))
                    except ValueError as exc:
                        raise ValueError(f"Línea {line}: {exc}") from None
                ts = parse_timestamp(row.get("timestamp", ""), line)
                if spec.expiry < et_date(ts):
                    raise ValueError(
                        f"Línea {line}: contrato {contract} vencido el {spec.expiry.isoformat()} "
                        f"para una vela del {local_dt(ts):%Y-%m-%d}"
                    )
                known = contract_specs.get(contract)
                if known is not None and known.expiry != spec.expiry:
                    raise ValueError(
                        f"Línea {line}: el contrato {contract} tiene dos vencimientos distintos "
                        f"({known.expiry.isoformat()} y {spec.expiry.isoformat()})"
                    )
                contract_specs[contract] = spec
                contract_expiries[contract] = spec.expiry.isoformat()
            else:
                ts = parse_timestamp(row.get("timestamp", ""), line)
            values = {name: _number(row.get(name, ""), name, line) for name in ("open", "high", "low", "close")}
            volume = _number(row.get("volume") or "0", "volume", line)
            if volume < 0:
                raise ValueError(f"Línea {line}: volumen negativo")
            if min(values.values()) <= 0:
                raise ValueError(f"Línea {line}: precios deben ser positivos")
            if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"], values["close"]):
                raise ValueError(f"Línea {line}: OHLC incoherente para {symbol} en {local_dt(ts):%Y-%m-%d %H:%M}")
            duplicate_key = (symbol, contract, ts)
            if duplicate_key in seen:
                suffix = f" (contrato {contract})" if contract else ""
                raise ValueError(
                    f"Línea {line}: timestamp duplicado para {symbol}{suffix} en {local_dt(ts):%Y-%m-%d %H:%M}"
                )
            seen.add(duplicate_key)
            bar = Bar(
                ts=ts,
                open=values["open"],
                high=values["high"],
                low=values["low"],
                close=values["close"],
                volume=volume,
            )
            out.setdefault(symbol, []).append(bar)
            contract_key = contract or ""
            contract_bars.setdefault(symbol, {}).setdefault(contract_key, []).append(bar)
            if contract:
                contracts.setdefault(symbol, set()).add(contract)
                bar_contracts.setdefault(symbol, {}).setdefault(ts, contract)
            row_count += 1

    if not out:
        raise ValueError("El CSV no contiene filas")
    for bars in out.values():
        bars.sort(key=lambda b: b.ts)
    for symbol_contracts in contract_bars.values():
        for bars in symbol_contracts.values():
            bars.sort(key=lambda b: b.ts)
    return CsvRows(
        bars=out,
        contracts={s: sorted(v) for s, v in contracts.items()},
        bar_contracts=bar_contracts,
        contract_bars=contract_bars,
        contract_specs=contract_specs,
        contract_expiries=contract_expiries,
        columns=columns,
        row_count=row_count,
        expiry_column=expiry_column,
    )


def holdout_sessions(days: Iterable[date | str]) -> list[date]:
    """Sesiones que caen en el holdout sellado, ordenadas y sin duplicados."""
    values: list[date] = []
    for day in days:
        value = day if isinstance(day, date) else date.fromisoformat(str(day))
        if value >= HOLDOUT_START:
            values.append(value)
    return sorted(set(values))


def refuse_holdout_sessions(days: Iterable[date | str]) -> None:
    """Rechaza cualquier lista de sesiones que incluya el holdout sellado."""
    leaked = holdout_sessions(days)
    if not leaked:
        return
    development_end = HOLDOUT_START - timedelta(days=1)
    raise ValueError(
        f"CSV bloqueado: contiene {len(leaked)} sesión(es) desde "
        f"{leaked[0].isoformat()}, fuera de la ventana de desarrollo (hasta "
        f"{development_end.isoformat()}). El holdout sellado "
        f"({HOLDOUT_START.isoformat()} → {HOLDOUT_END.isoformat()}) se ejecuta "
        "una sola vez con el comando confirmatorio."
    )


def _refuse_holdout(bars: dict[str, list[Bar]]) -> None:
    """Bloquea cualquier carga que incluya velas del holdout sellado.

    El replay y el backtest solo pueden consumir datos de desarrollo. La única
    excepción es el comando confirmatorio, que carga el dataset completo con
    ``allow_holdout=True`` y ejecuta el holdout una sola vez.
    """
    refuse_holdout_sessions(et_date(bar.ts) for rows in bars.values() for bar in rows)


def load_bars(path: Path) -> dict[str, list[Bar]]:
    """Compatibilidad: devuelve las barras crudas validadas."""
    data = _read_csv(path)
    _refuse_holdout(data.bars)
    return data.bars


def _fmt(ts: int | None) -> str | None:
    if ts is None:
        return None
    return local_dt(ts).strftime("%Y-%m-%d %H:%M")


def align_bars(rows: dict[str, list[Bar]], symbols: Iterable[str] = REQUIRED_SYMBOLS) -> tuple[list[dict[str, Bar]], dict[str, Any]]:
    """Intersección exacta de timestamps y diagnóstico de alineación.

    Devuelve las velas sincronizadas (una entrada por minuto) y un informe
    serializable. No lanza por desalineación: el llamador decide si es fatal.
    """
    wanted = list(symbols)
    counts = {s: len(rows.get(s, [])) for s in wanted}
    errors: list[str] = []
    warnings: list[str] = []
    missing_symbols = [s for s in wanted if not rows.get(s)]
    for symbol in missing_symbols:
        errors.append(f"Falta la serie {symbol} en el CSV")

    # En un CSV con contratos puede haber dos filas para el mismo minuto; la
    # selección de contrato activo ya deja una sola por símbolo y minuto.
    maps: dict[str, dict[int, Bar]] = {}
    for symbol in wanted:
        symbol_map: dict[int, Bar] = {}
        for bar in rows.get(symbol, []):
            if bar.ts in symbol_map:
                errors.append(f"Timestamp duplicado para {symbol} en {_fmt(bar.ts)}")
            symbol_map[bar.ts] = bar
        maps[symbol] = symbol_map
    sets = [set(maps[s]) for s in wanted]
    union: set[int] = set().union(*sets) if sets else set()
    common: set[int] = set.intersection(*sets) if wanted else set()
    missing = {s: len(union - set(maps[s])) for s in wanted}
    aligned = not any(missing.values()) and bool(common)
    first_mismatch = sorted(union - common)[:5]

    if not aligned and not missing_symbols:
        detail = ", ".join(f"{s} sin {missing[s]}" for s in wanted if missing[s])
        errors.append(f"Timestamps desalineados entre series ({detail})")
    if common and len(common) < 2:
        errors.append("Se necesitan al menos 2 velas comunes para operar/backtestear")
    if not common:
        errors.append("No hay velas comunes entre las series")

    stamps = sorted(common)
    bars = [{s: maps[s][ts] for s in wanted} for ts in stamps] if not missing_symbols else []

    gap_seconds = [b - a for a, b in zip(stamps, stamps[1:]) if b - a > 60]
    intraday = [g for g in gap_seconds if 120 <= g <= 240 * 60]
    if gap_seconds:
        warnings.append(
            f"{len(gap_seconds)} huecos entre velas comunes (máx {max(gap_seconds) // 60} min); "
            "incluyen cierres de sesión: revisa que no falten minutos dentro del horario operado."
        )
    if intraday:
        warnings.append(f"{len(intraday)} huecos de 2–240 min que podrían ser velas ausentes")

    report: dict[str, Any] = {
        "ok": bool(common) and aligned and not errors,
        "symbols": wanted,
        "counts": counts,
        "common_bars": len(stamps),
        "aligned": aligned,
        "missing": missing,
        "first_mismatch": [_fmt(ts) for ts in first_mismatch],
        "first_ts": stamps[0] if stamps else None,
        "last_ts": stamps[-1] if stamps else None,
        "first_et": _fmt(stamps[0]) if stamps else None,
        "last_et": _fmt(stamps[-1]) if stamps else None,
        "gap_count": len(gap_seconds),
        "max_gap_seconds": max(gap_seconds) if gap_seconds else 0,
        "errors": errors,
        "warnings": warnings,
    }
    return bars, report


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload(data: CsvRows) -> dict[str, Any]:
    """Identidad estable del contenido lógico, independiente de ruta/formato."""
    symbols = sorted(data.bars)
    bars: list[dict[str, Any]] = []
    if data.contract_specs:
        # Incluye todos los contratos fuente, no solo la serie seleccionada.
        for symbol in symbols:
            contract_rows = data.contract_bars.get(symbol, {})
            has_overlap = len({bar.ts for bar in data.bars[symbol]}) != len(data.bars[symbol])
            if has_overlap:
                sources = [(code, rows) for code, rows in sorted(contract_rows.items())]
            else:
                # Orden y forma históricos: una fila por timestamp, con el
                # contrato asociado. Mantiene el dataset_id de CSV antiguos.
                sources = [("", data.bars[symbol])]
            for code, rows in sources:
                for bar in sorted(rows, key=lambda b: b.ts):
                    contract = code or data.bar_contracts.get(symbol, {}).get(bar.ts)
                    item = {
                        "symbol": symbol,
                        "ts": bar.ts,
                        "contract": contract or None,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
                    # El vencimiento derivado no altera el hash de los CSV que
                    # solo tenían `contract`.
                    if data.expiry_column:
                        item["expiry"] = data.contract_expiries.get(contract or "")
                    bars.append(item)
    else:
        for symbol in symbols:
            for bar in sorted(data.bars[symbol], key=lambda b: b.ts):
                bars.append(
                    {
                        "symbol": symbol,
                        "ts": bar.ts,
                        "contract": None,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
                )
    return {
        "schema_version": DATA_SCHEMA_VERSION,
        "canonicalization": "rows-v1",
        "symbols": symbols,
        "bars": bars,
    }


def dataset_identity(data: CsvRows) -> str:
    encoded = json.dumps(
        _canonical_payload(data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def series_identity(bars: list[dict[str, Bar]], mode: str) -> str:
    """Identidad de la serie efectiva (raw o ajustada) tras excluir rolls."""
    reference = "NQ" if bars and "NQ" in bars[0] else (next(iter(bars[0])) if bars else None)
    payload = {
        "schema_version": DATA_SCHEMA_VERSION,
        "canonicalization": "series-v1",
        "mode": mode,
        "bars": [
            {
                "ts": tick[reference].ts if reference else None,
                "prices": {
                    symbol: [bar.open, bar.high, bar.low, bar.close, bar.volume]
                    for symbol, bar in sorted(tick.items())
                },
            }
            for tick in bars
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contract_offset(
    data: CsvRows,
    symbol: str,
    from_contract: str,
    to_contract: str,
    roll_day: date,
) -> tuple[float, str]:
    """Spread de roll para un símbolo.

    Prioriza el último precio solapado de ambos contratos. Si el CSV no trae
    ambos contratos en el mismo minuto, usa la apertura del primer contrato
    nuevo menos el cierre del último contrato antiguo.
    """
    old = data.contract_bars.get(symbol, {}).get(from_contract, [])
    new = data.contract_bars.get(symbol, {}).get(to_contract, [])
    if not old or not new:
        return 0.0, "unavailable"
    old_map = {bar.ts: bar for bar in old}
    shared = sorted(set(old_map) & {bar.ts for bar in new})
    if shared:
        ts = shared[-1]
        new_map = {bar.ts: bar for bar in new}
        return round(new_map[ts].close - old_map[ts].close, 4), "overlap"
    old_before = [bar for bar in old if et_date(bar.ts) <= roll_day]
    new_after = [bar for bar in new if et_date(bar.ts) >= roll_day]
    if old_before and new_after:
        return round(new_after[0].open - old_before[-1].close, 4), "boundary"
    return 0.0, "unavailable"


def _select_contract_rows(
    data: CsvRows,
    wanted: list[str],
) -> ContractSelection:
    """Selecciona una fila por símbolo/minuto y calcula el plan de rolls."""
    if not data.contract_specs:
        rows = {symbol: list(data.bars.get(symbol, [])) for symbol in wanted}
        return ContractSelection(
            rows=rows,
            contracts_by_session={},
            expiry_by_session={},
            roll_events=[],
            roll_sessions=[],
            excluded_sessions=[],
            adjustments={},
            series_mode="",
            exclude_roll_sessions=False,
            errors=[],
            warnings=[],
        )

    by_day: dict[str, dict[date, dict[str, list[Bar]]]] = {}
    for symbol in wanted:
        for code, contract_rows in data.contract_bars.get(symbol, {}).items():
            for bar in contract_rows:
                by_day.setdefault(symbol, {}).setdefault(et_date(bar.ts), {}).setdefault(code, []).append(bar)

    all_days = sorted(
        {
            day
            for symbol_days in by_day.values()
            for day in symbol_days
        }
    )
    rows: dict[str, list[Bar]] = {symbol: [] for symbol in wanted}
    contracts_by_session: dict[str, dict[str, str]] = {}
    expiry_by_session: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    warnings: list[str] = []
    previous: dict[str, str] = {}
    previous_day: dict[str, date] = {}
    switches: dict[date, dict[str, dict[str, Any]]] = {}

    for day in all_days:
        for symbol in wanted:
            candidates = by_day.get(symbol, {}).get(day, {})
            specs = [data.contract_specs[code] for code in candidates if code in data.contract_specs]
            active = select_active_contract(specs, day)
            if active is None:
                if candidates:
                    expired = ", ".join(sorted(candidates))
                    errors.append(
                        f"Sesión {day.isoformat()}: sin contrato activo para {symbol} "
                        f"(contratos vencidos: {expired})"
                    )
                continue
            contracts_by_session.setdefault(day.isoformat(), {})[symbol] = active.code
            expiry_by_session.setdefault(day.isoformat(), {})[symbol] = active.expiry.isoformat()
            selected_bars = candidates.get(active.code, [])
            rows.setdefault(symbol, []).extend(selected_bars)
            old_code = previous.get(symbol)
            if old_code and old_code != active.code:
                switches.setdefault(day, {})[symbol] = {
                    "from": old_code,
                    "to": active.code,
                    "roll_date": previous_day[symbol].isoformat() if symbol in previous_day else None,
                }
            previous[symbol] = active.code
            previous_day[symbol] = day

    roll_events: list[dict[str, Any]] = []
    for day in sorted(switches):
        per_symbol = switches[day]
        roll_dates = {change.get("roll_date") for change in per_symbol.values()}
        if len(roll_dates) != 1 or None in roll_dates:
            detail = ", ".join(
                f"{symbol}: {change.get('roll_date') or 'sin sesión previa'}"
                for symbol, change in sorted(per_symbol.items())
            )
            errors.append(f"Roll no sincronizado el {day.isoformat()} ({detail})")
            continue
        roll_day = next(iter(roll_dates))
        offsets: dict[str, float] = {}
        methods: dict[str, str] = {}
        for symbol, change in per_symbol.items():
            offset, method = _contract_offset(data, symbol, change["from"], change["to"], day)
            offsets[symbol] = offset
            methods[symbol] = method
            if method == "unavailable":
                warnings.append(
                    f"No se pudo calcular el spread de roll {symbol} "
                    f"{change['from']}→{change['to']} el {day.isoformat()}"
                )
        # La estrategia calcula niveles en NQ y ejecuta en MNQ. Para que ambos
        # compartan la misma base, el par NQ/MNQ usa un unico offset por roll:
        # el del instrumento de ejecucion (MNQ). ES conserva su offset porque
        # el SMT compara pivotes dentro de cada instrumento y un desplazamiento
        # constante no altera la divergencia.
        basis_symbol = next(
            (
                candidate
                for candidate in ("MNQ", "NQ")
                if candidate in per_symbol and methods.get(candidate) != "unavailable"
            ),
            None,
        )
        basis_offset = offsets.get(basis_symbol, 0.0) if basis_symbol else None
        applied_offsets = {
            symbol: (
                basis_offset
                if basis_symbol and symbol in {"NQ", "MNQ"}
                else offsets.get(symbol, 0.0)
            )
            for symbol in per_symbol
        }
        basis_residual = {
            symbol: round(offsets.get(symbol, 0.0) - applied_offsets[symbol], 4)
            for symbol in per_symbol
        }
        roll_events.append(
            {
                "date": roll_day,
                "switch_date": day.isoformat(),
                "from": {symbol: change["from"] for symbol, change in per_symbol.items()},
                "to": {symbol: change["to"] for symbol, change in per_symbol.items()},
                "offsets": offsets,
                "applied_offsets": applied_offsets,
                "basis_symbol": basis_symbol,
                "basis_residual": basis_residual,
                "methods": methods,
                "excluded": True,
            }
        )

    adjustments: dict[str, dict[str, float]] = {}
    for symbol in wanted:
        symbol_events = [
            {
                "date": date.fromisoformat(event["date"]),
                "from": event["from"][symbol],
                "offset": event["applied_offsets"].get(
                    symbol, event["offsets"].get(symbol, 0.0)
                ),
            }
            for event in roll_events
            if symbol in event["from"]
        ]
        cumulative = 0.0
        by_contract: dict[str, float] = {}
        for event in reversed(symbol_events):
            cumulative += event["offset"]
            by_contract[event["from"]] = round(cumulative, 4)
        adjustments[symbol] = by_contract

    if not data.expiry_column:
        warnings.append("expiry no declarado: se deriva el tercer viernes del mes del contrato")
    if roll_events:
        warnings.append(
            f"{len(roll_events)} sesión(es) de roll detectada(s); "
            "se excluyen del replay y del backtest por defecto"
        )

    return ContractSelection(
        rows=rows,
        contracts_by_session=contracts_by_session,
        expiry_by_session=expiry_by_session,
        roll_events=roll_events,
        roll_sessions=[event["date"] for event in roll_events],
        excluded_sessions=[],
        adjustments=adjustments,
        series_mode="",
        exclude_roll_sessions=False,
        errors=errors,
        warnings=warnings,
    )


def _apply_adjustment(
    bars: list[dict[str, Bar]],
    selection: ContractSelection,
    mode: str,
) -> list[dict[str, Bar]]:
    if mode == "raw":
        return bars
    adjusted: list[dict[str, Bar]] = []
    for tick in bars:
        new_tick: dict[str, Bar] = {}
        for symbol, bar in tick.items():
            day = et_date(bar.ts).isoformat()
            code = selection.contracts_by_session.get(day, {}).get(symbol)
            offset = selection.adjustments.get(symbol, {}).get(code, 0.0) if code else 0.0
            if offset:
                new_tick[symbol] = Bar(
                    ts=bar.ts,
                    open=round(bar.open + offset, 4),
                    high=round(bar.high + offset, 4),
                    low=round(bar.low + offset, 4),
                    close=round(bar.close + offset, 4),
                    volume=bar.volume,
                )
            else:
                new_tick[symbol] = bar
        adjusted.append(new_tick)
    return adjusted


def _build_selection(
    data: CsvRows,
    wanted: list[str],
    series_mode: str,
    exclude_roll_sessions: bool,
) -> tuple[list[dict[str, Bar]], list[dict[str, Bar]], dict[str, Any], ContractSelection]:
    if series_mode not in SERIES_MODES:
        raise ValueError(f"series_mode inválido: {series_mode!r}; usa raw o adjusted")
    selection = _select_contract_rows(data, wanted)
    selection.series_mode = series_mode
    selection.exclude_roll_sessions = exclude_roll_sessions
    rows, report = align_bars(selection.rows, wanted)
    if selection.errors:
        report["errors"].extend(selection.errors)
        report["ok"] = False
    if selection.warnings:
        report["warnings"].extend(selection.warnings)
    bars_all = _apply_adjustment(rows, selection, series_mode)
    if exclude_roll_sessions and selection.roll_sessions:
        excluded = set(selection.roll_sessions)
        selection.excluded_sessions = sorted(excluded)
        bars = [
            tick
            for tick in bars_all
            if et_date(tick[wanted[0]].ts).isoformat() not in excluded
        ]
    else:
        bars = list(bars_all)
    selection.roll_events = [
        {**event, "excluded": event["date"] in set(selection.excluded_sessions)}
        for event in selection.roll_events
    ]
    if not bars:
        report["ok"] = False
        report["errors"].append("No quedan sesiones utilizables después de excluir las sesiones de roll")
    report["all_common_bars"] = report.get("common_bars", 0)
    report["all_first_ts"] = report.get("first_ts")
    report["all_last_ts"] = report.get("last_ts")
    report["all_first_et"] = report.get("first_et")
    report["all_last_et"] = report.get("last_et")
    if bars:
        report["common_bars"] = len(bars)
        report["first_ts"] = bars[0][wanted[0]].ts
        report["last_ts"] = bars[-1][wanted[0]].ts
        report["first_et"] = _fmt(report["first_ts"])
        report["last_et"] = _fmt(report["last_ts"])
    return bars_all, bars, report, selection


def _apply_session_validation(report: dict[str, Any], bars: list[dict[str, Bar]]) -> dict[str, Any]:
    if bars:
        stamps = ((tick.get("NQ") or next(iter(tick.values()))).ts for tick in bars)
        validation = validate_sessions(stamps)
    else:
        validation = validate_sessions([])
    if not bars:
        validation["ok"] = False
        if not validation["errors"]:
            validation["errors"] = ["Sin velas comunes para validar sesiones"]
    report["session_validation"] = validation
    if not validation["ok"]:
        report["ok"] = False
        report["errors"].extend(validation["errors"])
    return validation


def _build_manifest(
    path: Path,
    data: CsvRows,
    report: dict[str, Any],
    bars: list[dict[str, Bar]],
    bars_all: list[dict[str, Bar]],
    selection: ContractSelection,
) -> dict[str, Any]:
    wanted = list(report.get("symbols") or REQUIRED_SYMBOLS)
    key = wanted[0]
    session_dates = sorted({et_date(tick[key].ts).isoformat() for tick in bars})
    all_dates = sorted({et_date(tick[key].ts).isoformat() for tick in bars_all})
    contracts = {s: data.contracts.get(s, []) for s in sorted(data.bars)}
    included_days = set(session_dates)
    contracts_by_session = {
        day: values
        for day, values in selection.contracts_by_session.items()
        if day in included_days
    }
    expiry_by_session = {
        day: values
        for day, values in selection.expiry_by_session.items()
        if day in included_days
    }
    return {
        "schema_version": DATA_SCHEMA_VERSION,
        "dataset_id": dataset_identity(data),
        "series_id": series_identity(bars, selection.series_mode),
        "file_hash": _file_hash(path),
        "file_name": path.name,
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "mtime": int(path.stat().st_mtime),
        "encoding": "utf-8-sig",
        "delimiter": ",",
        "columns": list(data.columns),
        "row_count": data.row_count,
        "symbols": {s: len(bars_for_symbol) for s, bars_for_symbol in sorted(data.bars.items())},
        "selected_counts": {s: sum(1 for tick in bars if s in tick) for s in wanted},
        "contracts": contracts,
        "contract_column": "contract" in data.columns,
        "contracts_declared": bool(contracts),
        "expiry_column": data.expiry_column,
        "contract_expiries": dict(sorted(data.contract_expiries.items())),
        "series_mode": selection.series_mode,
        "exclude_roll_sessions": selection.exclude_roll_sessions,
        "contracts_by_session": contracts_by_session,
        "expiry_by_session": expiry_by_session,
        "all_contracts_by_session": selection.contracts_by_session,
        "all_expiry_by_session": selection.expiry_by_session,
        "rolls": selection.roll_events,
        "roll_sessions": selection.roll_sessions,
        "excluded_sessions": selection.excluded_sessions,
        "range": {
            "first_ts": report.get("first_ts"),
            "last_ts": report.get("last_ts"),
            "first_et": report.get("first_et"),
            "last_et": report.get("last_et"),
        },
        "source_range": {
            "first_ts": report.get("all_first_ts"),
            "last_ts": report.get("all_last_ts"),
            "first_et": report.get("all_first_et"),
            "last_et": report.get("all_last_et"),
        },
        "session_count": len(session_dates),
        "sessions": session_dates,
        "all_sessions": all_dates,
        "common_bars": len(bars),
        "all_common_bars": report.get("all_common_bars", report.get("common_bars", 0)),
        "aligned": bool(report.get("aligned")),
        "gaps": {
            "count": report.get("gap_count", 0),
            "max_gap_seconds": report.get("max_gap_seconds", 0),
        },
        "session_validation": {
            "ok": (report.get("session_validation") or {}).get("ok", False),
            "expected_start": (report.get("session_validation") or {}).get("expected_start"),
            "expected_end": (report.get("session_validation") or {}).get("expected_end"),
            "expected_bars": (report.get("session_validation") or {}).get("expected_bars"),
            "invalid_sessions": (report.get("session_validation") or {}).get("invalid_sessions", 0),
            "missing_sessions": (report.get("session_validation") or {}).get("missing_sessions", []),
            "missing_session_count": (report.get("session_validation") or {}).get("missing_session_count", 0),
            "early_close_sessions": [
                s["date"]
                for s in (report.get("session_validation") or {}).get("sessions", [])
                if s.get("early_close")
            ],
            "scheduled_early_close_sessions": list(
                (report.get("session_validation") or {}).get(
                    "scheduled_early_close_sessions", []
                )
            ),
            "skipped_early_close_sessions": list(
                (report.get("session_validation") or {}).get(
                    "skipped_early_close_sessions", []
                )
            ),
            "premarket_bars": sum(
                int(s.get("premarket_bars") or 0)
                for s in (report.get("session_validation") or {}).get("sessions", [])
            ),
        },
        "warnings": list(report.get("warnings") or []),
    }


def _attach_manifest_fields(report: dict[str, Any], manifest: dict[str, Any]) -> None:
    report["path"] = manifest["path"]
    report["schema_version"] = manifest["schema_version"]
    report["dataset_id"] = manifest["dataset_id"]
    report["series_id"] = manifest["series_id"]
    report["file_hash"] = manifest["file_hash"]
    report["contracts"] = manifest["contracts"]
    report["contract_column"] = manifest["contract_column"]
    report["contracts_declared"] = manifest["contracts_declared"]
    report["expiry_column"] = manifest["expiry_column"]
    report["contract_expiries"] = manifest["contract_expiries"]
    report["series_mode"] = manifest["series_mode"]
    report["exclude_roll_sessions"] = manifest["exclude_roll_sessions"]
    report["contracts_by_session"] = manifest["contracts_by_session"]
    report["expiry_by_session"] = manifest["expiry_by_session"]
    report["all_contracts_by_session"] = manifest["all_contracts_by_session"]
    report["all_expiry_by_session"] = manifest["all_expiry_by_session"]
    report["rolls"] = manifest["rolls"]
    report["roll_sessions"] = manifest["roll_sessions"]
    report["excluded_sessions"] = manifest["excluded_sessions"]
    report["session_count"] = manifest["session_count"]
    report["sessions"] = manifest["sessions"]
    report["all_sessions"] = manifest["all_sessions"]
    report["common_bars"] = manifest["common_bars"]
    report["all_common_bars"] = manifest["all_common_bars"]
    report["first_ts"] = manifest["range"]["first_ts"]
    report["last_ts"] = manifest["range"]["last_ts"]
    report["first_et"] = manifest["range"]["first_et"]
    report["last_et"] = manifest["range"]["last_et"]
    report["range"] = manifest["range"]
    report["source_range"] = manifest["source_range"]
    report["manifest"] = manifest


def inspect_csv(
    path: Path,
    symbols: Iterable[str] = REQUIRED_SYMBOLS,
    series_mode: str = "adjusted",
    exclude_roll_sessions: bool = True,
) -> dict[str, Any]:
    """Informe completo sin lanzar por contenido inválido (sí devuelve el error)."""
    wanted = list(symbols)
    try:
        data = _read_csv(path)
        bars_all, bars, report, selection = _build_selection(
            data, wanted, series_mode, exclude_roll_sessions
        )
    except (FileNotFoundError, ValueError) as exc:
        return {
            "ok": False,
            "path": str(path),
            "symbols": wanted,
            "counts": {},
            "common_bars": 0,
            "all_common_bars": 0,
            "aligned": False,
            "missing": {},
            "first_mismatch": [],
            "first_ts": None,
            "last_ts": None,
            "first_et": None,
            "last_et": None,
            "all_first_ts": None,
            "all_last_ts": None,
            "all_first_et": None,
            "all_last_et": None,
            "gap_count": 0,
            "max_gap_seconds": 0,
            "errors": [str(exc)],
            "warnings": [],
            "schema_version": DATA_SCHEMA_VERSION,
            "dataset_id": None,
            "series_id": None,
            "file_hash": None,
            "contracts": {},
            "contract_column": False,
            "contracts_declared": False,
            "expiry_column": False,
            "contract_expiries": {},
            "series_mode": series_mode,
            "exclude_roll_sessions": exclude_roll_sessions,
            "contracts_by_session": {},
            "expiry_by_session": {},
            "all_contracts_by_session": {},
            "all_expiry_by_session": {},
            "rolls": [],
            "roll_sessions": [],
            "excluded_sessions": [],
            "session_count": 0,
            "sessions": [],
            "all_sessions": [],
            "session_validation": {
                "ok": False,
                "expected_start": None,
                "expected_end": None,
                "expected_bars": 0,
                "invalid_sessions": 0,
                "missing_sessions": [],
                "missing_session_count": 0,
                "early_close_sessions": [],
                "scheduled_early_close_sessions": [],
                "skipped_early_close_sessions": [],
                "premarket_bars": 0,
                "afterhours_bars": 0,
                "sessions": [],
                "errors": [],
            },
            "manifest": None,
        }
    _apply_session_validation(report, bars_all)
    if not bars:
        report["ok"] = False
        if "No quedan sesiones utilizables después de excluir las sesiones de roll" not in report["errors"]:
            report["errors"].append("No quedan sesiones utilizables después de excluir las sesiones de roll")
    manifest = _build_manifest(path, data, report, bars, bars_all, selection)
    _attach_manifest_fields(report, manifest)
    return report


@dataclass(slots=True)
class CsvDataset:
    """CSV ya validado y alineado, listo para replay o backtest."""

    path: Path
    bars: list[dict[str, Bar]]
    report: dict[str, Any]
    manifest: dict[str, Any]

    @property
    def dataset_id(self) -> str:
        return str(self.manifest["dataset_id"])

    @property
    def series_id(self) -> str:
        return str(self.manifest["series_id"])

    @property
    def file_hash(self) -> str:
        return str(self.manifest["file_hash"])

    @property
    def contracts(self) -> dict[str, list[str]]:
        return dict(self.manifest.get("contracts") or {})

    @property
    def series_mode(self) -> str:
        return str(self.manifest.get("series_mode") or "adjusted")

    @property
    def rolls(self) -> list[dict[str, Any]]:
        return list(self.manifest.get("rolls") or [])

    @property
    def excluded_sessions(self) -> list[str]:
        return list(self.manifest.get("excluded_sessions") or [])

    @classmethod
    def load(
        cls,
        path: Path,
        symbols: Iterable[str] = REQUIRED_SYMBOLS,
        series_mode: str = "adjusted",
        exclude_roll_sessions: bool = True,
        *,
        allow_holdout: bool = False,
    ) -> "CsvDataset":
        """Carga y valida un CSV; rechaza el holdout salvo opt-in explícito."""
        wanted = list(symbols)
        data = _read_csv(path)
        if not allow_holdout:
            _refuse_holdout(data.bars)
        bars_all, bars, report, selection = _build_selection(
            data, wanted, series_mode, exclude_roll_sessions
        )
        _apply_session_validation(report, bars_all)
        if not report["ok"]:
            detail = "; ".join(report["errors"]) or "sin velas sincronizadas"
            raise ValueError(f"CSV inválido ({path.name}): {detail}")
        if not bars:
            raise ValueError(
                f"CSV inválido ({path.name}): no quedan sesiones utilizables después de excluir rolls"
            )
        manifest = _build_manifest(path, data, report, bars, bars_all, selection)
        _attach_manifest_fields(report, manifest)
        return cls(path=path, bars=bars, report=report, manifest=manifest)

    def __len__(self) -> int:
        return len(self.bars)


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida un CSV de velas 1m alineadas para YEDTradingBot.")
    parser.add_argument("path", type=Path, help="Ruta del CSV a validar")
    parser.add_argument("--symbols", default=",".join(REQUIRED_SYMBOLS), help="Símbolos separados por coma")
    parser.add_argument("--series", choices=sorted(SERIES_MODES), default="adjusted", help="Serie raw o ajustada")
    parser.add_argument("--include-roll-sessions", action="store_true", help="No excluir las sesiones de roll")
    args = parser.parse_args()
    report = inspect_csv(
        args.path.expanduser(),
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        series_mode=args.series,
        exclude_roll_sessions=not args.include_roll_sessions,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
