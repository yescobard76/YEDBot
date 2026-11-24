#!/usr/bin/env python3
"""Genera una copia roll-adjusted del CSV real con ajuste aditivo.

El CSV de entrada se conserva intacto. La copia mantiene las mismas columnas y
filas, y solo modifica OHLC. El ajuste usa la convención del cargador del bot:
offset del roll = primera apertura del contrato entrante - último cierre del
contrato saliente; los offsets se acumulan hacia atrás y el contrato más reciente
queda sin desplazamiento.

El manifiesto registra método, hashes, offsets por contrato, offsets acumulados
por roll y las limitaciones de haber medido todos los rolls en la frontera.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.market.csv_data import (  # noqa: E402
    HOLDOUT_START,
    REQUIRED_SYMBOLS,
    CsvDataset,
    _read_csv,
    _select_contract_rows,
)
from server.timeutil import et_date, local_dt  # noqa: E402

DEFAULT_SOURCE = ROOT / "data/real/bars_mnq_nq_es_1m.csv"
DEFAULT_OUTPUT = ROOT / "data/real/bars_mnq_nq_es_1m_roll_adjusted.csv"
PRICE_FIELDS = ("open", "high", "low", "close")
UNCHANGED_FIELDS = ("timestamp", "symbol", "contract", "expiry", "volume")
QUANTUM = Decimal("0.0001")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fmt_price(value: Decimal) -> str:
    text = format(value.quantize(QUANTUM), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def as_decimal(value: float | str | Decimal) -> Decimal:
    return Decimal(str(value))


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def boundary_detail(
    data: Any,
    symbol: str,
    from_contract: str,
    to_contract: str,
    roll_day: date,
    switch_day: date,
    applied_old: Decimal,
    applied_new: Decimal,
) -> dict[str, Any]:
    old = data.contract_bars.get(symbol, {}).get(from_contract, [])
    new = data.contract_bars.get(symbol, {}).get(to_contract, [])
    old_map = {bar.ts: bar for bar in old}
    new_map = {bar.ts: bar for bar in new}
    shared = set(old_map) & set(new_map)
    old_before = [bar for bar in old if et_date(bar.ts) <= roll_day]
    new_after = [bar for bar in new if et_date(bar.ts) >= switch_day]
    if not old_before or not new_after:
        raise ValueError(
            f"No hay barras suficientes para la frontera {symbol} "
            f"{from_contract}->{to_contract} ({roll_day}->{switch_day})"
        )
    last_old = max(old_before, key=lambda bar: bar.ts)
    first_new = min(new_after, key=lambda bar: bar.ts)
    raw_gap = as_decimal(first_new.open) - as_decimal(last_old.close)
    adjusted_gap = (
        as_decimal(first_new.open)
        + applied_new
        - (as_decimal(last_old.close) + applied_old)
    )
    return {
        "last_old_bar_et": local_dt(last_old.ts).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "last_old_close": float(last_old.close),
        "first_new_bar_et": local_dt(first_new.ts).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "first_new_open": float(first_new.open),
        "first_new_volume": int(first_new.volume),
        "session_gap_hours": round((first_new.ts - last_old.ts) / 3600, 4),
        "raw_gap_points": round(float(raw_gap), 4),
        "post_adjustment_gap_points": round(float(adjusted_gap), 4),
        "overlap_bars": len(shared),
    }


def build_manifest(
    source: Path,
    output: Path,
    raw_rows: int,
    raw_columns: list[str],
    raw_hash_before: str,
    raw_hash_after: str,
    output_hash: str,
    source_counts: dict[str, int],
    output_counts: dict[str, int],
    source_range: dict[str, Any],
    data: Any,
    selection: Any,
    rolls: list[dict[str, Any]],
    checks: dict[str, Any],
) -> dict[str, Any]:
    output_manifest = output.with_suffix(".manifest.json")
    summary = source.with_name(f"{source.stem}_summary.json")
    summary_hash = sha256_file(summary) if summary.exists() else None
    max_residual = max(
        (abs(float(event["basis_residual"].get("NQ", 0.0))) for event in selection.roll_events),
        default=0.0,
    )
    max_residual_event = max(
        selection.roll_events,
        key=lambda event: abs(float(event["basis_residual"].get("NQ", 0.0))),
        default=None,
    )
    contract_offsets = {
        symbol: {code: round(float(value), 4) for code, value in sorted(values.items())}
        for symbol, values in selection.adjustments.items()
    }
    roll_dates = [event["date"] for event in selection.roll_events]
    no_overlap = all(
        all(detail["overlap_bars"] == 0 for detail in roll["boundary"].values())
        for roll in rolls
    )
    thin_opens = {
        roll["roll_date"]: {
            symbol: detail["first_new_volume"]
            for symbol, detail in roll["boundary"].items()
        }
        for roll in rolls
    }
    return {
        "schema": "yed-roll-adjusted-csv-manifest-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "generator": {
            "script": rel(Path(__file__)),
            "version": "1.0.0",
            "description": "Copia aditiva back-adjusted y manifiesto de auditoría",
        },
        "source": {
            "path": rel(source),
            "size_bytes": source.stat().st_size,
            "rows": raw_rows,
            "columns": raw_columns,
            "symbols": list(REQUIRED_SYMBOLS),
            "counts": source_counts,
            "sessions": len(selection.contracts_by_session),
            "range": source_range,
            "contracts": data.contracts,
            "contract_expiries": dict(sorted(data.contract_expiries.items())),
            "holdout_present": False,
            "holdout_window": {
                "start": HOLDOUT_START.isoformat(),
                "end": "2026-10-30",
            },
        },
        "output": {
            "path": rel(output),
            "manifest_path": rel(output_manifest),
            "size_bytes": output.stat().st_size,
            "rows": sum(output_counts.values()),
            "columns": raw_columns,
            "symbols": list(REQUIRED_SYMBOLS),
            "counts": output_counts,
            "sessions": len(selection.contracts_by_session),
            "range": source_range,
            "price_adjustment": "additive",
            "volume_adjustment": "none",
            "roll_sessions_retained": True,
            "expected_consumption_mode": "raw",
            "expected_consumption_note": (
                "Cargar la copia con series_mode=raw para que el cargador no "
                "reconstruya el ajuste. Con la convención actual, cargarla como "
                "adjusted también es idempotente; raw es el modo explícito."
            ),
        },
        "hashes": {
            "source_csv_sha256": raw_hash_before,
            "source_csv_sha256_after": raw_hash_after,
            "source_csv_unchanged": raw_hash_before == raw_hash_after,
            "source_summary_sha256": summary_hash,
            "output_csv_sha256": output_hash,
            "algorithm": "sha256",
        },
        "method": {
            "name": "additive_back_adjustment",
            "formula": "adjusted_ohlc = raw_ohlc + cumulative_offset(symbol, contract)",
            "offset_formula": (
                "offset(roll) = first_open(new_contract, switch_session) - "
                "last_close(old_contract, roll_session)"
            ),
            "offset_sign": (
                "Positivo si el contrato entrante cotiza por encima del saliente; "
                "se suma al histórico del contrato saliente."
            ),
            "backward_accumulation": (
                "Los offsets se acumulan desde el roll más reciente hacia atrás. "
                "El contrato más reciente tiene offset 0."
            ),
            "contract_selection": (
                "Contrato vivo de vencimiento más próximo por sesión; desempate por código."
            ),
            "roll_date": "Última sesión del contrato saliente.",
            "switch_date": "Primera sesión del contrato entrante.",
            "price_fields": list(PRICE_FIELDS),
            "volume": "sin cambios",
            "rounding": (
                "Precios ajustados a 0.0001 y sin ceros finales; el tick fuente es 0.25."
            ),
            "nq_mnq_basis": (
                "NQ y MNQ comparten el offset aplicado de MNQ para preservar la base "
                "NQ/MNQ del motor; ES usa su propio offset."
            ),
            "cumulative_offset_semantics": (
                "En cada roll, cumulative_offset_points es el desplazamiento total que "
                "recibe todo el histórico del contrato saliente: incluye ese roll y todos "
                "los posteriores. contract_offsets contiene el mismo valor por contrato."
            ),
            "reload_behavior": (
                "La copia ya está ajustada. Cargarla de nuevo como adjusted recalcula "
                "spreads de 0 en MNQ/ES y usa el offset MNQ 0 para NQ; no se desplaza. "
                "Se recomienda raw para no depender de esa idempotencia."
            ),
            "roll_sessions": "retenidas; no se excluyen",
            "boundary_fallback": (
                "Si no hay minutos solapados, se usa la primera apertura del contrato "
                "nuevo menos el último cierre del contrato viejo."
            ),
            "post_adjustment_gap": (
                "adjusted_first_open(new) - adjusted_last_close(old). Mide la "
                "discontinuidad que queda tras el ajuste; MNQ y ES deben quedar en 0. "
                "NQ puede conservar el residual de la base compartida con MNQ."
            ),
        },
        "rolls": rolls,
        "roll_dates": roll_dates,
        "contract_offsets": contract_offsets,
        "checks": checks,
        "limitations": [
            {
                "id": "boundary_only",
                "severity": "high",
                "detail": (
                    f"Los {len(rolls)} rolls usan method=boundary y "
                    f"{'todos tienen' if no_overlap else 'no todos tienen'} 0 barras solapadas. "
                    "No hay cotización simultánea de ambos contratos: el offset mezcla el "
                    "spread de calendario con el movimiento nocturno. No es un spread puro."
                ),
            },
            {
                "id": "thin_new_open",
                "severity": "high",
                "detail": (
                    "La primera barra del contrato entrante es de 09:00 ET, no de 09:30, y "
                    "puede tener volumen bajo. El offset depende de una sola apertura. "
                    f"Volúmenes de la primera barra nueva por roll: {thin_opens}."
                ),
            },
            {
                "id": "nq_mnq_shared_offset",
                "severity": "medium",
                "detail": (
                    "NQ y MNQ comparten el offset de MNQ por diseño del motor. "
                    f"El residual absoluto máximo de NQ es {max_residual:.2f} puntos"
                    + (
                        f" en el roll {max_residual_event['date']}."
                        if max_residual_event is not None
                        else "."
                    )
                    + " La serie NQ ajustada conserva ese gap en la frontera; MNQ y ES "
                    "quedan en cero. Si se necesita continuidad exacta por símbolo, usar "
                    "offsets independientes, que no son los de esta copia."
                ),
            },
            {
                "id": "roll_calendar_rule",
                "severity": "high",
                "detail": (
                    "El calendario de roll se deriva del vencimiento (contrato vivo más "
                    "próximo), no de volumen ni open interest. Los 6 rolls caen 8 días "
                    "antes del vencimiento. No es necesariamente el roll oficial o líquido."
                ),
            },
            {
                "id": "additive_returns",
                "severity": "medium",
                "detail": (
                    "El ajuste aditivo conserva diferencias absolutas en puntos, pero altera "
                    "los retornos porcentuales y la volatilidad relativa. No equivale a un "
                    "ajuste multiplicativo por ratio."
                ),
            },
            {
                "id": "synthetic_prices",
                "severity": "high",
                "detail": (
                    "Los precios ajustados son una serie contable sintética, no cotizaciones "
                    "ejecutables de ningún contrato. No usar esta copia para simular fills, "
                    "slippage o P&L realizado sin reconstruir el contrato activo."
                ),
            },
            {
                "id": "roll_sessions_retained",
                "severity": "medium",
                "detail": (
                    "Las 6 sesiones de roll se conservan en la copia. Si se quieren excluir, "
                    "usar roll_dates; el motor puede hacerlo con exclude_roll_sessions=true."
                ),
            },
            {
                "id": "already_adjusted_series",
                "severity": "medium",
                "detail": (
                    "La copia conserva contract y expiry, pero ya está ajustada. Con la "
                    "convención actual, cargarla como series_mode=adjusted recalcula "
                    "spreads 0 y no la desplaza; la idempotencia está verificada en el "
                    "manifiesto. Consumirla como series_mode=raw es el modo explícito y "
                    "evita depender de esa convención si el cargador cambia."
                ),
            },
            {
                "id": "holdout_absent",
                "severity": "info",
                "detail": (
                    "La fuente termina el 2026-06-30. No contiene el holdout sellado "
                    "2026-07-01 -> 2026-10-30; esta copia tampoco."
                ),
            },
            {
                "id": "volume_untouched",
                "severity": "info",
                "detail": (
                    "volume no se ajusta y no se reconstruye open interest. La serie ajustada "
                    "solo modifica OHLC."
                ),
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source = args.source if args.source.is_absolute() else ROOT / args.source
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if source.resolve() == output.resolve():
        raise SystemExit("source y output no pueden ser el mismo archivo")
    if not source.exists():
        raise SystemExit(f"No existe el CSV fuente: {source}")

    raw_hash_before = sha256_file(source)
    data = _read_csv(source)
    selection = _select_contract_rows(data, list(REQUIRED_SYMBOLS))
    if selection.errors:
        raise SystemExit("Errores de selección de contrato: " + "; ".join(selection.errors))
    if not selection.roll_events:
        raise SystemExit("El CSV no contiene rolls; no hay nada que ajustar")

    max_source_date = max(et_date(bar.ts) for bars in data.bars.values() for bar in bars)
    if max_source_date >= HOLDOUT_START:
        raise SystemExit(
            f"La fuente contiene sesiones desde {HOLDOUT_START}; el holdout está sellado"
        )

    # Offset acumulado que se aplica al contrato saliente en cada roll.
    cumulative_by_event: list[dict[str, Decimal]] = []
    running = {symbol: Decimal("0") for symbol in REQUIRED_SYMBOLS}
    for event in reversed(selection.roll_events):
        for symbol in REQUIRED_SYMBOLS:
            running[symbol] += as_decimal(event["applied_offsets"].get(symbol, 0.0))
        cumulative_by_event.append(dict(running))
    cumulative_by_event.reverse()

    rolls: list[dict[str, Any]] = []
    for index, (event, cumulative) in enumerate(
        zip(selection.roll_events, cumulative_by_event, strict=True), start=1
    ):
        roll_day = date.fromisoformat(event["date"])
        switch_day = date.fromisoformat(event["switch_date"])
        boundary: dict[str, Any] = {}
        for symbol in REQUIRED_SYMBOLS:
            old_code = event["from"][symbol]
            new_code = event["to"][symbol]
            applied_old = as_decimal(selection.adjustments[symbol].get(old_code, 0.0))
            applied_new = as_decimal(selection.adjustments[symbol].get(new_code, 0.0))
            if applied_old != cumulative[symbol]:
                raise SystemExit(
                    f"Offset acumulado inconsistente {symbol} {old_code}: "
                    f"{applied_old} != {cumulative[symbol]}"
                )
            if applied_new != cumulative[symbol] - as_decimal(
                event["applied_offsets"].get(symbol, 0.0)
            ):
                raise SystemExit(
                    f"Offset entrante inconsistente {symbol} {new_code}: {applied_new}"
                )
            boundary[symbol] = boundary_detail(
                data,
                symbol,
                old_code,
                new_code,
                roll_day,
                switch_day,
                applied_old,
                applied_new,
            )
        rolls.append(
            {
                "sequence": index,
                "roll_date": event["date"],
                "switch_date": event["switch_date"],
                "from": dict(event["from"]),
                "to": dict(event["to"]),
                "expiry_from": {
                    symbol: data.contract_expiries.get(code)
                    for symbol, code in event["from"].items()
                },
                "expiry_to": {
                    symbol: data.contract_expiries.get(code)
                    for symbol, code in event["to"].items()
                },
                "method": dict(event["methods"]),
                "raw_spread_points": {
                    symbol: round(float(event["offsets"].get(symbol, 0.0)), 4)
                    for symbol in REQUIRED_SYMBOLS
                },
                "applied_offset_points": {
                    symbol: round(float(event["applied_offsets"].get(symbol, 0.0)), 4)
                    for symbol in REQUIRED_SYMBOLS
                },
                "basis_residual_points": {
                    symbol: round(float(event["basis_residual"].get(symbol, 0.0)), 4)
                    for symbol in REQUIRED_SYMBOLS
                },
                "cumulative_offset_points": {
                    symbol: round(float(cumulative[symbol]), 4)
                    for symbol in REQUIRED_SYMBOLS
                },
                "boundary": boundary,
            }
        )

    source_counts: dict[str, int] = {symbol: 0 for symbol in REQUIRED_SYMBOLS}
    output_counts: dict[str, int] = {symbol: 0 for symbol in REQUIRED_SYMBOLS}
    rows_written = 0
    adjusted_rows = 0
    contract_mismatches: list[str] = []
    holdout_rows = 0
    output.parent.mkdir(parents=True, exist_ok=True)

    with source.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        columns = [(name or "").strip() for name in (reader.fieldnames or [])]
        for required in ("timestamp", "symbol", "open", "high", "low", "close", "contract"):
            if required not in columns:
                raise SystemExit(f"Falta la columna {required} en el CSV fuente")
        with output.open("w", encoding="utf-8", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            for row in reader:
                symbol = (row.get("symbol") or "").strip().upper()
                contract = (row.get("contract") or "").strip().upper()
                if symbol not in REQUIRED_SYMBOLS:
                    raise SystemExit(f"Símbolo no esperado: {symbol!r}")
                try:
                    day = date.fromisoformat((row.get("timestamp") or "")[:10])
                except ValueError:
                    raise SystemExit(f"Timestamp inválido: {row.get('timestamp')!r}") from None
                if day >= HOLDOUT_START:
                    holdout_rows += 1
                expected_contract = selection.contracts_by_session.get(day.isoformat(), {}).get(
                    symbol
                )
                if expected_contract != contract:
                    contract_mismatches.append(
                        f"{row.get('timestamp')} {symbol}: {contract} != {expected_contract}"
                    )
                offset = as_decimal(selection.adjustments.get(symbol, {}).get(contract, 0.0))
                for field in PRICE_FIELDS:
                    row[field] = fmt_price(as_decimal(row[field]) + offset)
                writer.writerow(row)
                source_counts[symbol] += 1
                output_counts[symbol] += 1
                rows_written += 1
                if offset:
                    adjusted_rows += 1

    raw_hash_after = sha256_file(source)
    output_hash = sha256_file(output)
    if contract_mismatches:
        raise SystemExit(
            "El contrato de alguna fila no coincide con la selección del cargador: "
            + "; ".join(contract_mismatches[:3])
        )
    if holdout_rows:
        raise SystemExit(f"La copia contiene {holdout_rows} filas del holdout")
    if rows_written != data.row_count:
        raise SystemExit(f"Filas escritas {rows_written} != filas fuente {data.row_count}")

    # Validación estructural de la copia: se carga como raw para no reajustar.
    loaded = CsvDataset.load(
        output,
        REQUIRED_SYMBOLS,
        series_mode="raw",
        exclude_roll_sessions=False,
        allow_holdout=False,
    )
    if len(loaded.bars) != len(data.bars["NQ"]):
        raise SystemExit(
            f"Barras cargadas {len(loaded.bars)} != barras fuente {len(data.bars['NQ'])}"
        )
    reloaded_adjusted = CsvDataset.load(
        output,
        REQUIRED_SYMBOLS,
        series_mode="adjusted",
        exclude_roll_sessions=False,
        allow_holdout=False,
    )
    adjusted_reload_zero_offsets = all(
        abs(float(offset)) < 1e-12
        for event in reloaded_adjusted.rolls
        for offset in event.get("applied_offsets", {}).values()
    )
    adjusted_reload_equals_raw = reloaded_adjusted.bars == loaded.bars

    # Comparación fila a fila: campos no-precio intactos y OHLC con el offset exacto.
    unchanged_mismatches = 0
    price_mismatches = 0
    max_price_error = Decimal("0")
    with source.open("r", encoding="utf-8-sig", newline="") as src, output.open(
        "r", encoding="utf-8", newline=""
    ) as dst:
        raw_reader = csv.DictReader(src)
        out_reader = csv.DictReader(dst)
        for raw_row, out_row in zip(raw_reader, out_reader, strict=True):
            for field in UNCHANGED_FIELDS:
                if raw_row.get(field, "") != out_row.get(field, ""):
                    unchanged_mismatches += 1
            symbol = (raw_row.get("symbol") or "").strip().upper()
            contract = (raw_row.get("contract") or "").strip().upper()
            offset = as_decimal(selection.adjustments.get(symbol, {}).get(contract, 0.0))
            for field in PRICE_FIELDS:
                expected = as_decimal(raw_row[field]) + offset
                actual = as_decimal(out_row[field])
                error = abs(actual - expected)
                max_price_error = max(max_price_error, error)
                if error > Decimal("0.0001"):
                    price_mismatches += 1

    max_residual = max(
        (abs(float(event["basis_residual"].get("NQ", 0.0))) for event in selection.roll_events),
        default=0.0,
    )
    checks = {
        "source_unchanged": raw_hash_before == raw_hash_after,
        "row_count_match": rows_written == data.row_count,
        "rows_written": rows_written,
        "adjusted_rows": adjusted_rows,
        "unchanged_field_mismatches": unchanged_mismatches,
        "price_mismatches": price_mismatches,
        "max_price_error": round(float(max_price_error), 8),
        "contract_mismatches": len(contract_mismatches),
        "holdout_rows": holdout_rows,
        "output_loaded_as_raw": True,
        "output_loaded_bars": len(loaded.bars),
        "output_loaded_sessions": len(loaded.manifest["contracts_by_session"]),
        "output_loaded_roll_sessions": len(loaded.manifest["roll_sessions"]),
        "adjusted_reload_zero_offsets": adjusted_reload_zero_offsets,
        "adjusted_reload_equals_raw": adjusted_reload_equals_raw,
        "all_rolls_boundary": all(
            all(method == "boundary" for method in event["methods"].values())
            for event in selection.roll_events
        ),
        "all_rolls_no_overlap": all(
            detail["overlap_bars"] == 0
            for roll in rolls
            for detail in roll["boundary"].values()
        ),
        "nq_max_basis_residual_points": max_residual,
        "roll_dates": [event["date"] for event in selection.roll_events],
        "roll_sessions_retained": True,
    }
    if not checks["source_unchanged"]:
        raise SystemExit("El CSV fuente cambió durante la generación")
    if unchanged_mismatches or price_mismatches:
        raise SystemExit(
            f"Verificación fallida: {unchanged_mismatches} campos intactos alterados, "
            f"{price_mismatches} precios fuera de tolerancia"
        )
    if not adjusted_reload_zero_offsets or not adjusted_reload_equals_raw:
        raise SystemExit("La copia no es idempotente al recargarla como adjusted")

    first_ts = min(bar.ts for bars in data.bars.values() for bar in bars)
    last_ts = max(bar.ts for bars in data.bars.values() for bar in bars)
    source_range = {
        "first_ts": first_ts,
        "last_ts": last_ts,
        "first_et": local_dt(first_ts).strftime("%Y-%m-%d %H:%M:%S %Z"),
        "last_et": local_dt(last_ts).strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    manifest = build_manifest(
        source,
        output,
        data.row_count,
        columns,
        raw_hash_before,
        raw_hash_after,
        output_hash,
        source_counts,
        output_counts,
        source_range,
        data,
        selection,
        rolls,
        checks,
    )
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"OK {rows_written} filas | {len(rolls)} rolls | "
        f"ajustadas {adjusted_rows} | raw intacto={checks['source_unchanged']}"
    )
    print(f"CSV: {rel(output)}")
    print(f"MANIFEST: {rel(manifest_path)}")
    print(f"SHA256 raw: {raw_hash_before}")
    print(f"SHA256 adjusted: {output_hash}")
    print(
        "Gaps post-ajuste: "
        + "; ".join(
            f"{roll['roll_date']} "
            + ",".join(
                f"{symbol}={detail['post_adjustment_gap_points']}"
                for symbol, detail in roll["boundary"].items()
            )
            for roll in rolls
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
