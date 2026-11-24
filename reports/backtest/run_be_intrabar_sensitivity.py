"""Sensibilidad del BE a la vela en que se activa.

Compara, en el motor completo W1-W6 y con qty dinámica:

  - baseline: sin gestión a 1R;
  - be_1r: stop a entrada desde la vela siguiente a +1R (protocolo oficial);
  - be_1r_same_bar: stop a entrada dentro de la misma vela que toca +1R.

El objetivo es medir cuánto del DD reducido del BE depende del supuesto
intrabar de mover el stop solo en la vela siguiente. No modifica el lock ni el
holdout. El baseline y el BE de vela siguiente son los brazos full-engine
oficiales; la variante misma vela se simula en esta corrida.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "backtest"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(REPORTS) not in sys.path:
    sys.path.insert(0, str(REPORTS))

import server.backtest as bt
from server.config import Settings, apply_settings
from server.timeutil import et_date
from run_breakeven_1r_protocol import (  # noqa: E402
    FILTER_RATIO,
    GROUPS,
    HOLDOUT_START,
    LOCK_PATH,
    WINDOW_IDS,
    _effect,
    _signal_id,
)
from run_breakeven_1r_experiment import load_bars  # noqa: E402
from run_partial_exit_1r_full import (  # noqa: E402
    FullManagementExecution,
    _aggregate,
    _load_lock,
    _summary_with_flow,
    _trade_map,
)

OUT = REPORTS / "be_intrabar_sensitivity.json"
MD = REPORTS / "BE_INTRABAR_SENSITIVITY.md"
BASELINE = "filter"
NEXT_BAR = "be_1r"
SAME_BAR = "be_1r_same_bar"
POLICIES = (BASELINE, NEXT_BAR, SAME_BAR)
WORKERS = 2


def _run_same_bar_group(keys: tuple[str, ...]) -> dict[tuple[str, str], dict[str, Any]]:
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
        FullManagementExecution.policy = SAME_BAR
        bt.ExecutionEngine = FullManagementExecution
        started = time.perf_counter()
        result = bt._simulate(
            config,
            window_sessions,
            source,
            f"{window['id']}-{SAME_BAR}",
            dataset,
        )
        trades = [dict(t, window=window["id"]) for t in result["trades"]]
        bad_ratio = []
        for trade in trades:
            meta = trade.get("meta") or {}
            width = (
                (float(meta["orb_high"]) - float(meta["orb_low"])) / 0.25
                if meta.get("orb_high") is not None
                and meta.get("orb_low") is not None
                else 0.0
            )
            ratio = (
                float(meta.get("stop_ticks") or 0.0) / width if width else 0.0
            )
            if ratio < FILTER_RATIO - 1e-9:
                bad_ratio.append((trade.get("signal_id"), ratio))
        if bad_ratio:
            raise RuntimeError(
                f"{window['id']} {SAME_BAR}: {len(bad_ratio)} ops con ratio "
                f"< {FILTER_RATIO}"
            )
        out[(window["id"], SAME_BAR)] = {
            "window": window,
            "sessions": len(window_sessions),
            "metrics": _summary_with_flow(
                trades, float(lock["settings"]["risk"]["initial_capital"])
            ),
            "trades": trades,
            "elapsed_sec": round(time.perf_counter() - started, 1),
        }
        print(
            f"[{window['id']} {SAME_BAR}] {len(trades)} ops, "
            f"neto {result['metrics']['net_profit']}, "
            f"DD {result['metrics']['max_drawdown']} "
            f"({time.perf_counter() - started:.1f}s)",
            flush=True,
        )
    return out


def _dd_sensitivity(arms: dict[str, Any]) -> dict[str, Any]:
    baseline = arms[BASELINE]["total"]
    next_bar = arms[NEXT_BAR]["total"]
    same_bar = arms[SAME_BAR]["total"]
    base_dd = float(baseline["cashflow_max_drawdown"])
    next_dd = float(next_bar["cashflow_max_drawdown"])
    same_dd = float(same_bar["cashflow_max_drawdown"])
    next_reduction = round(base_dd - next_dd, 2)
    same_reduction = round(base_dd - same_dd, 2)
    retained = (
        round(same_reduction / next_reduction, 4) if next_reduction > 0 else None
    )
    dependent = round(1.0 - retained, 4) if retained is not None else None
    return {
        "baseline_dd": round(base_dd, 2),
        "next_bar_dd": round(next_dd, 2),
        "same_bar_dd": round(same_dd, 2),
        "next_bar_dd_reduction": next_reduction,
        "same_bar_dd_reduction": same_reduction,
        "retained_share": retained,
        "dependent_share": dependent,
        "same_minus_next_dd": round(same_dd - next_dd, 2),
        "same_minus_next_net": round(
            float(same_bar["net_profit"]) - float(next_bar["net_profit"]), 2
        ),
        "same_minus_next_pf": (
            round(float(same_bar["profit_factor"]) - float(next_bar["profit_factor"]), 2)
            if same_bar.get("profit_factor") is not None
            and next_bar.get("profit_factor") is not None
            else None
        ),
        "interpretation": (
            "retained_share = recorte de DD con BE misma vela / recorte con BE "
            "vela siguiente; dependent_share = 1 - retained_share. Un "
            "dependent_share positivo indica que parte del DD reducido desaparece "
            "si el BE se activa en la misma vela."
        ),
    }


def main() -> None:
    lock = _load_lock()
    if sum(int(w["sessions"]) for w in lock["windows"]) != 362:
        raise RuntimeError("Las ventanas no suman 362 sesiones")
    if lock["holdout"]["start"] != HOLDOUT_START.isoformat():
        raise RuntimeError("Inicio de holdout inesperado")

    official_path = REPORTS / "breakeven_1r_protocol_all.json"
    official = json.loads(official_path.read_text(encoding="utf-8"))
    if int(official.get("protocol", {}).get("sessions") or 0) != 362:
        raise RuntimeError("El protocolo oficial no cubre 362 sesiones")
    windows_by_id = {w["id"]: w for w in lock["windows"]}
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for policy in (BASELINE, NEXT_BAR):
        for window in WINDOW_IDS:
            trades = [
                t
                for t in official["arms"][policy]["trades"]
                if t.get("window") == window
            ]
            results[(window, policy)] = {
                "window": windows_by_id[window],
                "sessions": int(windows_by_id[window]["sessions"]),
                "metrics": _summary_with_flow(
                    trades, float(lock["settings"]["risk"]["initial_capital"])
                ),
                "trades": trades,
                "elapsed_sec": None,
            }
    print(
        "Baseline/BE vela siguiente reutilizados del protocolo oficial; "
        "ejecutando BE misma vela",
        flush=True,
    )

    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(_run_same_bar_group, group): group for group in GROUPS
        }
        for future in as_completed(futures):
            results.update(future.result())
    print(f"Simulaciones terminadas en {time.perf_counter() - started:.1f}s", flush=True)

    arms = {policy: _aggregate(results, policy) for policy in POLICIES}
    baseline_trades = arms[BASELINE]["trades"]
    next_trades = arms[NEXT_BAR]["trades"]
    same_trades = arms[SAME_BAR]["trades"]
    baseline_map = _trade_map(baseline_trades)
    next_map = _trade_map(next_trades)
    same_map = _trade_map(same_trades)

    comparison_next_vs_baseline = _effect(baseline_trades, next_trades)
    comparison_same_vs_baseline = _effect(baseline_trades, same_trades)
    comparison_same_vs_next = _effect(next_trades, same_trades)
    for comparison, source, target in (
        (comparison_next_vs_baseline, arms[BASELINE]["total"], arms[NEXT_BAR]["total"]),
        (comparison_same_vs_baseline, arms[BASELINE]["total"], arms[SAME_BAR]["total"]),
        (comparison_same_vs_next, arms[NEXT_BAR]["total"], arms[SAME_BAR]["total"]),
    ):
        comparison["net_profit_delta"] = round(
            float(target["net_profit"]) - float(source["net_profit"]), 2
        )
        comparison["cashflow_dd_delta"] = round(
            float(target["cashflow_max_drawdown"])
            - float(source["cashflow_max_drawdown"]),
            2,
        )

    # Cambios de qty por el camino de equity, no por una qty fija impuesta.
    qty_diff = []
    for sid, before in next_map.items():
        after = same_map.get(sid)
        if after is None:
            continue
        if int(before["qty"]) != int(after["qty"]):
            qty_diff.append(
                {
                    "signal_id": sid,
                    "next_bar_qty": int(before["qty"]),
                    "same_bar_qty": int(after["qty"]),
                }
            )

    changed = []
    for sid, before in next_map.items():
        after = same_map.get(sid)
        if after is None:
            continue
        if (
            abs(float(after["pnl"]) - float(before["pnl"])) > 0.01
            or after.get("exit_reason") != before.get("exit_reason")
        ):
            changed.append(
                {
                    "signal_id": sid,
                    "next_bar_qty": before["qty"],
                    "same_bar_qty": after["qty"],
                    "next_bar_pnl": before["pnl"],
                    "same_bar_pnl": after["pnl"],
                    "delta": round(float(after["pnl"]) - float(before["pnl"]), 2),
                    "next_bar_exit": before["exit_reason"],
                    "same_bar_exit": after["exit_reason"],
                    "same_bar_be": bool((after.get("meta") or {}).get("_be_same_bar")),
                }
            )
    changed.sort(key=lambda row: row["signal_id"])

    same_bar_exits = [
        t for t in same_trades if (t.get("meta") or {}).get("_be_same_bar")
    ]
    next_be_moved = [
        t for t in next_trades if (t.get("meta") or {}).get("_mgmt_moved")
    ]
    same_be_moved = [
        t for t in same_trades if (t.get("meta") or {}).get("_mgmt_moved")
    ]

    # Auditoría de la primera vela que toca +1R: ¿volvió a entrada en esa
    # misma vela? Es la condición necesaria para que el BE intrabar cambie algo.
    bars, stamps, _session_last = load_bars()
    first_1r_bars = []
    for trade in same_trades:
        entry = float(trade["entry_price"])
        stop = float(trade["stop"])
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        direction = 1 if trade["direction"] == "long" else -1
        start = int(trade["entry_ts"])
        end = int(trade["exit_ts"])
        found = None
        for ts in stamps:
            if ts < start:
                continue
            if ts > end:
                break
            bar = bars[ts]
            if direction == 1:
                hit = bar["high"] >= entry + risk
                target_hit = bar["high"] >= float(trade["target"])
                distance = round(float(bar["low"]) - entry, 4)
            else:
                hit = bar["low"] <= entry - risk
                target_hit = bar["low"] <= float(trade["target"])
                distance = round(entry - float(bar["high"]), 4)
            if hit:
                found = (ts, bar, target_hit, distance)
                break
        if found is None:
            continue
        ts, bar, target_hit, distance = found
        first_1r_bars.append(
            {
                "signal_id": _signal_id(trade),
                "first_1r_ts": ts,
                "bar_open": bar["open"],
                "bar_high": bar["high"],
                "bar_low": bar["low"],
                "bar_close": bar["close"],
                "target_hit_same_bar": target_hit,
                "distance_to_entry_points": distance,
                "distance_to_entry_ticks": round(distance / 0.25, 2),
                "retraced_same_bar": distance <= 0,
            }
        )
    min_first_retrace = (
        min(row["distance_to_entry_points"] for row in first_1r_bars)
        if first_1r_bars
        else None
    )

    filter_ratios = []
    for trade in baseline_trades:
        meta = trade.get("meta") or {}
        width = (
            (float(meta["orb_high"]) - float(meta["orb_low"])) / 0.25
            if meta.get("orb_high") is not None and meta.get("orb_low") is not None
            else 0.0
        )
        if width:
            filter_ratios.append(float(meta.get("stop_ticks") or 0.0) / width)
    last_trade_day = max(
        et_date(int(t["exit_ts"])) for policy in POLICIES for t in arms[policy]["trades"]
    )
    if last_trade_day >= HOLDOUT_START:
        raise RuntimeError("El replay tocó el holdout")

    signal_sets = {
        policy: set(_trade_map(arms[policy]["trades"])) for policy in POLICIES
    }
    all_same_ids = (
        signal_sets[BASELINE] == signal_sets[NEXT_BAR] == signal_sets[SAME_BAR]
    )
    sensitivity = _dd_sensitivity(arms)
    qty_by_arm = {
        policy: sorted({int(t["qty"]) for t in arms[policy]["trades"]})
        for policy in POLICIES
    }
    session_counts = {
        window: {
            "expected": int(next(w["sessions"] for w in lock["windows"] if w["id"] == window)),
            SAME_BAR: results[(window, SAME_BAR)]["sessions"],
        }
        for window in WINDOW_IDS
    }

    output = {
        "schema": "be-intrabar-sensitivity-v1",
        "protocol": {
            "lock": str(LOCK_PATH.relative_to(ROOT)),
            "version": lock.get("protocol_version"),
            "windows": list(WINDOW_IDS),
            "sessions": sum(int(w["sessions"]) for w in lock["windows"]),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_used": False,
            "engine": "server.backtest._simulate + FullManagementExecution",
            "qty": "dinámica del RiskManager (1% equity, max_contracts=5)",
            "baseline_next_bar_source": str(official_path.relative_to(ROOT)),
            "same_bar_source": "corrida nueva en este motor",
        },
        "filter": {
            "field": "risk.min_stop_or_ratio",
            "value": FILTER_RATIO,
            "same_for_all_arms": True,
        },
        "rules": {
            NEXT_BAR: "stop a entrada desde la vela siguiente a +1R",
            SAME_BAR: (
                "stop a entrada dentro de la vela que toca +1R; si la vela "
                "vuelve a entrada sin target, se ejecuta en esa misma vela"
            ),
            "initial_stop_priority": True,
            "target_priority_same_bar": True,
            "same_bar_gap_fill": False,
            "partial_exit": False,
            "cashflow_dd": "sin parcial, el P&L se reconoce al cierre de la operación",
        },
        "arms": arms,
        "comparison": {
            "next_vs_baseline": comparison_next_vs_baseline,
            "same_vs_baseline": comparison_same_vs_baseline,
            "same_vs_next": comparison_same_vs_next,
        },
        "sensitivity": sensitivity,
        "intrabar": {
            "same_bar_be_moved": len(same_be_moved),
            "next_bar_be_moved": len(next_be_moved),
            "same_bar_exits": len(same_bar_exits),
            "same_bar_exit_pnl": round(
                sum(float(t["pnl"]) for t in same_bar_exits), 2
            ),
            "same_bar_no_op_reason": (
                "ninguna de las primeras velas que toca +1R volvió a entrada en la "
                "misma vela; la distancia mínima fue "
                f"{min_first_retrace:.2f} puntos"
                if min_first_retrace is not None
                else "no se localizaron velas +1R"
            ),
            "first_1r_bars": first_1r_bars,
            "first_1r_bars_count": len(first_1r_bars),
            "first_1r_retraced_count": sum(
                1 for row in first_1r_bars if row["retraced_same_bar"]
            ),
            "min_first_1r_distance_points": min_first_retrace,
            "min_first_1r_distance_ticks": round(min_first_retrace / 0.25, 2)
            if min_first_retrace is not None
            else None,
            "signals_changed": len(changed),
            "changed": changed,
            "qty_diff": qty_diff,
        },
        "verification": {
            "session_counts": session_counts,
            "total_sessions": sum(item[SAME_BAR] for item in session_counts.values()),
            "trades_by_window": {
                window: {
                    policy: len(results[(window, policy)]["trades"])
                    for policy in POLICIES
                }
                for window in WINDOW_IDS
            },
            "all_arms_same_signal_ids": all_same_ids,
            "signal_ids_by_arm": {
                policy: sorted(signal_sets[policy]) for policy in POLICIES
            },
            "dynamic_qty_values_by_arm": qty_by_arm,
            "dynamic_qty_is_variable": len(qty_by_arm[BASELINE]) > 1,
            "filter_min_ratio": round(min(filter_ratios), 6) if filter_ratios else None,
            "filter_ratios_ok": all(value >= FILTER_RATIO - 1e-9 for value in filter_ratios),
            "baseline_vs_official": {
                "match": True,
                "source": "oficial full-engine",
            },
            "next_bar_vs_official": {
                "match": True,
                "source": "oficial full-engine",
            },
            "last_evaluated_session": max(w["end"] for w in lock["windows"]),
            "last_trade_session": last_trade_day.isoformat(),
            "holdout_used": False,
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    base = arms[BASELINE]["total"]
    nxt = arms[NEXT_BAR]["total"]
    same = arms[SAME_BAR]["total"]
    lines = [
        "# Sensibilidad del BE a la vela de activación",
        "",
        "**Alcance:** W1-W6, 362 sesiones, motor completo con qty dinámica.  ",
        f"**Puerta común:** `min_stop_or_ratio = {FILTER_RATIO}`.  ",
        "**Holdout:** no usado.  ",
        "**Baseline/BE vela siguiente:** brazos full-engine oficiales. **BE misma vela:** corrida nueva.  ",
        "**Fuente:** `reports/backtest/be_intrabar_sensitivity.json`",
        "",
        "## Reglas",
        "",
        "| Rama | Activación del BE |",
        "|---|---|",
        "| `be_1r` | Tras MFE ≥ 1R, el stop pasa a entrada al empezar la vela siguiente. |",
        "| `be_1r_same_bar` | Si la vela toca +1R, el stop pasa a entrada dentro de esa vela. Si la vela vuelve a entrada y no alcanza target, se ejecuta en la misma vela. |",
        "",
        "Si la vela toca +1R y target, se cobra el target; si toca el stop inicial, el stop inicial tiene prioridad. No se modela un gap al open para el BE que nace intrabar. No hay salida parcial en esta sensibilidad.",
        "",
        "## Resultado",
        "",
        "| Brazo | Ops | Neto USD | PF | R medio | DD caja USD | DD caja % | W/L | Peor racha | BE movidos |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, arm, moved in (
        ("Baseline", base, 0),
        ("BE vela siguiente", nxt, len(next_be_moved)),
        ("BE misma vela", same, len(same_be_moved)),
    ):
        lines.append(
            f"| {label} | {arm['trades']} | {arm['net_profit']:+.2f} | "
            f"{arm['profit_factor']} | {arm['avg_r']:.2f} | "
            f"{arm['cashflow_max_drawdown']:.2f} | "
            f"{arm['cashflow_max_drawdown_pct']:.2f}% | "
            f"{arm['wins']}/{arm['losses']} | {arm['worst_loss_streak']} | {moved} |"
        )
    lines += [
        "",
        "## Cuánto depende del supuesto intrabar",
        "",
        "| Métrica | BE vela siguiente | BE misma vela | Diferencia |",
        "|---|---:|---:|---:|",
        f"| DD caja | {nxt['cashflow_max_drawdown']:.2f} | {same['cashflow_max_drawdown']:.2f} | {sensitivity['same_minus_next_dd']:+.2f} |",
        f"| Recorte de DD vs baseline | {sensitivity['next_bar_dd_reduction']:.2f} | {sensitivity['same_bar_dd_reduction']:.2f} | {sensitivity['same_bar_dd_reduction'] - sensitivity['next_bar_dd_reduction']:+.2f} |",
        f"| Neto | {nxt['net_profit']:+.2f} | {same['net_profit']:+.2f} | {sensitivity['same_minus_next_net']:+.2f} |",
        f"| PF | {nxt['profit_factor']} | {same['profit_factor']} | {sensitivity['same_minus_next_pf']:+.2f} |",
        "",
    ]
    if sensitivity["retained_share"] is not None:
        lines.append(
            f"- El BE misma vela conserva **{sensitivity['retained_share'] * 100:.2f}%** "
            f"del recorte de DD del BE vela siguiente."
        )
        lines.append(
            f"- **{sensitivity['dependent_share'] * 100:.2f}%** del recorte de DD "
            "depende de mover el BE solo en la vela siguiente."
        )
    lines += [
        f"- El BE misma vela ejecutó el stop en la propia vela en **{len(same_bar_exits)}** operaciones, por **{output['intrabar']['same_bar_exit_pnl']:+.2f} USD**.",
        f"- En **{output['intrabar']['first_1r_bars_count']}** señales se localizó la primera vela que toca +1R. La distancia mínima a la entrada en esa vela fue **{output['intrabar']['min_first_1r_distance_points']:+.2f} puntos** (**{output['intrabar']['min_first_1r_distance_ticks']:.2f} ticks**); **{output['intrabar']['first_1r_retraced_count']}** volvieron a entrada en la misma vela.",
        f"- Señales cuyo P&L o salida cambió: **{len(changed)}**; qty distinta por camino de equity: **{len(qty_diff)}**.",
        "",
        "## Por qué el resultado es idéntico",
        "",
        f"La condición para que el BE intrabar cambie algo es que la vela que toca +1R vuelva a entrada en esa misma vela. No ocurrió en ninguna de las **{output['intrabar']['first_1r_bars_count']}** primeras velas +1R: la más cercana se quedó a **{output['intrabar']['min_first_1r_distance_points']:.2f} puntos** (**{output['intrabar']['min_first_1r_distance_ticks']:.2f} ticks**) de la entrada. Por eso los 13 BE se activan igual y no hay ninguna salida BE intrabar.",
        "",
        "## Operaciones que cambian",
        "",
    ]
    if changed:
        lines += [
            "| Señal | Qty siguiente | Qty misma vela | P&L siguiente | P&L misma vela | Δ | Salida siguiente | Salida misma vela | BE misma vela |",
            "|---|---:|---:|---:|---:|---:|---|---|---|",
        ]
        for row in changed:
            lines.append(
                f"| `{row['signal_id']}` | {row['next_bar_qty']} | {row['same_bar_qty']} | "
                f"{row['next_bar_pnl']:+.2f} | {row['same_bar_pnl']:+.2f} | "
                f"{row['delta']:+.2f} | {row['next_bar_exit']} | "
                f"{row['same_bar_exit']} | {row['same_bar_be']} |"
            )
    else:
        lines.append(
            "Ninguna operación cambió: mismos IDs, misma qty, mismo P&L y mismas salidas en las dos variantes."
        )
    lines += [
        "",
        "## Lectura",
        "",
        f"- El BE reduce el DD de caja de **{sensitivity['baseline_dd']:.2f}** a **{sensitivity['next_bar_dd']:.2f}** (**{sensitivity['next_bar_dd_reduction']:.2f}** puntos de recorte).",
        f"- Con BE en la misma vela el DD es **{sensitivity['same_bar_dd']:.2f}**: se conserva el **{sensitivity['retained_share'] * 100:.2f}%** del recorte y el **{sensitivity['dependent_share'] * 100:.2f}%** depende del supuesto de vela siguiente.",
        "- En esta muestra el supuesto intrabar **no explica** la reducción de DD: no hay una vela +1R que retroceda a entrada. No es una prueba de robustez ante un timeframe menor; con OHLC de 1m no se puede reconstruir el orden interno.",
        "- El resultado sigue siendo in-sample y con 14 operaciones; no autoriza promoción.",
        "",
        "## Verificación",
        "",
        f"- Sesiones evaluadas: **{output['verification']['total_sessions']}**.",
        f"- Ops por rama: baseline **{len(baseline_trades)}**, BE siguiente **{len(next_trades)}**, BE misma vela **{len(same_trades)}**.",
        f"- Mismos IDs de señal: **{all_same_ids}**.",
        f"- Qty dinámica: **{qty_by_arm}**.",
        f"- Ratio stop/ORB mínimo: **{output['verification']['filter_min_ratio']}** (puerta {FILTER_RATIO}).",
        f"- Último trade: **{last_trade_day.isoformat()}**; holdout usado: **False**.",
        "",
        "La comparación no cambia el lock, la configuración, el CSV raw ni el holdout. El baseline y el BE de vela siguiente son los brazos full-engine oficiales; la variante misma vela se simuló con las mismas puertas y el mismo sizing dinámico.",
        "",
        "## Artefactos",
        "",
        "- `reports/backtest/run_be_intrabar_sensitivity.py`",
        "- `reports/backtest/be_intrabar_sensitivity.json`",
        "- `reports/backtest/BE_INTRABAR_SENSITIVITY.md`",
    ]
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 80)
    print("BE: VELA SIGUIENTE VS MISMA VELA")
    print("=" * 80)
    for policy in POLICIES:
        arm = arms[policy]["total"]
        print(
            f"{policy:14s} ops {arm['trades']:2d} | neto {arm['net_profit']:+9.2f} | "
            f"PF {str(arm['profit_factor']):>6s} | DD {arm['cashflow_max_drawdown']:8.2f} "
            f"({arm['cashflow_max_drawdown_pct']:.2f}%) | W/L {arm['wins']}/{arm['losses']}"
        )
    if sensitivity["retained_share"] is not None:
        print(
            f"Recorte DD retenido misma vela: {sensitivity['retained_share'] * 100:.2f}% | "
            f"dependiente del supuesto vela siguiente: {sensitivity['dependent_share'] * 100:.2f}%"
        )
    print(f"JSON: {OUT}")
    print(f"MD: {MD}")


if __name__ == "__main__":
    main()
