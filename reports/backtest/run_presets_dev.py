"""Ejecuta los presets default sobre los bloques de desarrollo W1-W6.

El CSV de ``profiles/backtest_real/config.json`` termina el 2026-06-30, así que
el holdout no forma parte del dataset. Cada bloque se ejecuta en un proceso
independiente sobre el mismo perfil y dataset; el resultado agregado se guarda
en ``reports/backtest/presets_default_dev.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from _windows import WINDOW_FIRST, WINDOWS  # noqa: E402
from server.backtest import DEFAULT_PRESETS, resolve_presets, run_presets  # noqa: E402
from server.config import Settings  # noqa: E402

PROFILE = ROOT / "profiles/backtest_real/config.json"
OUT = ROOT / "reports/backtest/presets_default_dev.json"
DEVELOPMENT_END = WINDOWS[-1][2]
DEFAULT_DATASET_PATH = "data/real/bars_mnq_nq_es_1m.csv"
SCHEMA = "presets-default-dev-v2"


def _settings() -> Settings:
    return Settings.model_validate_json(PROFILE.read_text(encoding="utf-8"))


def _ratio(numerator: float, denominator: float, digits: int = 2) -> float | None:
    return round(numerator / denominator, digits) if denominator else None


def _profit_factor_status(trades: int, gross_profit: float, gross_loss: float) -> str:
    """Distingue PF finito, infinito, 0/0 y muestra vacía."""
    if trades == 0:
        return "no_trades"
    if gross_loss < 0:
        return "ok"
    if gross_profit > 0:
        return "no_losses"
    return "no_pnl"


def _normalise_row(row: dict) -> dict:
    """Recalcula ratios y marca explícitamente los casos indefinidos."""
    trades = int(row["trades"])
    wins = int(row["wins"])
    gross_profit = float(row["gross_profit"])
    gross_loss = float(row["gross_loss"])
    net_profit = float(row["net_profit"])
    stop_losses = int(row["stop_losses"])
    status = _profit_factor_status(trades, gross_profit, gross_loss)
    return {
        **row,
        "trades": trades,
        "wins": wins,
        "losses": int(row["losses"]),
        "breakeven": int(row["breakeven"]),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_profit": round(net_profit, 2),
        "win_rate": _ratio(wins * 100, trades),
        "profit_factor": (
            round(gross_profit / abs(gross_loss), 2) if status == "ok" else None
        ),
        "profit_factor_status": status,
        "expectancy": _ratio(net_profit, trades),
        "max_drawdown": round(float(row["max_drawdown"]), 2),
        "max_drawdown_pct": round(float(row["max_drawdown_pct"]), 2),
        "avg_stop_ticks": (
            round(float(row["avg_stop_ticks"]), 1)
            if row.get("avg_stop_ticks") is not None
            else None
        ),
        "stop_losses": stop_losses,
        "stop_loss_rate": _ratio(stop_losses * 100, trades),
        "stop_cap_sessions": int(row["stop_cap_sessions"]),
        "qty_zero_sessions": int(row["qty_zero_sessions"]),
        "signals": int(row["signals"]),
        "sessions": int(row["sessions"]),
    }


def _row_from_result(result: dict, sessions: int) -> dict:
    metrics = result["metrics"]
    config = result.get("config") or {}
    strategy = config.get("strategy") or {}
    risk = config.get("risk") or {}
    return _normalise_row(
        {
            "preset": result["preset"],
            "label": result["preset_label"],
            "group": result["preset_group"],
            "trades": metrics["trades"],
            "wins": metrics["wins"],
            "losses": metrics["losses"],
            "breakeven": metrics["breakeven"],
            "gross_profit": metrics["gross_profit"],
            "gross_loss": metrics["gross_loss"],
            "net_profit": metrics["net_profit"],
            "max_drawdown": metrics["max_drawdown"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "stop_losses": metrics.get("stop_losses", 0),
            "stop_cap_sessions": metrics.get("stop_cap_sessions", 0),
            "qty_zero_sessions": metrics.get("qty_zero_sessions", 0),
            "signals": metrics.get("signals", 0),
            "breakouts": metrics.get("breakouts", 0),
            "retests": metrics.get("retests", 0),
            "avg_stop_ticks": metrics.get("avg_stop_ticks", 0.0),
            "max_sl_ticks": risk.get("max_sl_ticks"),
            "entry_reference": strategy.get("entry_reference"),
            "risk_per_trade_pct": risk.get("risk_per_trade_pct"),
            "max_contracts": risk.get("max_contracts"),
            "initial_capital": risk.get("initial_capital"),
            "sessions": sessions,
        }
    )


def run_window(
    window: tuple[str, str, str, int],
    presets: Sequence[str] = DEFAULT_PRESETS,
) -> dict:
    key, start_s, end_s, days = window
    started = time.perf_counter()
    result = run_presets(
        _settings(),
        days=days,
        presets=presets,
        start=date.fromisoformat(start_s),
    )

    if result["is_synthetic"] or result["data_source"] != "csv":
        raise RuntimeError(f"{key}: se esperaba CSV real, no {result['data_source']}")
    selected = result["dataset"].get("selected_range") or {}
    first = (selected.get("first_et") or "")[:10]
    last = (selected.get("last_et") or "")[:10]
    if result["sessions"] != days:
        raise RuntimeError(f"{key}: {result['sessions']} sesiones, se esperaban {days}")
    if first != WINDOW_FIRST[key]:
        raise RuntimeError(
            f"{key}: primera sesión {first}, se esperaba {WINDOW_FIRST[key]}"
        )
    if last != end_s:
        raise RuntimeError(f"{key}: última sesión {last}, se esperaba {end_s}")
    if last > DEVELOPMENT_END:
        raise RuntimeError(f"{key}: se tocó el holdout ({last})")

    expected = tuple(resolve_presets(presets))
    if tuple(result["preset_keys"]) != expected:
        raise RuntimeError(
            f"{key}: presets inesperados {result['preset_keys']}, "
            f"se esperaban {list(expected)}"
        )
    rows = [
        _row_from_result(item, result["sessions"]) for item in result["results"]
    ]
    if tuple(row["preset"] for row in rows) != expected:
        raise RuntimeError(f"{key}: el orden de los presets no coincide con el catálogo")

    elapsed = round(time.perf_counter() - started, 1)
    print(
        f"[{key}] {result['sessions']} sesiones {first}..{last} en {elapsed}s",
        flush=True,
    )
    return {
        "window": key,
        "start": start_s,
        "end": end_s,
        "days": days,
        "actual_first": first,
        "actual_last": last,
        "elapsed_s": elapsed,
        "dataset_id": result.get("dataset_id"),
        "dataset_path": result["dataset"].get("path"),
        "selected_id": result["dataset"].get("selected_id"),
        "rows": rows,
    }


def aggregate(
    per_window: list[dict],
    presets: Sequence[str] = DEFAULT_PRESETS,
) -> list[dict]:
    expected = tuple(resolve_presets(presets))
    by_preset: dict[str, list[dict]] = {}
    for block in per_window:
        for row in block["rows"]:
            by_preset.setdefault(row["preset"], []).append(row)

    missing = [key for key in expected if key not in by_preset]
    if missing:
        raise ValueError(f"Faltan presets en el informe: {', '.join(missing)}")

    aggregate_rows: list[dict] = []
    for key in expected:
        rows = by_preset[key]
        if len(rows) != len(per_window):
            raise ValueError(
                f"{key}: {len(rows)} bloques, se esperaban {len(per_window)}"
            )

        trades = sum(row["trades"] for row in rows)
        wins = sum(row["wins"] for row in rows)
        losses = sum(row["losses"] for row in rows)
        breakeven = sum(row["breakeven"] for row in rows)
        gross_profit = sum(row["gross_profit"] for row in rows)
        gross_loss = sum(row["gross_loss"] for row in rows)
        net_profit = sum(row["net_profit"] for row in rows)
        stop_losses = sum(row["stop_losses"] for row in rows)
        stop_caps = sum(row["stop_cap_sessions"] for row in rows)
        qty_zero = sum(row["qty_zero_sessions"] for row in rows)
        breakouts = sum(row.get("breakouts", 0) for row in rows)
        retests = sum(row.get("retests", 0) for row in rows)
        stop_ticks_complete = all(
            row.get("avg_stop_ticks") is not None for row in rows
        )
        avg_stop_ticks = (
            round(
                sum(row["avg_stop_ticks"] * row["trades"] for row in rows)
                / trades,
                1,
            )
            if trades and stop_ticks_complete
            else None
        )
        status = _profit_factor_status(trades, gross_profit, gross_loss)
        worst = max(rows, key=lambda row: row["max_drawdown"])

        aggregate_rows.append(
            {
                "preset": key,
                "label": rows[0]["label"],
                "group": rows[0]["group"],
                "sessions": sum(row["sessions"] for row in rows),
                "blocks": len(rows),
                "blocks_with_trades": sum(1 for row in rows if row["trades"] > 0),
                "signals": sum(row["signals"] for row in rows),
                "breakouts": breakouts,
                "retests": retests,
                "trades": trades,
                "wins": wins,
                "losses": losses,
                "breakeven": breakeven,
                "gross_profit": round(gross_profit, 2),
                "gross_loss": round(gross_loss, 2),
                "net_profit": round(net_profit, 2),
                "win_rate": _ratio(wins * 100, trades),
                "profit_factor": (
                    round(gross_profit / abs(gross_loss), 2)
                    if status == "ok"
                    else None
                ),
                "profit_factor_status": status,
                "expectancy": _ratio(net_profit, trades),
                "max_drawdown_worst": round(worst["max_drawdown"], 2),
                "max_drawdown_pct_at_worst": round(worst["max_drawdown_pct"], 2),
                "max_drawdown_mean": round(
                    fmean(row["max_drawdown"] for row in rows), 2
                ),
                "stop_losses": stop_losses,
                "stop_loss_rate": _ratio(stop_losses * 100, trades),
                "avg_stop_ticks": avg_stop_ticks,
                "stop_cap_sessions": stop_caps,
                "qty_zero_sessions": qty_zero,
                "max_sl_ticks": rows[0].get("max_sl_ticks"),
                "entry_reference": rows[0].get("entry_reference"),
                "risk_per_trade_pct": rows[0].get("risk_per_trade_pct"),
                "max_contracts": rows[0].get("max_contracts"),
                "initial_capital": rows[0].get("initial_capital"),
            }
        )
    return aggregate_rows


def _pf_text(row: dict) -> str:
    if row["profit_factor_status"] == "no_losses":
        return "inf"
    if row["profit_factor_status"] == "ok":
        return f"{row['profit_factor']:.2f}"
    return "n/a"


def _num_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _pct_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta presets sobre los bloques de desarrollo W1-W6. "
            "No usa el holdout ni modifica la configuración activa."
        )
    )
    parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="Clave de preset; se puede repetir. Sin argumento usa los default.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="JSON de salida; sin ruta usa el informe default o un timestamp.",
    )
    args = parser.parse_args(argv)
    try:
        keys = resolve_presets(args.preset or DEFAULT_PRESETS)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    default_run = keys == list(DEFAULT_PRESETS)
    schema = SCHEMA if default_run else "presets-optin-dev-v2"
    if args.out:
        target = Path(args.out)
    elif default_run:
        target = OUT
    else:
        target = (
            ROOT
            / "reports/backtest"
            / f"presets_optin_{time.strftime('%Y%m%d_%H%M%S')}.json"
        )

    started = time.perf_counter()
    per_window: list[dict] = []
    with ProcessPoolExecutor(max_workers=len(WINDOWS)) as pool:
        futures = {
            pool.submit(run_window, window, keys): window for window in WINDOWS
        }
        for future in as_completed(futures):
            window = futures[future]
            try:
                per_window.append(future.result())
            except Exception:
                print(f"[{window[0]}] FALLÓ", flush=True)
                traceback.print_exc()
                return 1

    per_window.sort(key=lambda item: item["window"])
    aggregate_rows = aggregate(per_window, keys)
    payload = {
        "schema": schema,
        "created_ts": int(time.time() * 1000),
        "profile": str(PROFILE.relative_to(ROOT)).replace("\\", "/"),
        "dataset_path": per_window[0].get("dataset_path") or DEFAULT_DATASET_PATH,
        "dataset_id": per_window[0].get("dataset_id"),
        "development_end": DEVELOPMENT_END,
        "holdout_executed": False,
        "presets": list(keys),
        "windows": [
            {key: value for key, value in block.items() if key != "rows"}
            for block in per_window
        ],
        "per_window": per_window,
        "aggregate": aggregate_rows,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Escrito {target} en {payload['elapsed_s']}s", flush=True)
    print(
        "preset,trades,signals,win_rate,pf,expectancy,net_profit,"
        "dd_worst,dd_worst_pct,dd_mean,sl_rate,stop_caps,qty0",
        flush=True,
    )
    for row in aggregate_rows:
        print(
            f"{row['preset']},{row['trades']},{row['signals']},"
            f"{_pct_text(row['win_rate'])},{_pf_text(row)},"
            f"{_num_text(row['expectancy'])},{row['net_profit']:.2f},"
            f"{row['max_drawdown_worst']:.2f},"
            f"{row['max_drawdown_pct_at_worst']:.2f},"
            f"{row['max_drawdown_mean']:.2f},"
            f"{_pct_text(row['stop_loss_rate'])},"
            f"{row['stop_cap_sessions']},{row['qty_zero_sessions']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
