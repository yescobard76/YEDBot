#!/usr/bin/env python3
"""Factorial 2x2 stop x frecuencia con qty=1 y metricas en R.

Diseno
------
Factor stop: 200 vs 300 ticks (max_sl_ticks).
Factor frecuencia: 150/12 vs 210/24 (setup_validity_minutes/retest_tolerance_ticks).

Celdas:
  A: stop 200, frecuencia 150/12  (original)
  B: stop 200, frecuencia 210/24  (P2)
  C: stop 300, frecuencia 150/12  (nueva corrida)
  D: stop 300, frecuencia 210/24  (manual)

A/B/D se reconstruyen desde operaciones ya medidas: el R por operacion es
invariante al tamano de posicion y max_contracts=1 solo cambia qty, no las
senales. C se ejecuta nueva con max_contracts=1. Un control D-W1 a qty=1
verifica que las senales y el R coinciden con las operaciones ya medidas.

No escribe configuracion, no toca la DB del 8765 y no abre el holdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "reports" / "backtest"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from _windows import WINDOWS, WINDOW_FIRST  # noqa: E402
from server.backtest import _simulate, prepare_dataset  # noqa: E402
from server.config import Settings, apply_settings  # noqa: E402
from server.timeutil import et_date  # noqa: E402

MANUAL_PATH = ROOT / "data/config.json"
FRESH_ORIGINAL = ROOT / "reports/autoloop/_fresh_original_1x.json"
FRESH_MANUAL = ROOT / "reports/autoloop/_fresh_manual_1x.json"
PROGRESO = ROOT / "reports/autoloop/progreso.json"
CELL_C_PATH = ROOT / "reports/backtest/_factorial_cell_c.json"
CONTROL_PATH = ROOT / "reports/backtest/_factorial_control_w1.json"
OUT_JSON = ROOT / "reports/backtest/factorial_stop_validity.json"
OUT_CSV = ROOT / "reports/backtest/factorial_stop_validity.csv"
HOLDOUT_START = date(2026, 7, 1)

CELL_C_PATCH: dict[str, Any] = {
    "risk": {"max_contracts": 1, "max_sl_ticks": 300},
    "strategy": {"setup_validity_minutes": 150, "retest_tolerance_ticks": 12},
}
CONTROL_PATCH: dict[str, Any] = {"risk": {"max_contracts": 1}}

CELL_META = {
    "A": {"stop": 200, "validity": 150, "retest": 12, "source": "original ya medido"},
    "B": {"stop": 200, "validity": 210, "retest": 24, "source": "P2 ya medido (sl_200)"},
    "C": {"stop": 300, "validity": 150, "retest": 12, "source": "corrida nueva qty=1"},
    "D": {"stop": 300, "validity": 210, "retest": 24, "source": "manual ya medido"},
}

WINDOW_BY_KEY = {
    key: (date.fromisoformat(start), date.fromisoformat(end), days)
    for key, start, end, days in WINDOWS
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def annotate_window(trades: list[dict]) -> list[dict]:
    out: list[dict] = []
    for trade in trades:
        day = et_date(int(trade["exit_ts"]))
        if day >= HOLDOUT_START:
            raise RuntimeError(f"Operacion en holdout: {day}")
        for key, start, end, _days in WINDOWS:
            if date.fromisoformat(start) <= day <= date.fromisoformat(end):
                item = dict(trade)
                item["window"] = key
                item["exit_date"] = day.isoformat()
                out.append(item)
                break
        else:
            raise RuntimeError(f"Operacion fuera de W1-W6: {day}")
    return out


def _r_pf(rs: list[float]) -> float | None:
    gross_profit = sum(r for r in rs if r > 0)
    gross_loss = sum(r for r in rs if r < 0)
    if gross_loss >= 0:
        return None
    return gross_profit / abs(gross_loss)


def _max_drawdown_r(rs: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _max_consecutive_losses(rs: list[float]) -> int:
    current = best = 0
    for r in rs:
        if r < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def r_metrics(trades: list[dict]) -> dict[str, Any]:
    ordered = sorted(trades, key=lambda t: (int(t["exit_ts"]), int(t["entry_ts"])))
    rs = [float(t["r_multiple"]) for t in ordered]
    qty = [int(t["qty"]) for t in ordered]
    pnl = [float(t["pnl"]) for t in ordered]
    if not rs:
        return {
            "ops": 0, "total_r": 0.0, "mean_r": 0.0, "r_pf": None,
            "r_dd": 0.0, "rdd_r": None, "win_rate": 0.0, "avg_win_r": None,
            "avg_loss_r": None, "max_consecutive_losses": 0, "net_usd_1": 0.0,
            "net_usd_dynamic": 0.0, "qty_min": None, "qty_max": None,
            "avg_qty": None, "qty_counts": {},
        }
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    r_dd = _max_drawdown_r(rs)
    by_window: dict[str, dict[str, Any]] = {}
    for key, _start, _end, _days in WINDOWS:
        sub = [t for t in ordered if t.get("window") == key]
        srs = [float(t["r_multiple"]) for t in sub]
        by_window[key] = {
            "ops": len(sub),
            "total_r": round(sum(srs), 4),
            "mean_r": round(statistics.fmean(srs), 4) if srs else None,
            "r_pf": round(_r_pf(srs), 4) if _r_pf(srs) is not None else None,
        }
    return {
        "ops": len(rs),
        "total_r": round(sum(rs), 4),
        "mean_r": round(statistics.fmean(rs), 4),
        "r_pf": round(_r_pf(rs), 4) if _r_pf(rs) is not None else None,
        "r_dd": round(r_dd, 4),
        "rdd_r": round(sum(rs) / r_dd, 4) if r_dd > 0 else None,
        "win_rate": round(100 * len(wins) / len(rs), 2),
        "avg_win_r": round(statistics.fmean(wins), 4) if wins else None,
        "avg_loss_r": round(statistics.fmean(losses), 4) if losses else None,
        "max_consecutive_losses": _max_consecutive_losses(rs),
        "net_usd_1": round(sum(p / q for p, q in zip(pnl, qty)), 2),
        "net_usd_dynamic": round(sum(pnl), 2),
        "qty_min": min(qty),
        "qty_max": max(qty),
        "avg_qty": round(sum(qty) / len(qty), 4),
        "qty_counts": {str(q): qty.count(q) for q in sorted(set(qty))},
        "by_window": by_window,
    }


def load_cells(include_c: bool) -> dict[str, list[dict]]:
    cells: dict[str, list[dict]] = {
        "A": annotate_window(read_json(FRESH_ORIGINAL)["trades"]),
        "B": annotate_window(read_json(PROGRESO)["sl_200"]["trades"]),
        "D": annotate_window(read_json(FRESH_MANUAL)["trades"]),
    }
    if include_c:
        if not CELL_C_PATH.exists():
            raise FileNotFoundError(f"Falta {CELL_C_PATH}; ejecuta --run")
        cells["C"] = annotate_window(read_json(CELL_C_PATH)["trades"])
    return cells


def _run_task(task: dict[str, Any]) -> dict[str, Any]:
    base = Settings.model_validate_json(MANUAL_PATH.read_text(encoding="utf-8"))
    cfg = apply_settings(base, task["patch"])
    key, start_s, _end_s, days = task["spec"]
    sessions, source, dataset = prepare_dataset(
        base, days=days, start=date.fromisoformat(start_s)
    )
    last_session = sessions[-1][0]
    if last_session >= HOLDOUT_START:
        raise RuntimeError(f"{task['label']} {key}: sesion en holdout {last_session}")
    started = time.perf_counter()
    result = _simulate(cfg, sessions, source, task["label"], dataset)
    elapsed = time.perf_counter() - started
    trades = result["trades"]
    bad_qty = [int(t["qty"]) for t in trades if int(t["qty"]) != 1]
    if bad_qty:
        raise RuntimeError(f"{task['label']} {key}: qty != 1: {sorted(set(bad_qty))}")
    qty_zero = int(result["metrics"].get("qty_zero_sessions", 0))
    if qty_zero:
        raise RuntimeError(f"{task['label']} {key}: {qty_zero} sesiones con qty=0")
    return {
        "kind": task["kind"],
        "window": key,
        "label": task["label"],
        "patch": task["patch"],
        "elapsed_sec": round(elapsed, 1),
        "sessions": [d.isoformat() for d, _ in sessions],
        "first": sessions[0][0].isoformat(),
        "last": last_session.isoformat(),
        "dataset_id": dataset.get("id"),
        "selected_id": dataset.get("selected_id"),
        "trades": trades,
        "metrics": result["metrics"],
    }


def run_new_cells(workers: int, force: bool) -> None:
    if CELL_C_PATH.exists() and CONTROL_PATH.exists() and not force:
        print(f"Reutilizo {CELL_C_PATH.name} y {CONTROL_PATH.name} (usa --force para repetir)")
        return
    tasks: list[dict[str, Any]] = []
    for spec in WINDOWS:
        tasks.append(
            {
                "kind": "cell_c",
                "spec": spec,
                "patch": CELL_C_PATCH,
                "label": f"factorial_C_{spec[0]}",
            }
        )
    tasks.append(
        {
            "kind": "control_w1",
            "spec": WINDOWS[0],
            "patch": CONTROL_PATCH,
            "label": "factorial_control_D_W1_qty1",
        }
    )
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(_run_task, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            result = future.result()
            results.append(result)
            print(
                f"[{result['kind']} {result['window']}] {result['first']}..{result['last']} "
                f"{len(result['trades'])} ops, {result['elapsed_sec']}s",
                flush=True,
            )
    cell_c = [r for r in results if r["kind"] == "cell_c"]
    control = [r for r in results if r["kind"] == "control_w1"]
    if len(cell_c) != len(WINDOWS) or len(control) != 1:
        raise RuntimeError("Faltan resultados de la celda C o del control")
    cell_c.sort(key=lambda r: [s[0] for s in WINDOWS].index(r["window"]))
    cell_payload = {
        "label": "C",
        "design": CELL_META["C"],
        "patch": CELL_C_PATCH,
        "created_ts": int(time.time()),
        "seconds": round(time.perf_counter() - started, 1),
        "windows": {
            r["window"]: {
                "first": r["first"],
                "last": r["last"],
                "sessions": r["sessions"],
                "elapsed_sec": r["elapsed_sec"],
                "dataset_id": r["dataset_id"],
                "selected_id": r["selected_id"],
                "metrics": r["metrics"],
            }
            for r in cell_c
        },
        "trades": [t for r in cell_c for t in r["trades"]],
    }
    control_payload = {
        "label": "control_D_W1_qty1",
        "patch": CONTROL_PATCH,
        "created_ts": int(time.time()),
        "window": control[0]["window"],
        "first": control[0]["first"],
        "last": control[0]["last"],
        "dataset_id": control[0]["dataset_id"],
        "selected_id": control[0]["selected_id"],
        "metrics": control[0]["metrics"],
        "trades": control[0]["trades"],
    }
    CELL_C_PATH.write_text(
        json.dumps(cell_payload, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    CONTROL_PATH.write_text(
        json.dumps(control_payload, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    print(f"Escrito {CELL_C_PATH} y {CONTROL_PATH}")


def _effect(high: float, low: float) -> dict[str, float]:
    return {"delta": round(high - low, 4), "pct": round(100 * (high / low - 1), 2) if low else None}


def factorial_effects(metrics: dict[str, dict]) -> dict[str, Any]:
    mean = {k: float(v["mean_r"]) for k, v in metrics.items()}
    total = {k: float(v["total_r"]) for k, v in metrics.items()}
    ops = {k: int(v["ops"]) for k, v in metrics.items()}

    def block(values: dict[str, float]) -> dict[str, Any]:
        stop_150 = values["C"] - values["A"]
        stop_210 = values["D"] - values["B"]
        freq_200 = values["B"] - values["A"]
        freq_300 = values["D"] - values["C"]
        stop_main = (values["C"] + values["D"]) / 2 - (values["A"] + values["B"]) / 2
        freq_main = (values["B"] + values["D"]) / 2 - (values["A"] + values["C"]) / 2
        interaction = (values["D"] - values["C"]) - (values["B"] - values["A"])
        return {
            "stop_200_a_300_en_freq_150": round(stop_150, 4),
            "stop_200_a_300_en_freq_210": round(stop_210, 4),
            "stop_efecto_principal": round(stop_main, 4),
            "freq_150_a_210_en_stop_200": round(freq_200, 4),
            "freq_150_a_210_en_stop_300": round(freq_300, 4),
            "freq_efecto_principal": round(freq_main, 4),
            "interaccion": round(interaction, 4),
        }

    effects_mean = block(mean)
    effects_total = block(total)
    effects_ops = block({k: float(v) for k, v in ops.items()})

    per_window: dict[str, Any] = {}
    for key, _start, _end, _days in WINDOWS:
        wm = {cell: metrics[cell]["by_window"][key]["mean_r"] for cell in "ABCD"}
        if any(v is None for v in wm.values()):
            per_window[key] = {"skip": "ventana sin operaciones en alguna celda"}
            continue
        per_window[key] = {
            "mean_r": {cell: round(float(wm[cell]), 4) for cell in "ABCD"},
            "stop_efecto_principal": round(
                (wm["C"] + wm["D"]) / 2 - (wm["A"] + wm["B"]) / 2, 4
            ),
            "freq_efecto_principal": round(
                (wm["B"] + wm["D"]) / 2 - (wm["A"] + wm["C"]) / 2, 4
            ),
        }
    stop_windows = [v["stop_efecto_principal"] for v in per_window.values() if "stop_efecto_principal" in v]
    freq_windows = [v["freq_efecto_principal"] for v in per_window.values() if "freq_efecto_principal" in v]
    return {
        "mean_r": effects_mean,
        "total_r": effects_total,
        "ops": effects_ops,
        "per_window_mean_r": per_window,
        "robustez": {
            "ventanas_stop_positivas": sum(1 for v in stop_windows if v > 0),
            "ventanas_stop_negativas": sum(1 for v in stop_windows if v < 0),
            "ventanas_freq_positivas": sum(1 for v in freq_windows if v > 0),
            "ventanas_freq_negativas": sum(1 for v in freq_windows if v < 0),
            "ventanas_evaluadas": len(stop_windows),
        },
    }


def contract_panel(metrics: dict[str, dict]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cell in "ABD":
        m = metrics[cell]
        out[cell] = {
            "max_qty_historico": m["qty_max"],
            "net_usd_dinamico": m["net_usd_dynamic"],
            "net_usd_qty1_derivado": m["net_usd_1"],
            "delta_usd_por_contratos": round(m["net_usd_dynamic"] - m["net_usd_1"], 2),
            "delta_usd_pct_dinamico": round(
                100 * (m["net_usd_dynamic"] - m["net_usd_1"]) / m["net_usd_dynamic"], 2
            ) if m["net_usd_dynamic"] else None,
            "avg_qty": m["avg_qty"],
            "total_r": m["total_r"],
            "mean_r": m["mean_r"],
            "nota": "R no cambia; el delta USD es sizing, no edge",
        }
    out["C"] = {
        "max_qty_historico": 1,
        "net_usd_dinamico": metrics["C"]["net_usd_dynamic"],
        "net_usd_qty1_derivado": metrics["C"]["net_usd_1"],
        "delta_usd_por_contratos": 0.0,
        "delta_usd_pct_dinamico": 0.0,
        "avg_qty": metrics["C"]["avg_qty"],
        "total_r": metrics["C"]["total_r"],
        "mean_r": metrics["C"]["mean_r"],
        "nota": "celda nueva ya ejecutada a qty=1",
    }
    return out


def validate_control(cells: dict[str, list[dict]]) -> dict[str, Any]:
    control = read_json(CONTROL_PATH)
    d_w1 = [t for t in cells["D"] if t["window"] == "W1"]
    c_trades = control["trades"]
    if any(int(t["qty"]) != 1 for t in c_trades):
        raise RuntimeError("El control no quedo a qty=1")

    def key(t: dict) -> tuple:
        return (
            int(t["entry_ts"]),
            int(t["exit_ts"]),
            t["direction"],
            round(float(t["entry_price"]), 4),
            round(float(t["exit_price"]), 4),
            round(float(t["r_multiple"]), 4),
        )

    d_keys = sorted(key(t) for t in d_w1)
    c_keys = sorted(key(t) for t in c_trades)
    if d_keys != c_keys:
        only_d = [k for k in d_keys if k not in c_keys][:5]
        only_c = [k for k in c_keys if k not in d_keys][:5]
        raise RuntimeError(
            f"Control D-W1 no reproduce las senales: D={len(d_keys)} C={len(c_keys)} "
            f"only_D={only_d} only_C={only_c}"
        )
    d_r = sum(float(t["r_multiple"]) for t in d_w1)
    c_r = sum(float(t["r_multiple"]) for t in c_trades)
    d_usd1 = sum(float(t["pnl"]) / int(t["qty"]) for t in d_w1)
    c_usd = sum(float(t["pnl"]) for t in c_trades)
    if abs(d_r - c_r) > 0.02:
        raise RuntimeError(f"Control R {c_r} != D {d_r}")
    if abs(d_usd1 - c_usd) > 0.05:
        raise RuntimeError(f"Control USD1 {c_usd} != D {d_usd1}")
    return {
        "estado": "ok",
        "ventana": "W1",
        "ops": len(c_trades),
        "r_control": round(c_r, 4),
        "r_manual_derivado": round(d_r, 4),
        "usd_control": round(c_usd, 2),
        "usd_manual_qty1_derivado": round(d_usd1, 2),
        "qty": sorted({int(t["qty"]) for t in c_trades}),
        "conclusion": "qty=1 no altera senales ni R; las celdas A/B/D son validas",
    }


def build_analysis() -> dict[str, Any]:
    cells = load_cells(include_c=True)
    metrics = {cell: r_metrics(cells[cell]) for cell in "ABCD"}
    control = validate_control(cells)
    effects = factorial_effects(metrics)
    contracts = contract_panel(metrics)
    source_meta = {
        "A": str(FRESH_ORIGINAL.relative_to(ROOT)),
        "B": str(PROGRESO.relative_to(ROOT)) + "#sl_200",
        "C": str(CELL_C_PATH.relative_to(ROOT)),
        "D": str(FRESH_MANUAL.relative_to(ROOT)),
    }
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "design": {
            "tipo": "factorial 2x2",
            "stop": [200, 300],
            "frecuencia": ["150/12", "210/24"],
            "qty": 1,
            "metrica_principal": "R por operacion (r_multiple)",
            "celdas": CELL_META,
            "holdout": "no abierto; solo W1-W6 (2025-01-10..2026-06-30)",
        },
        "cell_metrics": metrics,
        "effects": effects,
        "contracts": contracts,
        "control": control,
        "sources": source_meta,
    }


def write_outputs(analysis: dict[str, Any]) -> None:
    OUT_JSON.write_text(
        json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    rows = []
    for cell in "ABCD":
        m = analysis["cell_metrics"][cell]
        meta = analysis["design"]["celdas"][cell]
        rows.append(
            {
                "celda": cell,
                "stop_ticks": meta["stop"],
                "validez_min": meta["validity"],
                "retest_ticks": meta["retest"],
                "qty": 1,
                "ops": m["ops"],
                "total_r": m["total_r"],
                "mean_r": m["mean_r"],
                "r_pf": m["r_pf"],
                "r_dd": m["r_dd"],
                "rdd_r": m["rdd_r"],
                "win_rate": m["win_rate"],
                "avg_win_r": m["avg_win_r"],
                "avg_loss_r": m["avg_loss_r"],
                "max_consec_losses": m["max_consecutive_losses"],
                "net_usd_1": m["net_usd_1"],
                "net_usd_dinamico": m["net_usd_dynamic"],
                "max_qty_historico": m["qty_max"],
            }
        )
    with OUT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Escrito {OUT_JSON} y {OUT_CSV}")


def print_summary(analysis: dict[str, Any]) -> None:
    print("\nCELDAS (qty=1, R)")
    print("celda stop freq  ops  total_r mean_r  r_pf  r_dd  rdd_r  win%  usd_qty1  qty_max_hist")
    for cell in "ABCD":
        m = analysis["cell_metrics"][cell]
        meta = analysis["design"]["celdas"][cell]
        print(
            f"{cell:>5} {meta['stop']:>4} {meta['validity']}/{meta['retest']:<3} "
            f"{m['ops']:>4} {m['total_r']:>8.2f} {m['mean_r']:>6.3f} "
            f"{str(m['r_pf']):>5} {m['r_dd']:>5.2f} {str(m['rdd_r']):>5} "
            f"{m['win_rate']:>5.1f} {m['net_usd_1']:>9.2f} {m['qty_max']:>11}"
        )
    ef = analysis["effects"]
    print("\nEFECTOS PRINCIPALES (R por operacion)")
    for key in (
        "stop_200_a_300_en_freq_150",
        "stop_200_a_300_en_freq_210",
        "stop_efecto_principal",
        "freq_150_a_210_en_stop_200",
        "freq_150_a_210_en_stop_300",
        "freq_efecto_principal",
        "interaccion",
    ):
        print(f"  {key:>32}: {ef['mean_r'][key]:+.4f}")
    print("\nROBUSTEZ POR VENTANA")
    print(json.dumps(ef["robustez"], ensure_ascii=False))
    print("\nCONTROL")
    print(json.dumps(analysis["control"], ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="ejecuta la celda C y el control")
    parser.add_argument("--analyze", action="store_true", help="solo analiza artefactos existentes")
    parser.add_argument("--force", action="store_true", help="repite la corrida aunque exista")
    parser.add_argument("--workers", type=int, default=4, help="procesos paralelos (default 4)")
    args = parser.parse_args()
    if not args.run and not args.analyze:
        args.run = args.analyze = True
    if args.run:
        run_new_cells(workers=args.workers, force=args.force)
    if args.analyze or args.run:
        analysis = build_analysis()
        write_outputs(analysis)
        print_summary(analysis)


if __name__ == "__main__":
    main()
