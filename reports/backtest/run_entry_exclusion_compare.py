"""Compara W1-W6 con la exclusión de entradas apagada y con [11:00, 13:00).

Configuración fija: lock congelado + validez 240 min, tolerancia 12 ticks y
max_sl_ticks 300. No modifica data/config.json ni ejecuta el holdout.

El CSV se carga una sola vez por grupo de ventanas para no releerlo en cada
una de las doce simulaciones. Cada resultado se simula con el mismo motor y
la misma muestra; solo cambia entry_exclusion_start/end.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.backtest as bt
from _windows import WINDOW_IDS, WINDOWS
from server.config import Settings, apply_settings
from server.stats import compute_stats
from server.timeutil import et_minutes

LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
OUT_PATH = ROOT / "reports/backtest/entry_exclusion_11_13_compare.json"
HOLDOUT_START = date(2026, 7, 1)
GROUPS = (("W1", "W2"), ("W3",), ("W4",), ("W5", "W6"))
CONFIGS = ((False, "off"), (True, "on"))
EXCLUSION_START = "11:00"
EXCLUSION_END = "13:00"
EXCLUSION_START_MIN = 11 * 60
EXCLUSION_END_MIN = 13 * 60
BASE_OVERRIDES = {
    "strategy": {"setup_validity_minutes": 240, "retest_tolerance_ticks": 12},
    "risk": {"max_sl_ticks": 300},
}


def _load_lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _config_patch(active: bool) -> dict[str, Any]:
    patch = json.loads(json.dumps(BASE_OVERRIDES))
    patch["risk"]["entry_exclusion_start"] = EXCLUSION_START if active else ""
    patch["risk"]["entry_exclusion_end"] = EXCLUSION_END if active else ""
    return patch


def _window_dataset(
    dataset: dict[str, Any], sessions: list[tuple[date, dict[str, list[Any]]]]
) -> dict[str, Any]:
    """Copia la procedencia del grupo limitada a las sesiones de una ventana."""
    window = dict(dataset)
    contracts = dataset.get("contracts") or {}
    selected_contracts = {
        symbol: sorted(contracts.get(symbol, [])) for symbol in bt.REQUIRED_SYMBOLS
    }
    hash_meta: dict[str, Any] = {
        "kind": "csv-selected",
        "contracts": selected_contracts,
    }
    if (
        dataset.get("contracts_declared")
        or dataset.get("series_mode") != "adjusted"
        or dataset.get("roll_sessions")
        or dataset.get("excluded_sessions")
    ):
        hash_meta.update(
            {
                "series_id": dataset.get("series_id"),
                "series_mode": dataset.get("series_mode"),
                "roll_sessions": dataset.get("roll_sessions") or [],
                "excluded_sessions": dataset.get("excluded_sessions") or [],
            }
        )
    window["selected_id"] = bt._hash_sessions(sessions, hash_meta)
    window["selected_range"] = bt._session_range(sessions)
    window["sessions"] = {
        "count": len(sessions),
        "available": len(dataset.get("all_sessions") or []),
        "excluded": len(dataset.get("excluded_sessions") or []),
        "dates": [day.isoformat() for day, _ in sessions],
    }
    window["requested_start"] = sessions[0][0].isoformat()
    window["selection"] = "start_date"
    return window


def _summary(trades: list[dict[str, Any]], initial_capital: float) -> dict[str, Any]:
    stats = compute_stats(trades, initial_capital)
    total = int(stats.get("trades") or 0)
    stop_losses = sum(
        1 for trade in trades if str(trade.get("exit_reason") or "") == "stop_loss"
    )
    return {
        "trades": total,
        "wins": int(stats.get("wins") or 0),
        "losses": int(stats.get("losses") or 0),
        "win_rate": stats.get("win_rate", 0.0),
        "profit_factor": stats.get("profit_factor"),
        "net_profit": stats.get("net_profit", 0.0),
        "expectancy": stats.get("expectancy", 0.0),
        "avg_r": stats.get("avg_r", 0.0),
        "max_drawdown": stats.get("max_drawdown", 0.0),
        "max_drawdown_pct": stats.get("max_drawdown_pct", 0.0),
        "stop_losses": stop_losses,
        "stop_loss_rate": round(stop_losses / total * 100, 2) if total else 0.0,
    }


def _run_group(keys: tuple[str, ...]) -> dict[tuple[str, str], dict[str, Any]]:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    windows_by_id = {window["id"]: window for window in lock["windows"]}
    group_windows = [windows_by_id[key] for key in keys]
    start = date.fromisoformat(group_windows[0]["start"])
    days = sum(int(window["sessions"]) for window in group_windows)

    started = time.perf_counter()
    sessions, source, dataset = bt.prepare_dataset(
        base, days, start, allow_holdout=False
    )
    if source != "csv":
        raise RuntimeError(f"Se esperaba el CSV real; recibido {source!r}")
    group_first_end = date.fromisoformat(group_windows[0]["end"])
    if not (start <= sessions[0][0] <= group_first_end):
        raise RuntimeError(
            f"Primera sesión {sessions[0][0]} fuera del primer bloque "
            f"({start}..{group_first_end})"
        )
    if sessions[-1][0] >= HOLDOUT_START:
        raise RuntimeError(f"El CSV alcanza el holdout: {sessions[-1][0]}")
    print(
        f"[{keys[0]}..{keys[-1]}] {len(sessions)} sesiones cargadas en "
        f"{time.perf_counter() - started:.1f}s",
        flush=True,
    )

    output: dict[tuple[str, str], dict[str, Any]] = {}
    for window in group_windows:
        window_start = date.fromisoformat(window["start"])
        window_end = date.fromisoformat(window["end"])
        window_sessions = [
            (day, data)
            for day, data in sessions
            if window_start <= day <= window_end
        ]
        if len(window_sessions) != int(window["sessions"]):
            raise RuntimeError(
                f"{window['id']}: {len(window_sessions)} sesiones, "
                f"se esperaban {window['sessions']}"
            )
        # El inicio del lock es calendario: puede ser festivo (W5 empieza el
        # 1 de enero y su primera sesión es el 2). Solo exigimos que todas las
        # sesiones caigan dentro del bloque.
        if not (
            window_start <= window_sessions[0][0] <= window_end
            and window_start <= window_sessions[-1][0] <= window_end
        ):
            raise RuntimeError(
                f"{window['id']}: rango inesperado "
                f"{window_sessions[0][0]}..{window_sessions[-1][0]}"
            )
        if window_sessions[-1][0] >= HOLDOUT_START:
            raise RuntimeError(f"{window['id']} toca el holdout")

        window_dataset = _window_dataset(dataset, window_sessions)
        for active, label in CONFIGS:
            config = apply_settings(base, _config_patch(active))
            simulation_started = time.perf_counter()
            result = bt._simulate(
                config,
                window_sessions,
                source,
                f"{window['id']}-{label}",
                window_dataset,
            )
            trades = [
                dict(trade, window=window["id"]) for trade in result["trades"]
            ]
            timezone = config.orb.timezone
            entry_minutes = sorted(
                {
                    et_minutes(int(trade["entry_ts"]), timezone)
                    for trade in trades
                }
            )
            entries_in_exclusion = sum(
                1
                for trade in trades
                if EXCLUSION_START_MIN
                <= et_minutes(int(trade["entry_ts"]), timezone)
                < EXCLUSION_END_MIN
            )
            output[(window["id"], label)] = {
                "window": window,
                "selected_range": window_dataset["selected_range"],
                "sessions": len(window_sessions),
                "metrics": _summary(trades, config.risk.initial_capital),
                "entries_in_exclusion": entries_in_exclusion,
                "entry_minutes": entry_minutes,
                "trades": trades,
                "dataset": {
                    "file_hash": window_dataset.get("file_hash"),
                    "dataset_id": window_dataset.get("id"),
                    "series_id": window_dataset.get("series_id"),
                    "selected_id": window_dataset.get("selected_id"),
                },
                "experiment": {
                    "config_sha256": result["experiment"]["config_sha256"],
                    "dataset_sha256": result["experiment"]["dataset_sha256"],
                    "selected_id": result["experiment"].get("selected_id"),
                },
                "elapsed_sec": round(time.perf_counter() - simulation_started, 1),
            }
            print(
                f"  {window['id']} {label}: "
                f"{len(trades)} ops, neto {result['metrics']['net_profit']}, "
                f"DD {result['metrics']['max_drawdown']}, "
                f"SL {result['metrics']['stop_loss_rate']}% en "
                f"{time.perf_counter() - simulation_started:.1f}s",
                flush=True,
            )
    return output


def _delta(off: dict[str, Any], on: dict[str, Any], key: str) -> float | None:
    left = off.get(key)
    right = on.get(key)
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return round(float(right) - float(left), 2)
    return None


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return f"{value:,}"


def _metrics_line(metrics: dict[str, Any]) -> str:
    return (
        f"ops {metrics['trades']:>3} | "
        f"neto {_fmt(metrics['net_profit']):>10} | "
        f"PF {_fmt(metrics['profit_factor']):>5} | "
        f"DD {_fmt(metrics['max_drawdown']):>9} "
        f"({_fmt(metrics['max_drawdown_pct']):>5}%) | "
        f"SL {metrics['stop_losses']:>2} "
        f"({_fmt(metrics['stop_loss_rate']):>5}%) | "
        f"win {_fmt(metrics['win_rate']):>5}%"
    )


def main() -> int:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    windows_by_id = {window["id"]: window for window in lock["windows"]}

    results: dict[tuple[str, str], dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=len(GROUPS)) as pool:
        futures = {pool.submit(_run_group, group): group for group in GROUPS}
        for future in as_completed(futures):
            group = futures[future]
            try:
                results.update(future.result())
            except Exception as exc:  # noqa: BLE001 - el informe debe fallar entero
                print(f"FALLÓ el grupo {group}: {exc}", flush=True)
                raise

    for window_id in WINDOW_IDS:
        off = results[(window_id, "off")]
        on = results[(window_id, "on")]
        expected_sessions = int(windows_by_id[window_id]["sessions"])
        if off["sessions"] != expected_sessions or on["sessions"] != expected_sessions:
            raise RuntimeError(f"{window_id}: sesiones distintas de las esperadas")
        if off["experiment"]["selected_id"] != on["experiment"]["selected_id"]:
            raise RuntimeError(f"{window_id}: la muestra cambió entre configuraciones")
        if off["experiment"]["dataset_sha256"] != on["experiment"]["dataset_sha256"]:
            raise RuntimeError(f"{window_id}: cambió el dataset entre configuraciones")
        if off["experiment"]["config_sha256"] == on["experiment"]["config_sha256"]:
            raise RuntimeError(f"{window_id}: la configuración no cambió")
        if on["entries_in_exclusion"] != 0:
            raise RuntimeError(
                f"{window_id}: {on['entries_in_exclusion']} entradas dentro de "
                f"[{EXCLUSION_START}, {EXCLUSION_END})"
            )
        if not (off["selected_range"] == on["selected_range"]):
            raise RuntimeError(f"{window_id}: rango seleccionado distinto")

    by_config: dict[str, dict[str, Any]] = {}
    for _, label in CONFIGS:
        all_trades = [
            trade
            for window_id in WINDOW_IDS
            for trade in results[(window_id, label)]["trades"]
        ]
        ex_w4_trades = [trade for trade in all_trades if trade["window"] != "W4"]
        by_config[label] = {
            "total": _summary(all_trades, base.risk.initial_capital),
            "by_window": {
                window_id: results[(window_id, label)]["metrics"]
                for window_id in WINDOW_IDS
            },
            "ex_w4": _summary(ex_w4_trades, base.risk.initial_capital),
            "entries_in_exclusion": sum(
                results[(window_id, label)]["entries_in_exclusion"]
                for window_id in WINDOW_IDS
            ),
        }

    baseline_entries = sum(
        results[(window_id, "off")]["entries_in_exclusion"]
        for window_id in WINDOW_IDS
    )
    filtered_entries = by_config["on"]["entries_in_exclusion"]
    if filtered_entries != 0:
        raise RuntimeError("El filtro dejó entradas dentro de la ventana")

    delta_by_window = {}
    for window_id in WINDOW_IDS:
        off_metrics = by_config["off"]["by_window"][window_id]
        on_metrics = by_config["on"]["by_window"][window_id]
        delta_by_window[window_id] = {
            key: _delta(off_metrics, on_metrics, key)
            for key in (
                "trades",
                "net_profit",
                "profit_factor",
                "max_drawdown",
                "max_drawdown_pct",
                "stop_losses",
                "stop_loss_rate",
                "win_rate",
            )
        }

    dataset_meta = results[(WINDOW_IDS[0], "off")]["dataset"]
    report = {
        "schema": "entry-exclusion-compare-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "source": "csv",
            "path": base.feed.csv_path,
            "file_hash": dataset_meta["file_hash"],
            "dataset_id": dataset_meta["dataset_id"],
            "series_id": dataset_meta["series_id"],
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_used": False,
            "development_sessions": sum(spec[3] for spec in WINDOWS),
            "development_range": {
                "first": WINDOWS[0][1],
                "last": WINDOWS[-1][2],
            },
        },
        "config": {
            "base": "docs/protocolo_backtest.lock.json",
            "setup_validity_minutes": 240,
            "retest_tolerance_ticks": 12,
            "max_sl_ticks": 300,
            "entry_exclusion": {
                "off": None,
                "on": {"start": EXCLUSION_START, "end": EXCLUSION_END, "end_inclusive": False},
            },
        },
        "windows": {
            window_id: windows_by_id[window_id] for window_id in WINDOW_IDS
        },
        "results": by_config,
        "comparison": {
            "delta_total": {
                key: _delta(by_config["off"]["total"], by_config["on"]["total"], key)
                for key in (
                    "trades",
                    "net_profit",
                    "profit_factor",
                    "max_drawdown",
                    "max_drawdown_pct",
                    "stop_losses",
                    "stop_loss_rate",
                    "win_rate",
                )
            },
            "delta_by_window": delta_by_window,
            "delta_ex_w4": {
                key: _delta(
                    by_config["off"]["ex_w4"], by_config["on"]["ex_w4"], key
                )
                for key in (
                    "trades",
                    "net_profit",
                    "profit_factor",
                    "max_drawdown",
                    "max_drawdown_pct",
                    "stop_losses",
                    "stop_loss_rate",
                    "win_rate",
                )
            },
            "baseline_entries_in_exclusion": baseline_entries,
            "filtered_entries_in_exclusion": filtered_entries,
        },
    }
    OUT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print()
    print("Comparación: exclusión de entradas [11:00, 13:00) ET")
    print(
        "Config: 240 min de validez, 12 ticks de tolerancia, "
        "max_sl_ticks 300 | holdout no usado"
    )
    print()
    for window_id in WINDOW_IDS:
        window = windows_by_id[window_id]
        print(f"{window_id} {window['start']}..{window['end']}")
        for _, label in CONFIGS:
            metrics = by_config[label]["by_window"][window_id]
            entries = results[(window_id, label)]["entries_in_exclusion"]
            suffix = (
                f" | entradas 11-13: {entries}"
                if label == "off"
                else " | entradas 11-13: 0"
            )
            print(f"  {label:<3} {_metrics_line(metrics)}{suffix}")
    print()
    for label in ("off", "on"):
        print(f"TOTAL {label}")
        print(f"  total {_metrics_line(by_config[label]['total'])}")
        print(f"  ex-W4 {_metrics_line(by_config[label]['ex_w4'])}")
    print(f"\nEntradas baseline dentro de [11:00, 13:00): {baseline_entries}")
    print(f"Entradas con filtro dentro de [11:00, 13:00): {filtered_entries}")
    print(f"Informe guardado en {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
