"""Curva de equity continua de desarrollo para los presets default.

Simula W1-W6 como una sola secuencia de 362 sesiones, de modo que el capital
cerrado en una ventana se arrastra a la siguiente. No toca la configuración
activa ni el holdout. Guarda el detalle diario, la curva por trade y el DD
agregado y por bloque.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.backtest as bt  # noqa: E402
from _windows import WINDOWS as CANONICAL_WINDOWS, window_date_ranges  # noqa: E402
from server.config import Settings, apply_settings  # noqa: E402
from server.timeutil import et_date  # noqa: E402

PROFILE = ROOT / "profiles/backtest_real/config.json"
OUT = ROOT / "reports/backtest/equity_continuous_dev.json"
CSV_OUT = ROOT / "reports/backtest/equity_continuous_dev.csv"
START = date.fromisoformat(CANONICAL_WINDOWS[0][1])
END = date.fromisoformat(CANONICAL_WINDOWS[-1][2])
DAYS = sum(spec[3] for spec in CANONICAL_WINDOWS)
INITIAL_CAPITAL = 25_000.0
SCHEMA = "equity-continuous-dev-v1"

# Representación con date de la única definición en _windows.py.
BLOCK_RANGES: tuple[tuple[str, date, date], ...] = window_date_ranges()

# Cuatro cargas del CSV, repartidas para no mantener once copias del dataset.
GROUPS: tuple[tuple[str, ...], ...] = (
    ("baseline", "entry_breakout_direct", "entry_or_level"),
    ("entry_retrace_382", "smt_window_120", "smt_tolerance_16"),
    ("setup_validity_240", "sl_depth_6", "sl_buffer_12"),
    ("recovery_off", "rr_2_5"),
)


def _settings() -> Settings:
    return Settings.model_validate_json(PROFILE.read_text(encoding="utf-8"))


def _window_for(day: date) -> str:
    for key, start, end in BLOCK_RANGES:
        if start <= day <= end:
            return key
    raise ValueError(f"Fecha fuera de desarrollo: {day}")


def _load_sessions(settings: Settings) -> tuple[list, str, dict[str, Any]]:
    """Carga las 362 sesiones de desarrollo sin cambiar el límite del runner."""
    original_max = bt.MAX_BACKTEST_DAYS
    bt.MAX_BACKTEST_DAYS = DAYS
    try:
        sessions, source, dataset = bt.prepare_dataset(
            settings, days=DAYS, start=START
        )
    finally:
        bt.MAX_BACKTEST_DAYS = original_max

    if source != "csv" or not sessions:
        raise RuntimeError(f"Se esperaba CSV real; recibido {source}")
    if len(sessions) != DAYS:
        raise RuntimeError(f"{len(sessions)} sesiones, se esperaban {DAYS}")
    if sessions[0][0] != START or sessions[-1][0] > END:
        raise RuntimeError(
            f"Rango inesperado: {sessions[0][0]}..{sessions[-1][0]}"
        )
    return sessions, source, dataset


def _curve_stats(
    points: list[dict[str, Any]], initial: float
) -> dict[str, Any]:
    """Calcula peak, trough y drawdown sobre una secuencia de equity."""
    peak = initial
    peak_date = points[0]["date"] if points else None
    high = initial
    high_date = peak_date
    max_dd = 0.0
    max_dd_pct = 0.0
    trough = initial
    trough_date = peak_date
    dd_peak = initial
    dd_peak_date = peak_date
    for point in points:
        equity = float(point["equity"])
        if equity > peak:
            peak = equity
            peak_date = point["date"]
        if equity > high:
            high = equity
            high_date = point["date"]
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = (dd / peak * 100) if peak else 0.0
            trough = equity
            trough_date = point["date"]
            dd_peak = peak
            dd_peak_date = peak_date
    return {
        "peak_equity": round(high, 2),
        "peak_date": high_date,
        "drawdown_peak_equity": round(dd_peak, 2),
        "drawdown_peak_date": dd_peak_date,
        "trough_equity": round(trough, 2),
        "trough_date": trough_date,
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 3),
    }


def _summarise(
    key: str,
    preset: dict[str, Any],
    result: dict[str, Any],
    sessions: list,
) -> dict[str, Any]:
    metrics = result["metrics"]
    initial = float(result["config"]["risk"]["initial_capital"])
    trades = sorted(
        result["trades"],
        key=lambda trade: int(trade["exit_ts"]),
    )

    trade_points: list[dict[str, Any]] = [
        {
            "ts": None,
            "date": START.isoformat(),
            "block": "W1",
            "equity": round(initial, 2),
        }
    ]
    equity = initial
    for trade in trades:
        exit_ts = int(trade["exit_ts"])
        day = et_date(exit_ts)
        block = _window_for(day)
        equity += float(trade["pnl"])
        trade_points.append(
            {
                "ts": exit_ts,
                "date": day.isoformat(),
                "block": block,
                "equity": round(equity, 2),
            }
        )

    aggregate_stats = _curve_stats(trade_points, initial)
    final_equity = round(equity, 2)
    expected_final = round(float(metrics["net_profit"]) + initial, 2)
    if abs(final_equity - expected_final) > 0.01:
        raise RuntimeError(
            f"{key}: equity final {final_equity} != métricas {expected_final}"
        )
    if abs(aggregate_stats["max_drawdown"] - float(metrics["max_drawdown"])) > 0.01:
        raise RuntimeError(
            f"{key}: DD reconstruido {aggregate_stats['max_drawdown']} "
            f"!= métricas {metrics['max_drawdown']}"
        )

    # DD de cada tramo con el capital que entra en la ventana. El peak se
    # reinicia al inicio del bloque; el DD agregado conserva el peak global.
    blocks: list[dict[str, Any]] = []
    cursor = initial
    for block_key, block_start, block_end in BLOCK_RANGES:
        block_trades = [
            trade
            for trade in trades
            if block_start <= et_date(int(trade["exit_ts"])) <= block_end
        ]
        block_points = [
            {
                "ts": None,
                "date": block_start.isoformat(),
                "block": block_key,
                "equity": round(cursor, 2),
            }
        ]
        for trade in block_trades:
            exit_ts = int(trade["exit_ts"])
            cursor += float(trade["pnl"])
            block_points.append(
                {
                    "ts": exit_ts,
                    "date": et_date(exit_ts).isoformat(),
                    "block": block_key,
                    "equity": round(cursor, 2),
                }
            )
        block_stats = _curve_stats(block_points, block_points[0]["equity"])
        blocks.append(
            {
                "window": block_key,
                "start": block_start.isoformat(),
                "end": block_end.isoformat(),
                "start_equity": round(block_points[0]["equity"], 2),
                "end_equity": round(cursor, 2),
                "net_profit": round(cursor - block_points[0]["equity"], 2),
                "trades": len(block_trades),
                **block_stats,
            }
        )

    if abs(cursor - final_equity) > 0.01:
        raise RuntimeError(f"{key}: los bloques no suman la equity final")

    days_detail = sorted(result["days_detail"], key=lambda item: item["date"])
    if len(days_detail) != DAYS:
        raise RuntimeError(f"{key}: {len(days_detail)} días, se esperaban {DAYS}")
    daily_equity: list[dict[str, Any]] = []
    daily_peak = initial
    for item in days_detail:
        day = date.fromisoformat(item["date"])
        block = _window_for(day)
        day_equity = float(item["equity"])
        daily_peak = max(daily_peak, day_equity)
        drawdown = daily_peak - day_equity
        daily_equity.append(
            {
                "date": day.isoformat(),
                "block": block,
                "equity": round(day_equity, 2),
                "drawdown": round(drawdown, 2),
                "drawdown_pct": round(
                    drawdown / daily_peak * 100 if daily_peak else 0.0, 3
                ),
            }
        )

    if abs(daily_equity[-1]["equity"] - final_equity) > 0.01:
        raise RuntimeError(
            f"{key}: curva diaria termina en {daily_equity[-1]['equity']} "
            f"y no en {final_equity}"
        )

    return {
        "preset": key,
        "label": preset["label"],
        "group": preset["group"],
        "patch": preset["patch"],
        "aggregate": {
            "trades": int(metrics["trades"]),
            "net_profit": round(float(metrics["net_profit"]), 2),
            "final_equity": final_equity,
            "win_rate": metrics["win_rate"],
            "profit_factor": metrics["profit_factor"],
            "expectancy": metrics["expectancy"],
            "max_drawdown": metrics["max_drawdown"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "equity_trough": metrics["equity_trough"],
            **aggregate_stats,
        },
        "blocks": blocks,
        "daily_equity": daily_equity,
        "trade_equity": trade_points,
    }


def _run_group(keys: tuple[str, ...]) -> dict[str, Any]:
    settings = _settings()
    started = time.perf_counter()
    sessions, source, dataset = _load_sessions(settings)
    print(
        f"[worker] {len(keys)} presets, {len(sessions)} sesiones, "
        f"carga {round(time.perf_counter() - started, 1)}s",
        flush=True,
    )
    output: dict[str, Any] = {}
    for key in keys:
        preset = bt.PRESETS[key]
        cfg = apply_settings(settings, preset["patch"])
        preset_started = time.perf_counter()
        result = bt._simulate(
            cfg,
            sessions,
            source,
            preset["label"],
            dataset,
        )
        output[key] = _summarise(key, preset, result, sessions)
        print(
            f"[{key}] {output[key]['aggregate']['trades']} ops, "
            f"neto {output[key]['aggregate']['net_profit']}, "
            f"DD {output[key]['aggregate']['max_drawdown']} "
            f"en {round(time.perf_counter() - preset_started, 1)}s",
            flush=True,
        )
    return output


def main() -> int:
    started = time.perf_counter()
    results: dict[str, Any] = {}
    with ProcessPoolExecutor(max_workers=len(GROUPS)) as pool:
        futures = {pool.submit(_run_group, group): group for group in GROUPS}
        for future in as_completed(futures):
            group = futures[future]
            try:
                results.update(future.result())
            except Exception:
                print(f"FALLÓ el grupo {group}", flush=True)
                traceback.print_exc()
                return 1

    missing = [key for key in bt.DEFAULT_PRESETS if key not in results]
    if missing:
        raise RuntimeError(f"Faltan presets: {', '.join(missing)}")

    payload = {
        "schema": SCHEMA,
        "created_ts": int(time.time() * 1000),
        "profile": str(PROFILE.relative_to(ROOT)).replace("\\", "/"),
        "start": START.isoformat(),
        "end": END.isoformat(),
        "sessions": DAYS,
        "initial_capital": INITIAL_CAPITAL,
        "holdout_executed": False,
        "windows": [
            {"window": key, "start": start.isoformat(), "end": end.isoformat()}
            for key, start, end in BLOCK_RANGES
        ],
        "presets": list(bt.DEFAULT_PRESETS),
        "results": {
            key: results[key] for key in bt.DEFAULT_PRESETS
        },
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with CSV_OUT.open("w", encoding="utf-8", newline="") as handle:
        handle.write("preset,date,block,equity,drawdown,drawdown_pct\n")
        for key in bt.DEFAULT_PRESETS:
            for point in results[key]["daily_equity"]:
                handle.write(
                    f"{key},{point['date']},{point['block']},"
                    f"{point['equity']:.2f},{point['drawdown']:.2f},"
                    f"{point['drawdown_pct']:.3f}\n"
                )

    print(
        f"Escrito {OUT} y {CSV_OUT} en {payload['elapsed_s']}s",
        flush=True,
    )
    print(
        "preset,ops,neto,final,DD,DD_pct,win_rate,pf",
        flush=True,
    )
    for key in bt.DEFAULT_PRESETS:
        row = results[key]["aggregate"]
        print(
            f"{key},{row['trades']},{row['net_profit']:.2f},"
            f"{row['final_equity']:.2f},{row['max_drawdown']:.2f},"
            f"{row['max_drawdown_pct']:.3f},{row['win_rate']:.2f},"
            f"{row['profit_factor']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
