"""Replay completo W1-W6: filtro stop/ORB y gestión break-even/trailing 1R.

Protocolo v1.2, endpoint full, 362 sesiones, holdout sin abrir.
No modifica el motor ni la configuración de producción: parchea la clase de
ejecución solo dentro de este proceso de investigación.

Brazos:
  - filter:   min_stop_or_ratio=0.25, salida original.
  - be_1r:    stop a la entrada tras MFE >= 1R.
  - lock_1r:  stop a +1R tras MFE >= 1R.
  - trail_1r: stop a máximo favorable - 1R tras MFE >= 1R.

El stop se mueve al empezar la vela siguiente a la que alcanza +1R. Si en una
vela se tocan stop y target, se aplica stop primero, igual que el motor.
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.backtest as bt
from _windows import WINDOW_IDS
from server.config import Settings, apply_settings
from server.execution import ExecutionEngine
from server.stats import compute_stats
from server.timeutil import et_date

LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
OUT_PATH = Path(
    os.environ.get(
        "BE_OUT",
        str(ROOT / "reports/backtest/breakeven_1r_protocol.json"),
    )
)
FILTER_RATIO = 0.25
HOLDOUT_START = date(2026, 7, 1)
GROUPS = (("W1", "W2"), ("W3",), ("W4",), ("W5", "W6"))
POLICIES = tuple(
    p.strip()
    for p in os.environ.get(
        "BE_POLICIES", "filter,be_1r,lock_1r,trail_1r"
    ).split(",")
    if p.strip()
)


def _tick_round(value: float, tick: float) -> float:
    return round(value / tick) * tick


class PolicyExecution(ExecutionEngine):
    """ExecutionEngine con gestión de stop a +1R, solo para este experimento."""

    policy = "filter"

    def _manage_position(self, bar) -> None:  # type: ignore[no-untyped-def]
        pos = self.position
        if pos is not None and self.policy != "filter" and bar.ts >= pos.entry_ts:
            risk = abs(pos.entry_price - pos.initial_stop)
            if risk > 0 and pos.mfe_r >= 1.0:
                direction = 1 if pos.direction == "long" else -1
                moved = bool(pos.meta.get("_mgmt_moved"))
                if self.policy == "be_1r":
                    if not moved:
                        pos.stop = _tick_round(pos.entry_price, self.tick)
                        pos.meta["_mgmt_moved"] = True
                elif self.policy == "lock_1r":
                    if not moved:
                        pos.stop = _tick_round(pos.entry_price + direction * risk, self.tick)
                        pos.meta["_mgmt_moved"] = True
                elif self.policy == "trail_1r":
                    candidate = _tick_round(
                        pos.entry_price + direction * (pos.mfe_r - 1.0) * risk,
                        self.tick,
                    )
                    if direction == 1:
                        pos.stop = max(pos.stop, candidate)
                    else:
                        pos.stop = min(pos.stop, candidate)
                    pos.meta["_mgmt_moved"] = True
        super()._manage_position(bar)


def _load_lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _summary(trades: list[dict[str, Any]], capital: float) -> dict[str, Any]:
    stats = compute_stats(trades, capital)
    return {
        key: stats.get(key)
        for key in (
            "trades",
            "wins",
            "losses",
            "win_rate",
            "profit_factor",
            "expectancy",
            "net_profit",
            "gross_profit",
            "gross_loss",
            "avg_r",
            "max_drawdown",
            "max_drawdown_pct",
            "worst_loss_streak",
            "best_trade",
            "worst_trade",
        )
    }


def _signal_id(trade: dict[str, Any]) -> str:
    # El motor guarda el id en meta; los replays de gestión lo exponen arriba.
    return str(
        (trade.get("meta") or {}).get("signal_id")
        or trade.get("signal_id")
        or ""
    )


def _run_group(keys: tuple[str, ...]) -> dict[tuple[str, str], dict[str, Any]]:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    windows = {w["id"]: w for w in lock["windows"]}
    group_windows = [windows[k] for k in keys]
    start = date.fromisoformat(group_windows[0]["start"])
    days = sum(int(w["sessions"]) for w in group_windows)
    sessions, source, dataset = bt.prepare_dataset(
        base, days, start, allow_holdout=False
    )
    if source != "csv":
        raise RuntimeError(f"Se esperaba CSV real, recibido {source!r}")
    if sessions[-1][0] >= HOLDOUT_START:
        raise RuntimeError("El dataset alcanza el holdout")
    config = apply_settings(base, {"risk": {"min_stop_or_ratio": FILTER_RATIO}})
    if config.risk.min_stop_or_ratio != FILTER_RATIO:
        raise RuntimeError("El filtro no quedó activo")

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for window in group_windows:
        ws = date.fromisoformat(window["start"])
        we = date.fromisoformat(window["end"])
        window_sessions = [(d, data) for d, data in sessions if ws <= d <= we]
        if len(window_sessions) != int(window["sessions"]):
            raise RuntimeError(
                f"{window['id']}: {len(window_sessions)} sesiones, "
                f"se esperaban {window['sessions']}"
            )
        if window_sessions[-1][0] >= HOLDOUT_START:
            raise RuntimeError(f"{window['id']} toca el holdout")
        for policy in POLICIES:
            PolicyExecution.policy = policy
            bt.ExecutionEngine = PolicyExecution
            started = time.perf_counter()
            result = bt._simulate(
                config,
                window_sessions,
                source,
                f"{window['id']}-{policy}",
                dataset,
            )
            trades = [dict(t, window=window["id"]) for t in result["trades"]]
            bad_ratio = []
            for t in trades:
                meta = t.get("meta") or {}
                width = (
                    (float(meta["orb_high"]) - float(meta["orb_low"])) / 0.25
                    if meta.get("orb_high") is not None
                    and meta.get("orb_low") is not None
                    else 0.0
                )
                ratio = float(meta.get("stop_ticks") or 0.0) / width if width else 0.0
                if ratio < FILTER_RATIO - 1e-9:
                    bad_ratio.append((t.get("signal_id"), ratio))
            if bad_ratio:
                raise RuntimeError(
                    f"{window['id']} {policy}: {len(bad_ratio)} ops con ratio < "
                    f"{FILTER_RATIO}"
                )
            out[(window["id"], policy)] = {
                "window": window,
                "sessions": len(window_sessions),
                "metrics": _summary(trades, config.risk.initial_capital),
                "trades": trades,
                "elapsed_sec": round(time.perf_counter() - started, 1),
            }
            print(
                f"[{window['id']} {policy}] {len(trades)} ops, "
                f"neto {result['metrics']['net_profit']}, "
                f"DD {result['metrics']['max_drawdown']} "
                f"({time.perf_counter() - started:.1f}s)",
                flush=True,
            )
    return out


def _aggregate(
    results: dict[tuple[str, str], dict[str, Any]], policy: str
) -> dict[str, Any]:
    lock = _load_lock()
    capital = float(lock["settings"]["risk"]["initial_capital"])
    all_trades = [
        t for w in WINDOW_IDS for t in results[(w, policy)]["trades"]
    ]
    ex_w4 = [t for t in all_trades if t["window"] != "W4"]
    blocks = []
    for w in WINDOW_IDS:
        item = results[(w, policy)]
        blocks.append(
            {
                "id": w,
                "start": item["window"]["start"],
                "end": item["window"]["end"],
                "sessions": item["sessions"],
                "metrics": item["metrics"],
            }
        )
    return {
        "total": _summary(all_trades, capital),
        "ex_w4": _summary(ex_w4, capital),
        "blocks": blocks,
        "trades": all_trades,
    }


def _effect(original: list[dict[str, Any]], changed: list[dict[str, Any]]) -> dict[str, Any]:
    o = {_signal_id(t): t for t in original}
    c = {_signal_id(t): t for t in changed}
    cut = []
    below = []
    improved = []
    avoided = []
    new = [t for t in changed if _signal_id(t) not in o]
    for sid, before in o.items():
        after = c.get(sid)
        if after is None:
            if float(before["pnl"]) > 0:
                cut.append({"signal_id": sid, "original_pnl": before["pnl"], "new_pnl": None})
            else:
                avoided.append({"signal_id": sid, "original_pnl": before["pnl"]})
            continue
        bp = float(before["pnl"])
        ap = float(after["pnl"])
        if bp > 0 and ap <= 0:
            cut.append({"signal_id": sid, "original_pnl": bp, "new_pnl": ap})
        elif bp > 0 and ap < bp:
            below.append({"signal_id": sid, "original_pnl": bp, "new_pnl": ap})
        elif bp < 0 and ap > bp:
            improved.append({"signal_id": sid, "original_pnl": bp, "new_pnl": ap})
    return {
        "original_winners": sum(1 for t in original if float(t["pnl"]) > 0),
        "original_losses": sum(1 for t in original if float(t["pnl"]) < 0),
        "winners_cut": len(cut),
        "winners_below": len(below),
        "winner_pnl_lost": round(
            sum(float(x["original_pnl"]) - float(x["new_pnl"]) for x in cut + below),
            2,
        ),
        "losses_improved": len(improved),
        "losses_saved_usd": round(
            sum(float(x["new_pnl"]) - float(x["original_pnl"]) for x in improved),
            2,
        ),
        "losses_avoided": len(avoided),
        "new_trades": len(new),
        "new_trades_pnl": round(sum(float(t["pnl"]) for t in new), 2),
        "cut_detail": cut,
        "below_detail": below,
        "improved_detail": improved,
        "avoided_detail": avoided,
    }


def main() -> None:
    lock = _load_lock()
    if sum(int(w["sessions"]) for w in lock["windows"]) != 362:
        raise RuntimeError("Las ventanas no suman 362 sesiones")
    if lock["holdout"]["start"] != HOLDOUT_START.isoformat():
        raise RuntimeError("Inicio de holdout inesperado")

    started = time.perf_counter()
    results: dict[tuple[str, str], dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=len(GROUPS)) as pool:
        futures = {pool.submit(_run_group, g): g for g in GROUPS}
        for future in as_completed(futures):
            results.update(future.result())
    print(f"Simulaciones terminadas en {time.perf_counter() - started:.1f}s", flush=True)

    report: dict[str, Any] = {
        "schema": "breakeven-1r-protocol-v1",
        "protocol": {
            "lock": str(LOCK_PATH.relative_to(ROOT)),
            "version": lock.get("version"),
            "windows": WINDOW_IDS,
            "sessions": sum(int(w["sessions"]) for w in lock["windows"]),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_used": False,
        },
        "filter": {"field": "risk.min_stop_or_ratio", "value": FILTER_RATIO},
        "policies": {
            p: {
                "filter": "sin gestión a 1R",
                "be_1r": "stop a entrada tras MFE >= 1R",
                "lock_1r": "stop a +1R tras MFE >= 1R",
                "trail_1r": "stop a máximo favorable - 1R tras MFE >= 1R",
            }[p]
            for p in POLICIES
        },
        "arms": {},
        "comparison": {},
        "verification": {
            "session_counts": {},
            "last_session": None,
            "all_filter_ratios_ok": True,
            "holdout_used": False,
        },
    }

    for policy in POLICIES:
        agg = _aggregate(results, policy)
        report["arms"][policy] = agg

    base_trades = report["arms"]["filter"]["trades"]
    for policy in POLICIES:
        report["comparison"][policy] = _effect(
            base_trades, report["arms"][policy]["trades"]
        )

    for w in WINDOW_IDS:
        report["verification"]["session_counts"][w] = {
            "expected": int(next(x["sessions"] for x in lock["windows"] if x["id"] == w)),
            "filter": results[(w, "filter")]["sessions"],
        }
    last = max(
        et_date(int(t["exit_ts"]))
        for p in POLICIES
        for t in report["arms"][p]["trades"]
    )
    report["verification"]["last_evaluated_session"] = max(
        w["end"] for w in lock["windows"]
    )
    report["verification"]["last_trade_session"] = last.isoformat()
    if last >= HOLDOUT_START:
        raise RuntimeError("El replay tocó el holdout")

    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 78)
    print("BREAK-EVEN / TRAILING 1R - PROTOCOLO OFICIAL 362 SESIONES")
    print("=" * 78)
    for policy in POLICIES:
        s = report["arms"][policy]["total"]
        e = report["comparison"][policy] if policy != "filter" else None
        extra = ""
        if e:
            extra = (
                f" | cortados {e['winners_cut']} (-{e['winner_pnl_lost']:.2f})"
                f" | perdidas +{e['losses_saved_usd']:.2f}"
                f" | nuevos {e['new_trades']} ({e['new_trades_pnl']:+.2f})"
            )
        print(
            f"{policy:9s} ops {s['trades']:3d} | neto {s['net_profit']:+9.2f} | "
            f"PF {str(s['profit_factor']):>5s} | DD {s['max_drawdown']:8.2f} "
            f"({s['max_drawdown_pct']:.2f}%) | W/L {s['wins']}/{s['losses']} | "
            f"racha {s['worst_loss_streak']}{extra}"
        )
    print(f"\nJSON: {OUT_PATH}")


if __name__ == "__main__":
    main()
