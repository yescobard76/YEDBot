"""Scorecard continuo de los presets con curva de equity agregada.

Fuente: reports/backtest/equity_continuous_dev.json (solo desarrollo).
Calcula DD agregado, tiempo bajo agua, recuperación del DD máximo y neto/DD.
No ejecuta backtests, no usa el holdout y no modifica la configuración activa.

Los umbrales de promoción son constantes del script: se fijan antes de
comparar la tabla y no se ajustan después de ver los resultados.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "reports/backtest/equity_continuous_dev.json"
DEFAULT_JSON = ROOT / "reports/backtest/continuous_scorecard.json"
DEFAULT_CSV = ROOT / "reports/backtest/continuous_scorecard.csv"
SCHEMA = "continuous-scorecard-v1"

# Criterios v1.0, fijados antes de ordenar la tabla.
CRITERIA: dict[str, Any] = {
    "version": "1.0",
    "date": "2026-11-21",
    "dd_max_usd": 2_000.0,
    "tuw_max_pct": 35.0,
    "recovery_max_sessions": 126,
    "net_dd_min": 0.50,
    "positive_blocks_min": 4,
    "require_net_positive": True,
    "require_ex_w4_positive": True,
    "sample_min_paper": 80,
    "tier_a": "P1+P2+P3+P4+P5+P6",
    "tier_b": "P1+P2+P3+P6, fallando P4 y/o P5 (solo ampliar muestra)",
    "tier_c": "resto",
    "note": (
        "P4/P5 pueden fallar y dejar el preset en B (ampliar muestra), "
        "pero no en A (promoción). La muestra G4 se reporta aparte."
    ),
}


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def score_preset(name: str, result: dict[str, Any], initial: float) -> dict[str, Any]:
    """Calcula el scorecard de un preset sobre su curva diaria continua."""
    daily = sorted(result["daily_equity"], key=lambda point: point["date"])
    if not daily:
        raise ValueError(f"{name}: curva diaria vacía")

    peak = float(initial)
    peak_index = 0
    peak_date = daily[0]["date"]
    max_dd = 0.0
    dd_peak = float(initial)
    dd_peak_date = daily[0]["date"]
    trough = float(initial)
    trough_date = daily[0]["date"]
    trough_index = 0
    underwater_sessions = 0
    underwater_streak = 0
    longest_underwater = 0

    for index, point in enumerate(daily):
        equity = float(point["equity"])
        if equity > peak:
            peak = equity
            peak_index = index
            peak_date = point["date"]
        drawdown = peak - equity
        if drawdown > 0:
            underwater_sessions += 1
            underwater_streak += 1
            longest_underwater = max(longest_underwater, underwater_streak)
        else:
            underwater_streak = 0
        if drawdown > max_dd:
            max_dd = drawdown
            dd_peak = peak
            dd_peak_date = peak_date
            trough = equity
            trough_date = point["date"]
            trough_index = index

    recovered = False
    recovery_index: int | None = None
    for index in range(trough_index + 1, len(daily)):
        if float(daily[index]["equity"]) >= dd_peak:
            recovered = True
            recovery_index = index
            break

    if recovery_index is None:
        recovery_sessions = len(daily) - 1 - trough_index
        recovery_date = None
    else:
        recovery_sessions = recovery_index - trough_index
        recovery_date = daily[recovery_index]["date"]

    final_equity = float(daily[-1]["equity"])
    current_dd = peak - final_equity
    current_tuw = 0
    for point in reversed(daily):
        if float(point["equity"]) < peak:
            current_tuw += 1
        else:
            break

    net = float(result["aggregate"]["net_profit"])
    blocks = {block["window"]: block for block in result["blocks"]}
    w4_net = float(blocks["W4"]["net_profit"])
    ex_w4 = round(net - w4_net, 2)
    positive_blocks = sum(1 for block in result["blocks"] if block["net_profit"] > 0)
    net_dd = (net / max_dd) if max_dd > 0 else None

    # Comprobaciones de integridad: la curva diaria debe reproducir el agregado.
    if abs(final_equity - float(result["aggregate"]["final_equity"])) > 0.01:
        raise ValueError(f"{name}: equity final no coincide con el agregado")
    if abs(max_dd - float(result["aggregate"]["max_drawdown"])) > 0.01:
        raise ValueError(f"{name}: DD diario no coincide con el agregado")
    if abs(net - (final_equity - initial)) > 0.01:
        raise ValueError(f"{name}: neto no coincide con la equity")

    gates = {
        "P1_net_positive": net > 0,
        "P2_concentration": ex_w4 > 0 and positive_blocks >= CRITERIA["positive_blocks_min"],
        "P3_drawdown": max_dd <= CRITERIA["dd_max_usd"],
        "P4_underwater": (underwater_sessions / len(daily) * 100) <= CRITERIA["tuw_max_pct"],
        "P5_recovery": recovered and recovery_sessions <= CRITERIA["recovery_max_sessions"],
        "P6_net_dd": net_dd is not None and net_dd >= CRITERIA["net_dd_min"],
    }
    core_gates = all(gates[key] for key in ("P1_net_positive", "P2_concentration", "P3_drawdown", "P6_net_dd"))
    tier = "A" if all(gates.values()) else ("B" if core_gates else "C")
    score = sum(1 for passed in gates.values() if passed)

    return {
        "preset": name,
        "trades": int(result["aggregate"]["trades"]),
        "net": round(net, 2),
        "final_equity": round(final_equity, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / dd_peak * 100, 3) if dd_peak else 0.0,
        "dd_peak_equity": round(dd_peak, 2),
        "dd_peak_date": dd_peak_date,
        "dd_trough_equity": round(trough, 2),
        "dd_trough_date": trough_date,
        "dd_duration_sessions": trough_index - peak_index,
        "tuw_sessions": underwater_sessions,
        "tuw_pct": round(underwater_sessions / len(daily) * 100, 2),
        "longest_tuw_sessions": longest_underwater,
        "max_dd_recovered": recovered,
        "recovery_sessions": recovery_sessions,
        "recovery_date": recovery_date,
        "end_drawdown": round(current_dd, 2),
        "end_tuw_sessions": current_tuw,
        "net_dd": round(net_dd, 3) if net_dd is not None else None,
        "positive_blocks": positive_blocks,
        "ex_w4": ex_w4,
        "w4_net": round(w4_net, 2),
        "score": score,
        "gates": gates,
        "tier": tier,
        "promotion": tier == "A",
        "g4_sample": int(result["aggregate"]["trades"]) >= 80,
    }


def build_payload(source: dict[str, Any]) -> dict[str, Any]:
    initial = float(source["initial_capital"])
    rows = {
        key: score_preset(key, result, initial)
        for key, result in source["results"].items()
    }
    return {
        "schema": SCHEMA,
        "source": "reports/backtest/equity_continuous_dev.json",
        "created_ts": source.get("created_ts"),
        "initial_capital": initial,
        "sessions": source.get("sessions"),
        "holdout_executed": bool(source.get("holdout_executed")),
        "criteria": CRITERIA,
        "results": rows,
        "summary": {
            "presets": len(rows),
            "tier_a": sum(1 for row in rows.values() if row["tier"] == "A"),
            "tier_b": sum(1 for row in rows.values() if row["tier"] == "B"),
            "tier_c": sum(1 for row in rows.values() if row["tier"] == "C"),
        },
    }


def write_csv(payload: dict[str, Any], target: Path) -> None:
    fields = [
        "preset",
        "trades",
        "net",
        "max_drawdown",
        "max_drawdown_pct",
        "tuw_sessions",
        "tuw_pct",
        "longest_tuw_sessions",
        "max_dd_recovered",
        "recovery_sessions",
        "recovery_date",
        "end_drawdown",
        "end_tuw_sessions",
        "net_dd",
        "positive_blocks",
        "ex_w4",
        "score",
        "tier",
        "promotion",
    ]
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in payload["results"].values():
            writer.writerow({field: row.get(field) for field in fields})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--csv-out", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    if source.get("holdout_executed"):
        raise SystemExit("La fuente contiene holdout ejecutado; no se procesa")
    payload = build_payload(source)
    args.json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(payload, args.csv_out)

    print("preset,trades,net,dd,tuw_pct,recovery_sessions,net_dd,tier")
    for row in payload["results"].values():
        print(
            f"{row['preset']},{row['trades']},{row['net']:.2f},"
            f"{row['max_drawdown']:.2f},{row['tuw_pct']:.2f},"
            f"{row['recovery_sessions']},{row['net_dd']},{row['tier']}"
        )
    print(f"summary {payload['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
