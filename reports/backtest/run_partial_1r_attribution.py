"""Atribución de la gestión a +1R: parcial solo, BE solo y combinación.

Brazos, todos con la misma puerta stop/ORB >= 0.25 y sizing dinámico:

  - filter:              sin gestión;
  - be_1r:               BE completo desde la vela siguiente a +1R;
  - partial_50_no_be:    50% a +1R, resto con stop original;
  - partial_50_be:       50% a +1R, resto con BE desde la vela siguiente.

El baseline y el BE son los brazos full-engine oficiales. El parcial+BE es el
brazo full-engine ya generado. El parcial sin BE se simula en esta corrida.
No se modifica el lock, la configuración, el CSV raw ni el holdout.
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
from run_partial_exit_1r_full import (  # noqa: E402
    FullManagementExecution,
    _aggregate,
    _load_lock,
    _summary_with_flow,
    _trade_map,
)

OUT = REPORTS / "partial_exit_1r_attribution.json"
MD = REPORTS / "PARTIAL_EXIT_1R_ATTRIBUTION.md"
BASELINE = "filter"
BE = "be_1r"
PARTIAL = "partial_50_no_be"
COMBINED = "partial_50_be"
POLICIES = (BASELINE, BE, PARTIAL, COMBINED)
WORKERS = 2
OFFICIAL = REPORTS / "breakeven_1r_protocol_all.json"
COMBINED_SOURCE = REPORTS / "partial_exit_1r_full.json"


def _run_partial_no_be_group(
    keys: tuple[str, ...],
) -> dict[tuple[str, str], dict[str, Any]]:
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
        FullManagementExecution.policy = PARTIAL
        bt.ExecutionEngine = FullManagementExecution
        started = time.perf_counter()
        result = bt._simulate(
            config,
            window_sessions,
            source,
            f"{window['id']}-{PARTIAL}",
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
                f"{window['id']} {PARTIAL}: {len(bad_ratio)} ops con ratio < "
                f"{FILTER_RATIO}"
            )
        out[(window["id"], PARTIAL)] = {
            "window": window,
            "sessions": len(window_sessions),
            "metrics": _summary_with_flow(
                trades, float(lock["settings"]["risk"]["initial_capital"])
            ),
            "trades": trades,
            "elapsed_sec": round(time.perf_counter() - started, 1),
        }
        print(
            f"[{window['id']} {PARTIAL}] {len(trades)} ops, "
            f"neto {result['metrics']['net_profit']}, "
            f"DD {result['metrics']['max_drawdown']} "
            f"({time.perf_counter() - started:.1f}s)",
            flush=True,
        )
    return out


def _source_rows(
    payload: dict[str, Any], policy: str, lock: dict[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    windows = {w["id"]: w for w in lock["windows"]}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for window in WINDOW_IDS:
        trades = [
            t
            for t in payload["arms"][policy]["trades"]
            if t.get("window") == window
        ]
        out[(window, policy)] = {
            "window": windows[window],
            "sessions": int(windows[window]["sessions"]),
            "metrics": _summary_with_flow(
                trades, float(lock["settings"]["risk"]["initial_capital"])
            ),
            "trades": trades,
            "elapsed_sec": None,
        }
    return out


def _effect_with_deltas(
    source: dict[str, Any], target: dict[str, Any], source_trades: list[dict[str, Any]], target_trades: list[dict[str, Any]]
) -> dict[str, Any]:
    effect = _effect(source_trades, target_trades)
    effect.update(
        {
            "net_profit_delta": round(
                float(target["net_profit"]) - float(source["net_profit"]), 2
            ),
            "cashflow_dd_delta": round(
                float(target["cashflow_max_drawdown"])
                - float(source["cashflow_max_drawdown"]),
                2,
            ),
            "trades_delta": int(target["trades"]) - int(source["trades"]),
        }
    )
    return effect


def _qty_diff(
    source_trades: list[dict[str, Any]], target_trades: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source = _trade_map(source_trades)
    target = _trade_map(target_trades)
    out = []
    for sid, before in source.items():
        after = target.get(sid)
        if after is None:
            continue
        if int(before["qty"]) != int(after["qty"]):
            out.append(
                {
                    "signal_id": sid,
                    "source_qty": int(before["qty"]),
                    "target_qty": int(after["qty"]),
                }
            )
    return out


def _arm_extra(trades: list[dict[str, Any]]) -> dict[str, Any]:
    partials = [
        t for t in trades if (t.get("meta") or {}).get("partial_exit")
    ]
    be_moved = [
        t for t in trades if (t.get("meta") or {}).get("_mgmt_moved")
    ]
    return {
        "signals_with_partial": len(partials),
        "signals_without_partial": len(trades) - len(partials),
        "partial_qty_total": sum(
            int((t.get("meta") or {}).get("partial_qty") or 0) for t in partials
        ),
        "partial_pnl_total": round(
            sum(float((t.get("meta") or {}).get("partial_pnl") or 0.0) for t in partials),
            2,
        ),
        "be_moved_signals": len(be_moved),
        "partial_skipped_qty_one": sum(
            1
            for t in trades
            if (t.get("meta") or {}).get("partial_skipped_qty_one")
        ),
    }


def _attribution(arms: dict[str, Any]) -> dict[str, Any]:
    base = arms[BASELINE]["total"]
    be = arms[BE]["total"]
    part = arms[PARTIAL]["total"]
    combined = arms[COMBINED]["total"]
    base_dd = float(base["cashflow_max_drawdown"])
    be_dd = float(be["cashflow_max_drawdown"])
    part_dd = float(part["cashflow_max_drawdown"])
    combined_dd = float(combined["cashflow_max_drawdown"])
    base_net = float(base["net_profit"])
    be_net = float(be["net_profit"])
    part_net = float(part["net_profit"])
    combined_net = float(combined["net_profit"])

    be_dd_reduction = round(base_dd - be_dd, 2)
    part_dd_reduction = round(base_dd - part_dd, 2)
    combined_dd_reduction = round(base_dd - combined_dd, 2)
    be_net_delta = round(be_net - base_net, 2)
    part_net_delta = round(part_net - base_net, 2)
    combined_net_delta = round(combined_net - base_net, 2)

    return {
        "baseline_net": round(base_net, 2),
        "baseline_dd": round(base_dd, 2),
        "be": {
            "net_delta": be_net_delta,
            "dd_reduction": be_dd_reduction,
            "net": round(be_net, 2),
            "dd": round(be_dd, 2),
        },
        "partial": {
            "net_delta": part_net_delta,
            "dd_reduction": part_dd_reduction,
            "net": round(part_net, 2),
            "dd": round(part_dd, 2),
        },
        "combined": {
            "net_delta": combined_net_delta,
            "dd_reduction": combined_dd_reduction,
            "net": round(combined_net, 2),
            "dd": round(combined_dd, 2),
        },
        "be_incremental_over_partial": {
            "net_delta": round(combined_net - part_net, 2),
            "dd_reduction": round(part_dd - combined_dd, 2),
            "net": round(combined_net - part_net, 2),
            "dd": round(combined_dd, 2),
        },
        "partial_incremental_over_be": {
            "net_delta": round(combined_net - be_net, 2),
            "dd_reduction": round(be_dd - combined_dd, 2),
            "net": round(combined_net - be_net, 2),
            "dd": round(combined_dd, 2),
        },
        "interaction": {
            "net": round(combined_net_delta - be_net_delta - part_net_delta, 2),
            "dd_reduction": round(
                combined_dd_reduction - be_dd_reduction - part_dd_reduction, 2
            ),
        },
        "decomposition_note": (
            "Los deltas no son necesariamente aditivos por la qty dinámica y por "
            "la interacción de ambas gestiones sobre la misma cola de operaciones."
        ),
    }


def _matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    keys = (
        "trades",
        "wins",
        "losses",
        "net_profit",
        "gross_profit",
        "gross_loss",
        "profit_factor",
        "expectancy",
        "max_drawdown",
        "worst_loss_streak",
    )
    return all(
        abs(float(actual.get(key) or 0.0) - float(expected.get(key) or 0.0)) <= 0.01
        for key in keys
    )


def main() -> None:
    lock = _load_lock()
    if sum(int(w["sessions"]) for w in lock["windows"]) != 362:
        raise RuntimeError("Las ventanas no suman 362 sesiones")
    if lock["holdout"]["start"] != HOLDOUT_START.isoformat():
        raise RuntimeError("Inicio de holdout inesperado")

    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    combined_source = json.loads(COMBINED_SOURCE.read_text(encoding="utf-8"))
    results: dict[tuple[str, str], dict[str, Any]] = {}
    results.update(_source_rows(official, BASELINE, lock))
    results.update(_source_rows(official, BE, lock))
    results.update(_source_rows(combined_source, COMBINED, lock))
    print(
        "Baseline/BE/parcial+BE reutilizados de sus artefactos full-engine; "
        f"ejecutando {PARTIAL}",
        flush=True,
    )

    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        futures = {
            pool.submit(_run_partial_no_be_group, group): group for group in GROUPS
        }
        for future in as_completed(futures):
            results.update(future.result())
    print(f"Simulaciones terminadas en {time.perf_counter() - started:.1f}s", flush=True)

    arms = {policy: _aggregate(results, policy) for policy in POLICIES}
    base_trades = arms[BASELINE]["trades"]
    be_trades = arms[BE]["trades"]
    part_trades = arms[PARTIAL]["trades"]
    combined_trades = arms[COMBINED]["trades"]
    base_map = _trade_map(base_trades)
    be_map = _trade_map(be_trades)
    part_map = _trade_map(part_trades)
    combined_map = _trade_map(combined_trades)

    effects = {
        "be_vs_baseline": _effect_with_deltas(
            arms[BASELINE]["total"], arms[BE]["total"], base_trades, be_trades
        ),
        "partial_vs_baseline": _effect_with_deltas(
            arms[BASELINE]["total"], arms[PARTIAL]["total"], base_trades, part_trades
        ),
        "combined_vs_baseline": _effect_with_deltas(
            arms[BASELINE]["total"], arms[COMBINED]["total"], base_trades, combined_trades
        ),
        "combined_vs_partial": _effect_with_deltas(
            arms[PARTIAL]["total"], arms[COMBINED]["total"], part_trades, combined_trades
        ),
        "combined_vs_be": _effect_with_deltas(
            arms[BE]["total"], arms[COMBINED]["total"], be_trades, combined_trades
        ),
    }
    attribution = _attribution(arms)

    qty_diffs = {
        "be_vs_baseline": _qty_diff(base_trades, be_trades),
        "partial_vs_baseline": _qty_diff(base_trades, part_trades),
        "combined_vs_baseline": _qty_diff(base_trades, combined_trades),
        "combined_vs_partial": _qty_diff(part_trades, combined_trades),
        "combined_vs_be": _qty_diff(be_trades, combined_trades),
    }

    per_signal = []
    for sid, base in base_map.items():
        be = be_map.get(sid) or {}
        part = part_map.get(sid) or {}
        combined = combined_map.get(sid) or {}
        per_signal.append(
            {
                "signal_id": sid,
                "baseline_qty": base.get("qty"),
                "be_qty": be.get("qty"),
                "partial_arm_qty": part.get("qty"),
                "combined_arm_qty": combined.get("qty"),
                "baseline_pnl": base.get("pnl"),
                "be_pnl": be.get("pnl"),
                "partial_pnl": part.get("pnl"),
                "combined_pnl": combined.get("pnl"),
                "baseline_exit": base.get("exit_reason"),
                "be_exit": be.get("exit_reason"),
                "partial_exit": part.get("exit_reason"),
                "combined_exit": combined.get("exit_reason"),
                "partial_leg_qty": (part.get("meta") or {}).get("partial_qty"),
                "combined_leg_qty": (combined.get("meta") or {}).get("partial_qty"),
                "partial_be_moved": bool((part.get("meta") or {}).get("_mgmt_moved")),
                "combined_be_moved": bool((combined.get("meta") or {}).get("_mgmt_moved")),
            }
        )
    per_signal.sort(key=lambda row: row["signal_id"])

    signal_sets = {
        policy: set(_trade_map(arms[policy]["trades"])) for policy in POLICIES
    }
    all_same_ids = all(
        signal_sets[BASELINE] == signal_sets[policy] for policy in POLICIES
    )
    filter_ratios = []
    for trade in base_trades:
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

    session_counts = {
        window: {
            "expected": int(next(w["sessions"] for w in lock["windows"] if w["id"] == window)),
            PARTIAL: results[(window, PARTIAL)]["sessions"],
        }
        for window in WINDOW_IDS
    }
    qty_by_arm = {
        policy: sorted({int(t["qty"]) for t in arms[policy]["trades"]})
        for policy in POLICIES
    }
    extra = {policy: _arm_extra(arms[policy]["trades"]) for policy in POLICIES}

    output = {
        "schema": "partial-exit-1r-attribution-v1",
        "protocol": {
            "lock": str(LOCK_PATH.relative_to(ROOT)),
            "version": lock.get("protocol_version"),
            "windows": list(WINDOW_IDS),
            "sessions": sum(int(w["sessions"]) for w in lock["windows"]),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_used": False,
            "engine": "server.backtest._simulate + FullManagementExecution",
            "qty": "dinámica del RiskManager (1% equity, max_contracts=5)",
            "sources": {
                BASELINE: str(OFFICIAL.relative_to(ROOT)),
                BE: str(OFFICIAL.relative_to(ROOT)),
                PARTIAL: "corrida nueva en este motor",
                COMBINED: str(COMBINED_SOURCE.relative_to(ROOT)),
            },
        },
        "filter": {
            "field": "risk.min_stop_or_ratio",
            "value": FILTER_RATIO,
            "same_for_all_arms": True,
        },
        "rules": {
            BASELINE: "sin gestión a 1R",
            BE: "stop a entrada desde la vela siguiente a +1R",
            PARTIAL: "50% a +1R; resto con stop original",
            COMBINED: "50% a +1R; resto con BE desde la vela siguiente",
            "partial_fraction": 0.5,
            "partial_r": 1.0,
            "partial_qty_formula": "qty // 2; si qty<2 no hay parcial",
            "partial_same_bar_target": True,
            "initial_stop_priority": True,
            "cashflow_dd": "el parcial se acredita al ejecutarse; el resto al cierre",
        },
        "arms": arms,
        "effects": effects,
        "attribution": attribution,
        "extra": extra,
        "qty_diffs": qty_diffs,
        "per_signal": per_signal,
        "verification": {
            "session_counts": session_counts,
            "total_sessions": sum(item[PARTIAL] for item in session_counts.values()),
            "all_arms_same_signal_ids": all_same_ids,
            "signal_ids_by_arm": {
                policy: sorted(signal_sets[policy]) for policy in POLICIES
            },
            "dynamic_qty_values_by_arm": qty_by_arm,
            "dynamic_qty_is_variable": len(qty_by_arm[BASELINE]) > 1,
            "filter_min_ratio": round(min(filter_ratios), 6) if filter_ratios else None,
            "filter_ratios_ok": all(value >= FILTER_RATIO - 1e-9 for value in filter_ratios),
            "baseline_vs_official": _matches(
                arms[BASELINE]["total"], official["arms"][BASELINE]["total"]
            ),
            "be_vs_official": _matches(
                arms[BE]["total"], official["arms"][BE]["total"]
            ),
            "combined_vs_source": _matches(
                arms[COMBINED]["total"],
                combined_source["arms"][COMBINED]["total"],
            ),
            "partial_only_be_moved": extra[PARTIAL]["be_moved_signals"],
            "partial_only_no_be": extra[PARTIAL]["be_moved_signals"] == 0,
            "last_evaluated_session": max(w["end"] for w in lock["windows"]),
            "last_trade_session": last_trade_day.isoformat(),
            "holdout_used": False,
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    base = arms[BASELINE]["total"]
    be = arms[BE]["total"]
    part = arms[PARTIAL]["total"]
    combined = arms[COMBINED]["total"]
    lines = [
        "# Atribución del parcial 50% y del BE a +1R",
        "",
        "**Alcance:** W1-W6, 362 sesiones, motor completo con qty dinámica.  ",
        f"**Puerta común:** `min_stop_or_ratio = {FILTER_RATIO}`.  ",
        "**Holdout:** no usado.  ",
        "**Fuentes:** baseline/BE del protocolo oficial; parcial+BE del artefacto full-engine; parcial sin BE de esta corrida.  ",
        "**Fuente estructurada:** `reports/backtest/partial_exit_1r_attribution.json`",
        "",
        "## Brazos",
        "",
        "| Brazo | Salida a +1R | Resto |",
        "|---|---|---|",
        "| `filter` | Nada | Stop y target originales. |",
        "| `be_1r` | Nada | BE desde la vela siguiente. |",
        "| `partial_50_no_be` | 50% | Stop original. |",
        "| `partial_50_be` | 50% | BE desde la vela siguiente. |",
        "",
        "La qty se calcula con el 1% del equity y `max_contracts=5`; no se impone la qty fija del replay antiguo.",
        "",
        "## Resultado",
        "",
        "| Brazo | Ops | Neto USD | PF | R medio | DD caja USD | DD caja % | W/L | Peor racha | P&L parcial | BE movidos |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for policy, label in (
        (BASELINE, "Baseline"),
        (BE, "BE solo"),
        (PARTIAL, "Parcial solo"),
        (COMBINED, "Parcial + BE"),
    ):
        arm = arms[policy]["total"]
        info = extra[policy]
        lines.append(
            f"| {label} | {arm['trades']} | {arm['net_profit']:+.2f} | "
            f"{arm['profit_factor']} | {arm['avg_r']:.2f} | "
            f"{arm['cashflow_max_drawdown']:.2f} | "
            f"{arm['cashflow_max_drawdown_pct']:.2f}% | "
            f"{arm['wins']}/{arm['losses']} | {arm['worst_loss_streak']} | "
            f"{info['partial_pnl_total']:+.2f} | {info['be_moved_signals']} |"
        )
    lines += [
        "",
        "## Descomposición",
        "",
        "| Concepto | Δ neto vs baseline | DD caja | Δ DD vs baseline | Recorte de DD |",
        "|---|---:|---:|---:|---:|",
        f"| BE solo | {attribution['be']['net_delta']:+.2f} | {attribution['be']['dd']:.2f} | {attribution['be']['dd'] - attribution['baseline_dd']:+.2f} | {attribution['be']['dd_reduction']:.2f} |",
        f"| Parcial solo | {attribution['partial']['net_delta']:+.2f} | {attribution['partial']['dd']:.2f} | {attribution['partial']['dd'] - attribution['baseline_dd']:+.2f} | {attribution['partial']['dd_reduction']:.2f} |",
        f"| Parcial + BE | {attribution['combined']['net_delta']:+.2f} | {attribution['combined']['dd']:.2f} | {attribution['combined']['dd'] - attribution['baseline_dd']:+.2f} | {attribution['combined']['dd_reduction']:.2f} |",
        f"| Interacción | {attribution['interaction']['net']:+.2f} | — | — | {attribution['interaction']['dd_reduction']:+.2f} |",
        "",
        "La interacción es la parte del resultado combinado que no se explica por la suma de los efectos individuales. Es negativa cuando ambas gestiones protegen la misma cola; la qty dinámica también puede hacerla no aditiva.",
        "",
        "## Aportes incrementales",
        "",
        "| Pregunta | Δ neto | Δ DD / recorte adicional |",
        "|---|---:|---:|",
        f"| ¿Cuánto añade el BE al parcial? | {attribution['be_incremental_over_partial']['net_delta']:+.2f} | {attribution['be_incremental_over_partial']['dd_reduction']:+.2f} |",
        f"| ¿Cuánto añade el parcial al BE? | {attribution['partial_incremental_over_be']['net_delta']:+.2f} | {attribution['partial_incremental_over_be']['dd_reduction']:+.2f} |",
        "",
        "**Lectura:** el recorte de DD del parcial solo es "
        f"**{attribution['partial']['dd_reduction']:.2f}** y cuesta "
        f"**{abs(attribution['partial']['net_delta']):.2f}** de neto. El BE solo recorta "
        f"**{attribution['be']['dd_reduction']:.2f}** y suma "
        f"**{attribution['be']['net_delta']:+.2f}**. El combinado recorta "
        f"**{attribution['combined']['dd_reduction']:.2f}** y resta "
        f"**{abs(attribution['combined']['net_delta']):.2f}**; añadir BE al parcial "
        f"mejora el neto en **{attribution['be_incremental_over_partial']['net_delta']:+.2f}** "
        f"y recorta **{attribution['be_incremental_over_partial']['dd_reduction']:.2f}** más. "
        f"Añadir el parcial al BE solo recorta **{attribution['partial_incremental_over_be']['dd_reduction']:.2f}** "
        f"más y cuesta **{abs(attribution['partial_incremental_over_be']['net_delta']):.2f}** de neto. "
        "La interacción de DD es **"
        f"{attribution['interaction']['dd_reduction']:+.2f}**: ambas gestiones protegen la misma cola.",
        "",
        "## Detalle por señal",
        "",
        "| Señal | Qty parcial | Parcial ejecutado | P&L base | P&L parcial | Δ parcial | P&L BE | P&L parcial+BE | Δ BE sobre parcial | Salida parcial | Salida combinada |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in per_signal:
        delta_partial = round(float(row["partial_pnl"]) - float(row["baseline_pnl"]), 2)
        delta_be = round(float(row["combined_pnl"]) - float(row["partial_pnl"]), 2)
        lines.append(
            f"| `{row['signal_id']}` | {row['partial_arm_qty']} | {row['partial_leg_qty']} | "
            f"{row['baseline_pnl']:+.2f} | {row['partial_pnl']:+.2f} | "
            f"{delta_partial:+.2f} | {row['be_pnl']:+.2f} | "
            f"{row['combined_pnl']:+.2f} | {delta_be:+.2f} | "
            f"{row['partial_exit']} | {row['combined_exit']} |"
        )
    lines += [
        "",
        "## Qty dinámica",
        "",
        f"- Qty observada: `{qty_by_arm}`.",
        f"- Señales con qty distinta al baseline: parcial **{len(qty_diffs['partial_vs_baseline'])}**, BE **{len(qty_diffs['be_vs_baseline'])}**, parcial+BE **{len(qty_diffs['combined_vs_baseline'])}**.",
        f"- Parcial sin BE: **{extra[PARTIAL]['signals_with_partial']}** señales con parcial; BE movidos: **{extra[PARTIAL]['be_moved_signals']}** (debe ser 0).",
        "",
        "## Verificación",
        "",
        f"- Sesiones evaluadas: **{output['verification']['total_sessions']}**.",
        f"- Mismos IDs de señal en las cuatro ramas: **{all_same_ids}**.",
        f"- Ratio stop/ORB mínimo: **{output['verification']['filter_min_ratio']}** (puerta {FILTER_RATIO}).",
        f"- Baseline vs oficial: **{output['verification']['baseline_vs_official']}**.",
        f"- BE vs oficial: **{output['verification']['be_vs_official']}**.",
        f"- Parcial+BE vs artefacto fuente: **{output['verification']['combined_vs_source']}**.",
        f"- Parcial sin BE no movió ningún stop a BE: **{output['verification']['partial_only_no_be']}**.",
        f"- Último trade: **{last_trade_day.isoformat()}**; holdout usado: **False**.",
        "",
        "No se modificaron lock, configuración, CSV raw ni holdout. Las 14 operaciones son in-sample y no alcanzan el mínimo de 80 para promoción.",
        "",
        "## Artefactos",
        "",
        "- `reports/backtest/run_partial_1r_attribution.py`",
        "- `reports/backtest/partial_exit_1r_attribution.json`",
        "- `reports/backtest/PARTIAL_EXIT_1R_ATTRIBUTION.md`",
    ]
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "=" * 84)
    print("ATRIBUCION: PARCIAL 50% Y BE A +1R")
    print("=" * 84)
    for policy in POLICIES:
        arm = arms[policy]["total"]
        print(
            f"{policy:18s} ops {arm['trades']:2d} | neto {arm['net_profit']:+9.2f} | "
            f"PF {str(arm['profit_factor']):>6s} | DD {arm['cashflow_max_drawdown']:8.2f} "
            f"({arm['cashflow_max_drawdown_pct']:.2f}%) | W/L {arm['wins']}/{arm['losses']}"
        )
    print(
        f"BE solo: Delta neto {attribution['be']['net_delta']:+.2f}, recorte DD {attribution['be']['dd_reduction']:.2f}"
    )
    print(
        f"Parcial solo: Delta neto {attribution['partial']['net_delta']:+.2f}, "
        f"recorte DD {attribution['partial']['dd_reduction']:.2f}"
    )
    print(
        f"Combinado: Delta neto {attribution['combined']['net_delta']:+.2f}, "
        f"recorte DD {attribution['combined']['dd_reduction']:.2f}"
    )
    print(f"JSON: {OUT}")
    print(f"MD: {MD}")


if __name__ == "__main__":
    main()
