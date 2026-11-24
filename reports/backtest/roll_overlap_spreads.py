#!/usr/bin/env python3
"""Calcula spreads old/new por solape en los seis rolls del protocolo.

Fuente: data/real/raw_mnq_nq_es_1m.jsonl.gz, el dump crudo de Databento que
contiene los 24 contratos. No descarga ni modifica configuración.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data/real/raw_mnq_nq_es_1m.jsonl.gz"
MANIFEST = ROOT / "data/real/bars_mnq_nq_es_1m_roll_adjusted.manifest.json"
OUT_JSON = ROOT / "reports/backtest/roll_overlap_spreads.json"
OUT_MD = ROOT / "reports/backtest/ROLL_OVERLAP_SPREADS.md"
OUT_CSV = ROOT / "reports/backtest/roll_overlap_spreads.csv"
ET = ZoneInfo("America/New_York")
ROOTS = ("MNQ", "NQ", "ES")
SESSION_OPEN = time(9, 0)
SESSION_CLOSE = time(15, 59)
HOLDOUT_START = date(2026, 7, 1)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def et_day(ts: int) -> date:
    return datetime.fromtimestamp(ts, ET).date()


def et_time(ts: int) -> time:
    return datetime.fromtimestamp(ts, ET).time()


def session_ts(ts: int) -> bool:
    return SESSION_OPEN <= et_time(ts) <= SESSION_CLOSE


def ts_at(day: date, hhmm: str) -> int:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return int(datetime.combine(day, time(hour, minute), tzinfo=ET).timestamp())


def canonical_code(raw_symbol: str, expiration: str) -> str | None:
    match = re.fullmatch(r"(MNQ|NQ|ES)([FGHJKMNQUVXZ])(\d{1,2})", raw_symbol.upper())
    if not match:
        return None
    root, month, _ = match.groups()
    year = int(expiration[:4])
    return f"{root}{month}{year % 100:02d}"


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "p10": round(quantile(values, 0.10), 4),
        "p90": round(quantile(values, 0.90), 4),
    }


def load_raw() -> tuple[dict[str, Any], dict[str, str], dict[str, dict[int, dict[str, Any]]]]:
    with gzip.open(RAW, "rt", encoding="utf-8") as handle:
        meta = json.loads(handle.readline())
        raw_to_code: dict[str, str] = {}
        for definition in meta.get("definitions", []):
            raw = str(definition.get("raw_symbol") or "").upper()
            code = canonical_code(raw, str(definition.get("expiration") or ""))
            if code:
                raw_to_code[raw] = code

        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        wanted: set[str] = set()
        for roll in manifest["rolls"]:
            wanted.update(roll["from"].values())
            wanted.update(roll["to"].values())

        window_days: set[str] = set()
        for roll in manifest["rolls"]:
            roll_day = date.fromisoformat(roll["roll_date"])
            switch_day = date.fromisoformat(roll["switch_date"])
            for day in (roll_day - timedelta(days=1), roll_day, switch_day, switch_day + timedelta(days=1)):
                window_days.add(day.isoformat())

        bars: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("type") != "bar":
                continue
            raw_symbol = str(record.get("symbol") or "").upper()
            code = raw_to_code.get(raw_symbol)
            if not code or code not in wanted:
                continue
            ts = int(record["ts_event"])
            if et_day(ts).isoformat() not in window_days:
                continue
            bars[code][ts] = {
                "open": float(record["open"]),
                "high": float(record["high"]),
                "low": float(record["low"]),
                "close": float(record["close"]),
                "volume": float(record.get("volume") or 0.0),
            }
    return meta, raw_to_code, bars


def pick_bar(
    bars: dict[int, dict[str, Any]],
    day: date,
    hhmm: str,
    direction: str,
) -> tuple[int, dict[str, Any]] | None:
    target = ts_at(day, hhmm)
    candidates = [
        (ts, bar)
        for ts, bar in bars.items()
        if et_day(ts) == day and session_ts(ts)
    ]
    if not candidates:
        return None
    if direction == "ge":
        candidates = [item for item in candidates if item[0] >= target]
        return min(candidates, key=lambda item: item[0]) if candidates else None
    candidates = [item for item in candidates if item[0] <= target]
    return max(candidates, key=lambda item: item[0]) if candidates else None


def common_bars(
    old_bars: dict[int, dict[str, Any]],
    new_bars: dict[int, dict[str, Any]],
    day: date,
) -> list[tuple[int, dict[str, Any], dict[str, Any]]]:
    common = []
    for ts in sorted(set(old_bars) & set(new_bars)):
        if et_day(ts) != day or not session_ts(ts):
            continue
        common.append((ts, old_bars[ts], new_bars[ts]))
    return common


def analyze_roll(roll: dict[str, Any], bars: dict[str, dict[int, dict[str, Any]]]) -> dict[str, Any]:
    roll_day = date.fromisoformat(roll["roll_date"])
    switch_day = date.fromisoformat(roll["switch_date"])
    if switch_day >= HOLDOUT_START or roll_day >= HOLDOUT_START:
        raise RuntimeError(f"roll {roll['sequence']} toca el holdout")

    symbols: dict[str, Any] = {}
    for symbol in ROOTS:
        old_code = roll["from"][symbol]
        new_code = roll["to"][symbol]
        old_bars = bars.get(old_code, {})
        new_bars = bars.get(new_code, {})

        overlap_roll = common_bars(old_bars, new_bars, roll_day)
        overlap_switch = common_bars(old_bars, new_bars, switch_day)
        spreads = [new["close"] - old["close"] for _, old, new in overlap_roll + overlap_switch]

        old_last = pick_bar(old_bars, roll_day, "15:59", "le")
        new_first = pick_bar(new_bars, switch_day, "09:00", "ge")
        boundary = None
        boundary_ts = None
        if old_last and new_first:
            boundary = new_first[1]["open"] - old_last[1]["close"]
            boundary_ts = {
                "old_close_et": datetime.fromtimestamp(old_last[0], ET).isoformat(),
                "new_open_et": datetime.fromtimestamp(new_first[0], ET).isoformat(),
            }

        roll_close = None
        roll_close_ts = None
        if overlap_roll:
            target = ts_at(roll_day, "15:59")
            candidates = [item for item in overlap_roll if item[0] <= target]
            if candidates:
                ts, old, new = max(candidates, key=lambda item: item[0])
                roll_close = new["close"] - old["close"]
                roll_close_ts = datetime.fromtimestamp(ts, ET).isoformat()

        switch_open = None
        switch_open_ts = None
        if overlap_switch:
            target = ts_at(switch_day, "09:00")
            candidates = [item for item in overlap_switch if item[0] >= target]
            if candidates:
                ts, old, new = min(candidates, key=lambda item: item[0])
                switch_open = new["open"] - old["open"]
                switch_open_ts = datetime.fromtimestamp(ts, ET).isoformat()

        applied = float(roll["applied_offset_points"][symbol])
        raw_boundary = float(roll["raw_spread_points"][symbol])
        overlap_stats = stats(spreads)
        overlap_median = overlap_stats.get("median")
        switch_gap = (
            round(boundary - switch_open, 4)
            if boundary is not None and switch_open is not None
            else None
        )
        symbols[symbol] = {
            "old_contract": old_code,
            "new_contract": new_code,
            "applied_offset_points": applied,
            "manifest_raw_spread_points": raw_boundary,
            "boundary_recalc_points": round(boundary, 4) if boundary is not None else None,
            "boundary_ts": boundary_ts,
            "boundary_recalc_minus_manifest_raw": round(boundary - raw_boundary, 4) if boundary is not None else None,
            "boundary_recalc_minus_applied": round(boundary - applied, 4) if boundary is not None else None,
            "roll_close_spread_points": round(roll_close, 4) if roll_close is not None else None,
            "roll_close_ts": roll_close_ts,
            "switch_open_spread_points": round(switch_open, 4) if switch_open is not None else None,
            "switch_open_ts": switch_open_ts,
            "overlap": overlap_stats,
            "overlap_roll": stats([new["close"] - old["close"] for _, old, new in overlap_roll]),
            "overlap_switch": stats([new["close"] - old["close"] for _, old, new in overlap_switch]),
            "median_minus_applied": (
                round(overlap_median - applied, 4)
                if overlap_median is not None
                else None
            ),
            "boundary_minus_median": (
                round(boundary - overlap_median, 4)
                if boundary is not None and overlap_median is not None
                else None
            ),
            "boundary_minus_switch_open": switch_gap,
            "roll_close_minus_applied": (
                round(roll_close - applied, 4) if roll_close is not None else None
            ),
            "switch_open_minus_applied": (
                round(switch_open - applied, 4) if switch_open is not None else None
            ),
        }
    return {
        "sequence": roll["sequence"],
        "roll_date": roll["roll_date"],
        "switch_date": roll["switch_date"],
        "symbols": symbols,
    }


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def main() -> None:
    meta, raw_to_code, bars = load_raw()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rolls = [analyze_roll(roll, bars) for roll in manifest["rolls"]]

    deltas: list[float] = []
    boundary_deltas: list[float] = []
    gaps: list[float] = []
    for roll in rolls:
        for symbol in ROOTS:
            row = roll["symbols"][symbol]
            if row["median_minus_applied"] is not None:
                deltas.append(row["median_minus_applied"])
            if row["boundary_minus_median"] is not None:
                boundary_deltas.append(row["boundary_minus_median"])
            if row["boundary_minus_switch_open"] is not None:
                gaps.append(row["boundary_minus_switch_open"])

    output = {
        "schema": "roll-overlap-spreads-v1",
        "source": {
            "raw": str(RAW.relative_to(ROOT)).replace("\\", "/"),
            "raw_sha256": sha256_file(RAW),
            "raw_start": meta.get("start"),
            "raw_end": meta.get("end"),
            "definitions": len(meta.get("definitions", [])),
            "mapped_contracts": len(raw_to_code),
        },
        "boundary_source": str(MANIFEST.relative_to(ROOT)).replace("\\", "/"),
        "method": {
            "spread": "new.close - old.close en timestamps comunes",
            "session": "09:00–15:59 America/New_York",
            "boundary": "new.open 09:00 switch - old.close 15:59 roll",
            "window": "roll_date y switch_date",
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_used": False,
        },
        "rolls": rolls,
        "summary": {
            "rolls": len(rolls),
            "symbol_rolls": len(rolls) * len(ROOTS),
            "overlap_observations": sum(
                row["overlap"].get("count", 0)
                for roll in rolls
                for row in roll["symbols"].values()
            ),
            "median_abs_delta_vs_applied": round(
                statistics.median([abs(value) for value in deltas]), 4
            ) if deltas else None,
            "max_abs_delta_vs_applied": round(max((abs(value) for value in deltas), default=0.0), 4),
            "median_abs_boundary_minus_overlap": round(
                statistics.median([abs(value) for value in boundary_deltas]), 4
            ) if boundary_deltas else None,
            "max_abs_boundary_minus_overlap": round(
                max((abs(value) for value in boundary_deltas), default=0.0), 4
            ),
            "median_abs_overnight_gap": round(
                statistics.median([abs(value) for value in gaps]), 4
            ) if gaps else None,
        },
    }
    OUT_JSON.write_text(json.dumps(output, indent=1, ensure_ascii=False), encoding="utf-8")

    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "sequence",
                "roll_date",
                "switch_date",
                "symbol",
                "old_contract",
                "new_contract",
                "timestamp_et",
                "old_close",
                "new_close",
                "spread_points",
            ]
        )
        for roll in manifest["rolls"]:
            roll_day = date.fromisoformat(roll["roll_date"])
            switch_day = date.fromisoformat(roll["switch_date"])
            for symbol in ROOTS:
                old_code = roll["from"][symbol]
                new_code = roll["to"][symbol]
                for day in (roll_day, switch_day):
                    for ts, old, new in common_bars(
                        bars.get(old_code, {}), bars.get(new_code, {}), day
                    ):
                        writer.writerow(
                            [
                                roll["sequence"],
                                roll["roll_date"],
                                roll["switch_date"],
                                symbol,
                                old_code,
                                new_code,
                                datetime.fromtimestamp(ts, ET).isoformat(),
                                f"{old['close']:.2f}",
                                f"{new['close']:.2f}",
                                f"{new['close'] - old['close']:.4f}",
                            ]
                        )

    lines = [
        "# Spreads old/new por solape en los seis rolls",
        "",
        "**Fuente:** `data/real/raw_mnq_nq_es_1m.jsonl.gz` (dump Databento con los 24 contratos).  ",
        "**Boundary de referencia:** `bars_mnq_nq_es_1m_roll_adjusted.manifest.json`.  ",
        "**Método:** `nuevo.close − viejo.close` en timestamps comunes, sesión 09:00–15:59 ET.  ",
        "**Holdout:** no usado.  ",
        "**Descarga:** no se hizo una descarga nueva; el dump local ya contiene los 24 contratos.",
        "",
        "## Resultado por roll",
        "",
        "| Roll | Símbolo | Contratos | Boundary aplicado | Boundary recalc | Δ recalc−aplicado | Solape mediana | Δ boundary−mediana | Cierre roll | Apertura switch | Gap overnight implícito | N solape |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for roll in rolls:
        for symbol in ROOTS:
            row = roll["symbols"][symbol]
            lines.append(
                "| {seq} | {sym} | {old}→{new} | {applied} | {recalc} | {dr} | {median} | {dm} | {rc} | {so} | {gap} | {n} |".format(
                    seq=roll["sequence"],
                    sym=symbol,
                    old=row["old_contract"],
                    new=row["new_contract"],
                    applied=fmt(row["applied_offset_points"]),
                    recalc=fmt(row["boundary_recalc_points"]),
                    dr=fmt(row["boundary_recalc_minus_applied"]),
                    median=fmt(row["overlap"].get("median")),
                    dm=fmt(row["boundary_minus_median"]),
                    rc=fmt(row["roll_close_spread_points"]),
                    so=fmt(row["switch_open_spread_points"]),
                    gap=fmt(row["boundary_minus_switch_open"]),
                    n=row["overlap"].get("count", 0),
                )
            )

    lines += [
        "",
        "## Ejemplo de descomposición",
        "",
        "Roll 1, MNQ: boundary 448.25 = gap overnight del viejo 244.00 + spread de apertura 204.25. El spread de solape fue 205.25. El boundary no mide el spread: mide el hueco de precio hasta la apertura siguiente.",
        "",
        "## Lectura",
        "",
        f"- Observaciones de solape: **{output['summary']['overlap_observations']:,}** barras comunes.",
        f"- Mediana del valor absoluto de `mediana solape − boundary aplicado`: **{fmt(output['summary']['median_abs_delta_vs_applied'])} puntos**.",
        f"- Mediana del valor absoluto de `boundary − mediana de solape`: **{fmt(output['summary']['median_abs_boundary_minus_overlap'])} puntos**.",
        f"- Máxima diferencia absoluta `boundary − mediana de solape`: **{fmt(output['summary']['max_abs_boundary_minus_overlap'])} puntos**.",
        f"- Mediana del gap overnight implícito (`boundary − apertura switch`): **{fmt(output['summary']['median_abs_overnight_gap'])} puntos**.",
        "- `Boundary recalc` es `nuevo.open 09:00 del switch − viejo.close 15:59 del roll`; debe coincidir con `raw_spread` del manifiesto (salvo redondeos y el residual NQ/MNQ).",
        "- El boundary actual **no es un spread de calendario**: es un offset de frontera que incluye el movimiento overnight del contrato viejo. En los seis rolls, el spread de solape se mantiene en ~202–280 (MNQ/NQ) y ~50–62 (ES), pero el boundary cambia de signo y de magnitud (de −57 a 560 en MNQ/NQ, de −6 a 104 en ES).",
        "- `overlap_bars=0` en el manifiesto no significa que no haya solape en el mercado: el manifiesto se calculó sobre el CSV final, que ya tiene solo el contrato activo. El dump crudo sí conserva ambos contratos.",
        "- En NQ, el offset aplicado usa el de MNQ; por eso `Δ recalc−aplicado` puede incluir el residual NQ vs MNQ.",
        "- El CSV `roll_overlap_spreads.csv` contiene cada spread por minuto para auditoría.",
        "",
        "## Implicación",
        "",
        "- Si el objetivo es **medir el spread entre contratos**, usa la mediana de solape (o el spread al mismo timestamp), no el boundary actual.",
        "- Si el objetivo es **ajustar una serie continua de precios**, el boundary mantiene continuidad de nivel, pero elimina el retorno overnight. Para preservar retornos, el offset debe medirse con ambos contratos en el mismo timestamp (por ejemplo, cierre del roll o apertura del switch), no entre el cierre de un día y la apertura del siguiente.",
        "- No conviene reemplazar el CSV roll-adjusted actual sin decidir esa convención: el cambio afecta la serie histórica. El raw y el CSV actual no se tocaron en esta auditoría.",
        "",
        "## Artefactos",
        "",
        "- `reports/backtest/roll_overlap_spreads.json`",
        "- `reports/backtest/roll_overlap_spreads.csv`",
        "- `reports/backtest/ROLL_OVERLAP_SPREADS.md`",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=1, ensure_ascii=False))
    print(f"JSON: {OUT_JSON}")
    print(f"CSV: {OUT_CSV}")
    print(f"MD: {OUT_MD}")


if __name__ == "__main__":
    main()
