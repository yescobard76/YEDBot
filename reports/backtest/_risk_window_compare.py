"""Compara reglas de riesgo en W1-W6 sin tocar holdout ni configuración activa."""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.backtest import run_backtest  # noqa: E402
from server.config import Settings, apply_settings  # noqa: E402

LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
OUT = ROOT / "logs/risk_window_compare.json"
ET = ZoneInfo("America/New_York")
CONFIGS = [
    ("base", {}),
    ("loss2", {"no_trade_after_consecutive_losses": 2}),
    ("cd15", {"cooldown_minutes": 15}),
    ("cd30", {"cooldown_minutes": 30}),
    ("cd60", {"cooldown_minutes": 60}),
    ("loss2_cd15", {"no_trade_after_consecutive_losses": 2, "cooldown_minutes": 15}),
    ("loss2_cd30", {"no_trade_after_consecutive_losses": 2, "cooldown_minutes": 30}),
    ("loss2_cd60", {"no_trade_after_consecutive_losses": 2, "cooldown_minutes": 60}),
]


def _task_key(task: dict) -> str:
    return f"{task['config']}:{task['window']}"


def _run(task: dict) -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    settings = Settings.model_validate(lock["settings"])
    settings = apply_settings(
        settings,
        {
            "strategy": {"use_smt": True, "entry_reference": "or_mid"},
            "risk": task["risk"],
        },
    )
    result = run_backtest(
        settings,
        days=task["sessions"],
        start=date.fromisoformat(task["start"]),
        label=f"{task['config']}:{task['window']}",
        allow_holdout=False,
    )
    selected = result["dataset"].get("selected_range") or {}
    last_et = str(selected.get("last_et") or "")[:10]
    if last_et > "2026-06-30" or last_et > lock["holdout"]["start"]:
        raise RuntimeError(f"{task['config']}:{task['window']} tocó holdout ({last_et})")
    trades = []
    for trade in result["trades"]:
        trades.append(
            {
                "window": task["window"],
                "signal_id": (trade.get("meta") or {}).get("signal_id"),
                "entry_ts": trade["entry_ts"],
                "exit_ts": trade["exit_ts"],
                "entry_et": datetime.fromtimestamp(trade["entry_ts"], ET).strftime("%Y-%m-%d %H:%M"),
                "exit_et": datetime.fromtimestamp(trade["exit_ts"], ET).strftime("%Y-%m-%d %H:%M"),
                "entry_hour": datetime.fromtimestamp(trade["entry_ts"], ET).hour,
                "exit_hour": datetime.fromtimestamp(trade["exit_ts"], ET).hour,
                "direction": trade["direction"],
                "qty": trade["qty"],
                "pnl": trade["pnl"],
                "r_multiple": trade["r_multiple"],
                "exit_reason": trade["exit_reason"],
            }
        )
    metrics = result["metrics"]
    return {
        "key": _task_key(task),
        "config": task["config"],
        "window": task["window"],
        "risk": task["risk"],
        "sessions": result["dataset"]["sessions"]["count"],
        "selected": selected,
        "trades": trades,
        "metrics": {
            key: metrics.get(key)
            for key in (
                "trades",
                "net_profit",
                "profit_factor",
                "expectancy",
                "avg_r",
                "max_drawdown",
                "max_open_drawdown",
                "worst_loss_streak",
                "win_rate",
            )
        },
        "funnel": {
            "signals": result["funnel"]["summary"]["signals"],
            "traded": result["funnel"]["summary"]["traded"],
        },
    }


def _bucket(trades: list[dict], field: str) -> dict[int, dict]:
    buckets: dict[int, dict] = {}
    for trade in trades:
        hour = int(trade[field])
        row = buckets.setdefault(hour, {"trades": 0, "net": 0.0, "wins": 0, "losses": 0})
        row["trades"] += 1
        row["net"] += float(trade["pnl"])
        if trade["pnl"] > 0:
            row["wins"] += 1
        elif trade["pnl"] < 0:
            row["losses"] += 1
    return buckets


def _summary(runs: list[dict], config: str) -> dict:
    rows = [row for row in runs if row["config"] == config]
    trades = [trade for row in rows for trade in row["trades"]]
    by_entry = _bucket(trades, "entry_hour")
    by_exit = _bucket(trades, "exit_hour")
    net = sum(float(t["pnl"]) for t in trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] < 0)
    gross_profit = sum(float(t["pnl"]) for t in trades if t["pnl"] > 0)
    gross_loss = sum(float(t["pnl"]) for t in trades if t["pnl"] < 0)
    return {
        "config": config,
        "trades": len(trades),
        "net": round(net, 2),
        "pf": round(gross_profit / abs(gross_loss), 4) if gross_loss else None,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades) * 100, 2) if trades else None,
        "avg_r": round(sum(float(t["r_multiple"]) for t in trades) / len(trades), 4) if trades else None,
        "by_entry_hour": {str(k): v for k, v in sorted(by_entry.items())},
        "by_exit_hour": {str(k): v for k, v in sorted(by_exit.items())},
        "entry_12": by_entry.get(12, {"trades": 0, "net": 0.0, "wins": 0, "losses": 0}),
        "exit_12": by_exit.get(12, {"trades": 0, "net": 0.0, "wins": 0, "losses": 0}),
        "entry_rest": {
            "trades": len(trades) - by_entry.get(12, {}).get("trades", 0),
            "net": round(net - by_entry.get(12, {}).get("net", 0.0), 2),
        },
        "exit_rest": {
            "trades": len(trades) - by_exit.get(12, {}).get("trades", 0),
            "net": round(net - by_exit.get(12, {}).get("net", 0.0), 2),
        },
        "windows": {
            row["window"]: {
                "trades": len(row["trades"]),
                "net": round(sum(float(t["pnl"]) for t in row["trades"]), 2),
                "entry_12": _bucket(row["trades"], "entry_hour").get(12, {"trades": 0, "net": 0.0}),
                "exit_12": _bucket(row["trades"], "exit_hour").get(12, {"trades": 0, "net": 0.0}),
            }
            for row in sorted(rows, key=lambda r: r["window"])
        },
    }


def main() -> int:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    tasks = [
        {
            "config": config,
            "risk": patch,
            "window": window["id"],
            "start": window["start"],
            "end": window["end"],
            "sessions": window["sessions"],
        }
        for config, patch in CONFIGS
        for window in lock["windows"]
    ]
    runs = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_run, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            row = future.result()
            runs.append(row)
            print(
                f"{row['key']:<18} {row['metrics']['trades']:2d} ops "
                f"net {row['metrics']['net_profit']:8.2f} "
                f"entry12 {_bucket(row['trades'], 'entry_hour').get(12, {}).get('net', 0):8.2f} "
                f"exit12 {_bucket(row['trades'], 'exit_hour').get(12, {}).get('net', 0):8.2f}",
                flush=True,
            )
            if task["config"] == "base":
                selected = row["selected"]
                print(
                    f"  base {task['window']} sessions={row['sessions']} "
                    f"{selected.get('first_et')}..{selected.get('last_et')}",
                    flush=True,
                )

    runs.sort(key=lambda r: (r["config"], r["window"]))
    summaries = [_summary(runs, config) for config, _ in CONFIGS]
    payload = {
        "configs": [{"name": name, "risk": patch} for name, patch in CONFIGS],
        "runs": runs,
        "summaries": summaries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nRESUMEN")
    for row in summaries:
        print(
            f"{row['config']:<10} ops={row['trades']:2d} net={row['net']:8.2f} "
            f"pf={row['pf']} entry12={row['entry_12']['net']:8.2f} "
            f"entry_rest={row['entry_rest']['net']:8.2f} exit12={row['exit_12']['net']:8.2f} "
            f"exit_rest={row['exit_rest']['net']:8.2f}"
        )
    print(f"Guardado en {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
