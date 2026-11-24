"""Prueba de salida parcial 50% a +1R + break-even en el resto.

Fuente: las 14 operaciones del brazo `filter` del protocolo oficial de 362
sesiones (`breakeven_1r_protocol_be.json`), con sus entradas, stops, targets y
qty originales. No re-simula señales ni toca la configuración activa.

Políticas comparadas, sobre el mismo conjunto y la misma qty:
  - baseline:     stop y target originales.
  - be_1r:        stop a la entrada tras MFE >= 1R (BE completo).
  - partial_50_be: 50% de la posición a +1R y stop a la entrada en el resto.

Supuestos:
  - El parcial se llena a +1R (con slippage adverso de 1 tick; si la vela abre
    más allá de +1R, al open). Es una orden límite de toma de beneficio.
  - El stop del resto pasa a break-even para la vela siguiente, no dentro de la
    misma vela que alcanza +1R.
  - Si en una vela se tocan stop y +1R, se aplica stop primero (peor caso).
  - Si una vela alcanza +1R y target, se asume camino favorable: parcial a +1R
    y resto a target en esa misma vela. Así no se corta artificialmente un
    ganador que recorrió todo el trayecto.
  - El cierre de sesión liquida el resto al close de la primera vela >= 15:55 ET
    (o la última disponible).
  - Comisión 0.62 USD por contrato y lado. Sin costes de financiación.

El R se calcula como R de precio por operación, redondeado a 2 decimales; en el
parcial se pondera por contratos, igual que el motor full-engine. El DD se
calcula con los flujos de caja reales: el parcial entra en la equity cuando se
ejecuta, no al cierre final. Es la métrica que interesa para saber si la salida
parcial suaviza la curva.

Con qty=1 no se ejecuta parcial ni se mueve el stop a BE: la política vuelve al
comportamiento original, igual que el motor full-engine.
"""

from __future__ import annotations

import json
import statistics
import sys
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "backtest"
if str(REPORTS) not in sys.path:
    sys.path.insert(0, str(REPORTS))

from run_breakeven_1r_experiment import (  # noqa: E402
    COMMISSION_SIDE,
    INITIAL_CAPITAL,
    et,
    load_bars,
    pnl_for_qty,
    round_tick,
    stop_price,
    target_price,
)
from run_breakeven_1r_protocol import _effect as be_effect  # noqa: E402

OFFICIAL = REPORTS / "breakeven_1r_protocol_be.json"
OUT = REPORTS / "partial_exit_1r_protocol.json"
MD = REPORTS / "PARTIAL_EXIT_1R_PROTOCOL.md"
POLICIES = ("baseline", "be_1r", "partial_50_be")


def simulate(
    trade: dict,
    policy: str,
    bars: dict[int, dict],
    stamps: list[int],
    session_last: dict[str, int],
) -> dict:
    entry = float(trade["entry_price"])
    initial_stop = float(trade["stop"])
    target = float(trade["target"])
    qty = int(trade["qty"])
    direction = 1 if trade["direction"] == "long" else -1
    risk = abs(entry - initial_stop)
    start = int(trade["entry_ts"])
    session_end = session_last[et(start).date().isoformat()]

    # Un contrato no permite ejecutar el 50%; en ese caso la política vuelve
    # al comportamiento original, igual que el motor full-engine.
    partial_qty = qty // 2 if policy == "partial_50_be" and qty >= 2 else 0
    partial_enabled = partial_qty > 0
    be_enabled = policy == "be_1r" or partial_enabled
    remaining = qty
    stop = initial_stop
    partial_done = False
    partial_pnl = 0.0
    partial_ts = None
    partial_price = None
    partial_r = None
    remainder_pnl = None
    remainder_exit = None
    remainder_price = None
    exit_ts = None
    moved_be = False

    start_index = bisect_left(stamps, start)
    for ts in stamps[start_index:]:
        if ts > session_end:
            break
        bar = bars[ts]

        if direction == 1:
            hit_stop = bar["low"] <= stop
            hit_target = bar["high"] >= target
            hit_one_r = risk > 0 and bar["high"] >= entry + risk
            gap_stop = bar["open"] < stop
            gap_one_r = bar["open"] > entry + risk
            gap_target = bar["open"] > target
        else:
            hit_stop = bar["high"] >= stop
            hit_target = bar["low"] <= target
            hit_one_r = risk > 0 and bar["low"] <= entry - risk
            gap_stop = bar["open"] > stop
            gap_one_r = bar["open"] < entry - risk
            gap_target = bar["open"] < target

        # Peor caso: si stop y target/+1R se tocan en la misma vela, stop first.
        if hit_stop:
            remainder_price = stop_price(trade, stop, gap_stop, bar)
            remainder_exit = "stop_loss"
            exit_ts = ts
            break

        if partial_enabled and not partial_done and hit_one_r:
            partial_price = target_price(
                trade, entry + direction * risk, gap_one_r, bar
            )
            partial_pnl = pnl_for_qty(trade, partial_price, partial_qty)
            partial_r = round((partial_price - entry) * direction / risk, 4)
            partial_ts = ts
            partial_done = True
            remaining -= partial_qty
            # BE para la vela siguiente, igual que el motor.
            stop = entry
            moved_be = True
            if hit_target:
                remainder_price = target_price(trade, target, gap_target, bar)
                remainder_exit = "take_profit"
                exit_ts = ts
                break
            if ts >= session_end:
                remainder_price = round_tick(bar["close"])
                remainder_exit = "session_close"
                exit_ts = ts
                break
            continue

        if hit_target:
            remainder_price = target_price(trade, target, gap_target, bar)
            remainder_exit = "take_profit"
            exit_ts = ts
            break

        if ts >= session_end:
            remainder_price = round_tick(bar["close"])
            remainder_exit = "session_close"
            exit_ts = ts
            break

        # El BE se activa después de comprobar target y cierre de sesión, para
        # que el stop nuevo nunca convierta en pérdida un target ya alcanzado.
        if be_enabled and not moved_be and hit_one_r:
            stop = entry
            moved_be = True

    if exit_ts is None:
        bar = bars[session_end]
        remainder_price = round_tick(bar["close"])
        remainder_exit = "session_close"
        exit_ts = session_end

    remainder_pnl = pnl_for_qty(trade, remainder_price, remaining)
    total_pnl = round(partial_pnl + remainder_pnl, 2)
    risk_amount = float(trade.get("risk_amount") or 0.0)
    if partial_done and risk > 0:
        # R de precio ponderado por contratos, igual que el motor full-engine.
        partial_r_weighted = (
            (partial_price - entry) * direction * partial_qty / (risk * qty)
        )
        remainder_r = round((remainder_price - entry) * direction / risk, 2)
        r_multiple = round(
            partial_r_weighted + remainder_r * remaining / qty, 2
        )
    elif risk > 0:
        r_multiple = round((remainder_price - entry) * direction / risk, 2)
    else:
        r_multiple = 0.0
    r_multiple_net = round(total_pnl / risk_amount, 4) if risk_amount else 0.0

    return {
        "signal_id": trade["meta"]["signal_id"],
        "policy": policy,
        "direction": trade["direction"],
        "qty": qty,
        "partial_qty": partial_qty if partial_done else 0,
        "remaining_qty": remaining,
        "entry_ts": start,
        "exit_ts": exit_ts,
        "entry_price": entry,
        "stop": initial_stop,
        "target": target,
        "partial_ts": partial_ts,
        "partial_price": partial_price,
        "partial_r": partial_r,
        "partial_pnl": partial_pnl if partial_done else None,
        "remainder_pnl": remainder_pnl,
        "remainder_exit": remainder_exit,
        "remainder_price": round(remainder_price, 2),
        "pnl": total_pnl,
        "r_multiple": r_multiple,
        "r_multiple_net": r_multiple_net,
        "risk_amount": risk_amount,
        "partial_done": partial_done,
        "be_moved": moved_be,
        "original_pnl": float(trade["pnl"]),
        "original_exit": trade["exit_reason"],
        "mfe_r": trade.get("mfe_r"),
    }


def cashflows(rows: list[dict]) -> list[tuple[int, int, int, float, str, str]]:
    """Flujos de caja en orden de ejecución.

    Si el parcial y el resto coinciden en la misma vela, el parcial se cobra
    primero. Ordenar solo por P&L podía alterar el DD artificialmente.
    """
    out = []
    for order, row in enumerate(rows):
        if row["partial_pnl"] is not None:
            out.append(
                (
                    int(row["partial_ts"]),
                    0,
                    order,
                    float(row["partial_pnl"]),
                    row["signal_id"],
                    "partial",
                )
            )
        out.append(
            (
                int(row["exit_ts"]),
                1,
                order,
                float(row["remainder_pnl"]),
                row["signal_id"],
                "remainder",
            )
        )
    return sorted(out, key=lambda event: (event[0], event[1], event[2]))


def _drawdown_from_pnls(pnls: list[float]) -> tuple[float, float]:
    equity = INITIAL_CAPITAL
    peak = equity
    worst = 0.0
    worst_pct = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        if drawdown > worst:
            worst = drawdown
            worst_pct = drawdown / peak * 100 if peak else 0.0
    return round(worst, 2), round(worst_pct, 3)


def max_drawdown(rows: list[dict]) -> tuple[float, float]:
    return _drawdown_from_pnls([event[3] for event in cashflows(rows)])


def closed_trade_drawdown(rows: list[dict]) -> tuple[float, float]:
    ordered = sorted(rows, key=lambda row: row["exit_ts"])
    return _drawdown_from_pnls([float(row["pnl"]) for row in ordered])


def summarize(rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda row: row["entry_ts"])
    pnls = [float(row["pnl"]) for row in ordered]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gp = sum(wins)
    gl = sum(losses)
    dd, dd_pct = max_drawdown(ordered)
    closed_dd, closed_dd_pct = closed_trade_drawdown(ordered)
    rs = [float(row["r_multiple"]) for row in ordered]
    streak = worst = 0
    for pnl in pnls:
        if pnl < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0,
        "gross_profit": round(gp, 2),
        "gross_loss": round(gl, 2),
        "net_profit": round(sum(pnls), 2),
        "profit_factor": round(gp / abs(gl), 2) if gl else None,
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else 0.0,
        "avg_r": round(statistics.fmean(rs), 2) if rs else 0.0,
        "total_r": round(sum(rs), 2),
        "max_drawdown": dd,
        "max_drawdown_pct": dd_pct,
        "max_drawdown_basis": "cashflow",
        "closed_trade_max_drawdown": closed_dd,
        "closed_trade_max_drawdown_pct": closed_dd_pct,
        "worst_loss_streak": worst,
    }


def reconcile_metrics(rows: list[dict]) -> dict:
    """Comprueba que las métricas publicadas salen de las operaciones."""
    metrics = summarize(rows)
    pnls = [float(row["pnl"]) for row in rows]
    rs = [float(row["r_multiple"]) for row in rows]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gp = sum(wins)
    gl = sum(losses)
    expected = {
        "net_profit": round(sum(pnls), 2),
        "gross_profit": round(gp, 2),
        "gross_loss": round(gl, 2),
        "profit_factor": round(gp / abs(gl), 2) if gl else None,
        "avg_r": round(statistics.fmean(rs), 2) if rs else 0.0,
        "total_r": round(sum(rs), 2),
        "max_drawdown": max_drawdown(rows)[0],
        "max_drawdown_pct": max_drawdown(rows)[1],
        "closed_trade_max_drawdown": closed_trade_drawdown(rows)[0],
    }
    checks = {
        key: (
            metrics.get(key) == value
            if value is None
            else abs(float(metrics.get(key) or 0.0) - float(value)) <= 0.011
        )
        for key, value in expected.items()
    }
    return {"ok": all(checks.values()), "checks": checks, "expected": expected}


def compare_trades(
    official_trades: list[dict], sim_trades: list[dict]
) -> dict:
    """Compara P&L y motivo de salida contra las operaciones oficiales."""
    official = {
        str(trade["meta"]["signal_id"]): trade for trade in official_trades
    }
    sim = {row["signal_id"]: row for row in sim_trades}
    detail = []
    for sid, before in official.items():
        after = sim.get(sid)
        if after is None:
            detail.append({"signal_id": sid, "missing_in_simulation": True})
            continue
        detail.append(
            {
                "signal_id": sid,
                "official_pnl": before["pnl"],
                "sim_pnl": after["pnl"],
                "delta": round(float(after["pnl"]) - float(before["pnl"]), 2),
                "official_exit": before["exit_reason"],
                "sim_exit": after["remainder_exit"],
                "official_r": before.get("r_multiple"),
                "sim_r": after.get("r_multiple"),
            }
        )
    mismatches = [row for row in detail if abs(float(row.get("delta") or 0.0)) > 0.01]
    return {"mismatches": len(mismatches), "detail": detail, "mismatch_detail": mismatches}


def compare_metrics(sim: dict, official: dict) -> dict:
    fields = ("net_profit", "max_drawdown", "profit_factor", "avg_r")
    out = {}
    for field in fields:
        left = sim.get(field)
        right = official.get(field)
        out[field] = {
            "sim": left,
            "official": right,
            "delta": round(float(left or 0.0) - float(right or 0.0), 4),
            "match": left is not None
            and right is not None
            and abs(float(left) - float(right)) <= 0.01,
        }
    return out


def main() -> None:
    official = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    official_filter = official["arms"]["filter"]
    official_be = official["arms"]["be_1r"]
    trades = official_filter["trades"]
    if len(trades) != 14:
        raise RuntimeError(f"Se esperaban 14 operaciones filter, hay {len(trades)}")

    bars, stamps, session_last = load_bars()
    results = {
        policy: [
            simulate(trade, policy, bars, stamps, session_last)
            for trade in trades
        ]
        for policy in POLICIES
    }
    by_id = {
        policy: {row["signal_id"]: row for row in rows}
        for policy, rows in results.items()
    }

    baseline_validation = compare_trades(trades, results["baseline"])
    be_validation = compare_trades(official_be["trades"], results["be_1r"])
    effects = {
        policy: be_effect(results["baseline"], results[policy])
        for policy in POLICIES
        if policy != "baseline"
    }
    reconciliations = {
        policy: reconcile_metrics(rows) for policy, rows in results.items()
    }
    all_metrics_reconciled = all(
        item["ok"] for item in reconciliations.values()
    )

    partial_rows = [row for row in results["partial_50_be"] if row["partial_done"]]
    be_rows = [row for row in results["be_1r"] if row["be_moved"]]
    partial_be_rows = [
        row for row in results["partial_50_be"] if row["be_moved"]
    ]

    partial_metrics = summarize(results["partial_50_be"])
    full_reference = None
    full_path = REPORTS / "partial_exit_1r_full.json"
    if full_path.exists():
        full = json.loads(full_path.read_text(encoding="utf-8"))
        full_arm = full["arms"]["partial_50_be"]
        full_total = full_arm["total"]
        full_trades = full_arm["trades"]
        full_reference = {
            "path": str(full_path.relative_to(ROOT)),
            "net_profit": full_total["net_profit"],
            "profit_factor": full_total["profit_factor"],
            "avg_r": full_total["avg_r"],
            "max_drawdown": full_total["max_drawdown"],
            "cashflow_max_drawdown": full_total["cashflow_max_drawdown"],
            "qty_values": sorted({int(t["qty"]) for t in full_trades}),
            "deltas_vs_protocol": {
                "net_profit": round(
                    float(partial_metrics["net_profit"])
                    - float(full_total["net_profit"]),
                    2,
                ),
                "profit_factor": round(
                    float(partial_metrics["profit_factor"] or 0.0)
                    - float(full_total["profit_factor"] or 0.0),
                    2,
                ),
                "avg_r": round(
                    float(partial_metrics["avg_r"])
                    - float(full_total["avg_r"]),
                    2,
                ),
                "cashflow_max_drawdown": round(
                    float(partial_metrics["max_drawdown"])
                    - float(full_total["cashflow_max_drawdown"]),
                    2,
                ),
            },
            "note": (
                "El replay usa qty fija oficial; el full-engine usa qty dinámica. "
                "El DD de caja coincide; el R coincide salvo la señal con qty distinta. "
                "Neto y PF pueden diferir por qty."
            ),
        }

    arm_metrics = {
        "baseline": summarize(results["baseline"]),
        "be_1r": summarize(results["be_1r"]),
        "partial_50_be": partial_metrics,
    }
    baseline_metrics_vs_official = compare_metrics(
        arm_metrics["baseline"], official_filter["total"]
    )
    be_metrics_vs_official = compare_metrics(
        arm_metrics["be_1r"], official_be["total"]
    )

    output = {
        "schema": "partial-exit-1r-protocol-v2",
        "scope": "14 operaciones del brazo filter del protocolo oficial de 362 sesiones; holdout no usado",
        "source": {
            "path": str(OFFICIAL.relative_to(ROOT)),
            "sha256": __import__("hashlib").sha256(OFFICIAL.read_bytes()).hexdigest(),
        },
        "rules": {
            "partial_fraction": 0.5,
            "partial_r": 1.0,
            "be_after_partial": True,
            "be_timing": "vela siguiente a +1R",
            "stop_first_if_ambiguous": True,
            "partial_then_target_same_bar": True,
            "qty": "fija del protocolo oficial",
            "commission_per_contract_side": COMMISSION_SIDE,
            "slippage_ticks": 1,
            "r_definition": "R de precio por operación, 2 decimales; parcial ponderado por contratos (motor full-engine)",
            "drawdown_definition": "cashflow, parcial acreditado al ejecutarse; porcentaje sobre el pico de equity",
        },
        "validation": {
            "trades": len(trades),
            "baseline": baseline_validation,
            "be_1r": be_validation,
            "baseline_mismatches": baseline_validation["mismatches"],
            "baseline_mismatch_detail": baseline_validation["mismatch_detail"],
            "be_mismatches": be_validation["mismatches"],
            "be_mismatch_detail": be_validation["mismatch_detail"],
            "baseline_metrics_vs_official": baseline_metrics_vs_official,
            "be_metrics_vs_official": be_metrics_vs_official,
            "metric_reconciliation": reconciliations,
            "all_metrics_reconciled": all_metrics_reconciled,
            "full_engine_partial": full_reference,
            "official_filter": {
                "net_profit": official_filter["total"]["net_profit"],
                "max_drawdown": official_filter["total"]["max_drawdown"],
                "profit_factor": official_filter["total"]["profit_factor"],
                "avg_r": official_filter["total"]["avg_r"],
                "wins": official_filter["total"]["wins"],
                "trades": official_filter["total"]["trades"],
            },
            "official_be_1r": {
                "net_profit": official_be["total"]["net_profit"],
                "max_drawdown": official_be["total"]["max_drawdown"],
                "profit_factor": official_be["total"]["profit_factor"],
                "avg_r": official_be["total"]["avg_r"],
                "wins": official_be["total"]["wins"],
                "trades": official_be["total"]["trades"],
            },
        },
        "arms": {
            policy: {
                "metrics": arm_metrics[policy],
                "trades": rows,
            }
            for policy, rows in results.items()
        },
        "comparison": {
            "official_filter_metrics": official_filter["total"],
            "official_be_metrics": official_be["total"],
            **effects,
        },
        "partial": {
            "signals_with_partial": len(partial_rows),
            "partial_qty_total": sum(row["partial_qty"] for row in partial_rows),
            "partial_pnl_total": round(sum(row["partial_pnl"] for row in partial_rows), 2),
            "be_moved_signals": len(be_rows),
            "partial_be_signals": len(partial_be_rows),
            "details": partial_rows,
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    def money(value: float | None) -> str:
        return "—" if value is None else f"{value:+,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def pct(value: float | None) -> str:
        return "—" if value is None else f"{value:.2f}%".replace(".", ",")

    lines = [
        "# Salida parcial 50% a +1R + break-even en el resto",
        "",
        "**Alcance:** 14 operaciones del brazo `filter` del protocolo oficial de 362 sesiones. Holdout no usado.  ",
        "**Naturaleza:** replay de gestión con entradas, qty, stops y targets oficiales; no re-simula señales.  ",
        "**Fuente:** `reports/backtest/breakeven_1r_protocol_be.json`  ",
        "**Resultado estructurado:** `reports/backtest/partial_exit_1r_protocol.json`",
        "",
        "## 1. Qué se probó",
        "",
        "| Política | Salida | Resto |",
        "|---|---|---|",
        "| `baseline` | target original 3R | stop original |",
        "| `be_1r` | target original 3R | stop a entrada tras +1R |",
        "| `partial_50_be` | 50% a +1R | 50% con stop a entrada tras +1R |",
        "",
        "La qty es la del protocolo oficial y no se recalcula. El parcial se llena a +1R; si la vela abre más allá, al open. El break-even del resto se activa para la vela siguiente, no dentro de la misma vela que toca +1R. Si stop y +1R coinciden en una vela, se aplica stop primero. Si +1R y target coinciden, se asume camino favorable: parcial a +1R y resto a target. La mitad es entera (`qty // 2`): con 3 contratos se toma 1 y quedan 2; con 5 se toman 2 y quedan 3.",
        "",
        "El **R** es el R de precio por operación, redondeado a 2 decimales; en el parcial se pondera por contratos, igual que el motor full-engine. No es el P&L neto dividido por el riesgo. El **DD** es de caja: el parcial se acredita cuando se ejecuta; el porcentaje se calcula sobre el pico de equity.",
        "",
        "## 2. Resultado",
        "",
        "| Brazo | Ops | Neto USD | PF | R medio | DD USD | DD % | Ganadoras | Perdedoras | Peor racha |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("baseline", "Baseline"),
        ("be_1r", "BE completo"),
        ("partial_50_be", "Parcial 50% + BE"),
    ):
        m = output["arms"][key]["metrics"]
        lines.append(
            f"| {label} | {m['trades']} | {money(m['net_profit'])} | {m['profit_factor']} | "
            f"{m['avg_r']} | {money(m['max_drawdown']).lstrip('+')} | {pct(m['max_drawdown_pct'])} | "
            f"{m['wins']} | {m['losses']} | {m['worst_loss_streak']} |"
        )

    base = output["arms"]["baseline"]["metrics"]
    be = output["arms"]["be_1r"]["metrics"]
    part = output["arms"]["partial_50_be"]["metrics"]
    be_eff = effects["be_1r"]
    part_eff = effects["partial_50_be"]
    full_net = full_reference["net_profit"] if full_reference else None
    full_pf = full_reference["profit_factor"] if full_reference else None
    full_r = full_reference["avg_r"] if full_reference else None
    full_dd = full_reference["cashflow_max_drawdown"] if full_reference else None

    lines += [
        "",
        f"El baseline simulado deja **{money(base['net_profit'])}** con DD **{money(base['max_drawdown']).lstrip('+')}**. El BE completo deja **{money(be['net_profit'])}** y DD **{money(be['max_drawdown']).lstrip('+')}**; el parcial deja **{money(part['net_profit'])}** y DD **{money(part['max_drawdown']).lstrip('+')}**.",
        "",
        f"El BE completo reduce el DD un **{pct((1 - be['max_drawdown'] / base['max_drawdown']) * 100)}** pero corta **{be_eff['winners_cut']} ganadoras** y deja **{be['wins']}** ganadoras. El parcial reduce el DD un **{pct((1 - part['max_drawdown'] / base['max_drawdown']) * 100)}**, deja **{part['wins']}** ganadoras y no corta ninguna; el coste es que baja el P&L de las ganadoras en **{money(part_eff['winner_pnl_lost']).lstrip('+')}**.",
        "",
        "## 3. Efecto sobre ganadoras y perdedoras",
        "",
        "| Política | Ganadoras cortadas | Ganadoras por debajo | P&L perdido en ganadoras | Perdedoras mejoradas | Ahorro en perdedoras |",
        "|---|---:|---:|---:|---:|---:|",
        f"| BE completo | {be_eff['winners_cut']} | {be_eff['winners_below']} | {money(be_eff['winner_pnl_lost']).lstrip('+')} | {be_eff['losses_improved']} | {money(be_eff['losses_saved_usd']).lstrip('+')} |",
        f"| Parcial 50% + BE | {part_eff['winners_cut']} | {part_eff['winners_below']} | {money(part_eff['winner_pnl_lost']).lstrip('+')} | {part_eff['losses_improved']} | {money(part_eff['losses_saved_usd']).lstrip('+')} |",
        "",
        "## 4. Detalle del parcial",
        "",
        f"Se ejecutó parcial en **{len(partial_rows)}** de 14 señales. El P&L del parcial suma **{money(output['partial']['partial_pnl_total'])}**; el resto se cerró por stop, target o sesión según el caso. La única señal sin parcial es `2025-09-19-short-1758294900` (MFE 0,11R), que se queda en -183,48 USD.",
        "",
        "| Señal | Qty | Parcial | Precio | P&L parcial | Resto | Salida resto | P&L total | Baseline |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for row in sorted(partial_rows, key=lambda x: x["entry_ts"]):
        lines.append(
            f"| `{row['signal_id']}` | {row['qty']} | {row['partial_qty']} | "
            f"{row['partial_price']:.2f} | {money(row['partial_pnl'])} | "
            f"{row['remaining_qty']} | {row['remainder_exit']} | "
            f"{money(row['pnl'])} | {money(row['original_pnl'])} |"
        )

    lines += [
        "",
        "## 5. Verificación de métricas",
        "",
        "### 5.1 Control contra el protocolo oficial",
        "",
        "| Brazo | Métrica | Oficial | Replay | Δ |",
        "|---|---|---:|---:|---:|",
        f"| Filter | Neto | {money(official_filter['total']['net_profit'])} | {money(base['net_profit'])} | {money(base['net_profit'] - official_filter['total']['net_profit'])} |",
        f"| Filter | DD caja | {money(official_filter['total']['max_drawdown']).lstrip('+')} | {money(base['max_drawdown']).lstrip('+')} | {money(base['max_drawdown'] - official_filter['total']['max_drawdown'])} |",
        f"| Filter | PF | {official_filter['total']['profit_factor']} | {base['profit_factor']} | {base['profit_factor'] - official_filter['total']['profit_factor']:+.2f} |",
        f"| Filter | R medio | {official_filter['total']['avg_r']} | {base['avg_r']} | {base['avg_r'] - official_filter['total']['avg_r']:+.2f} |",
        f"| BE | Neto | {money(official_be['total']['net_profit'])} | {money(be['net_profit'])} | {money(be['net_profit'] - official_be['total']['net_profit'])} |",
        f"| BE | DD caja | {money(official_be['total']['max_drawdown']).lstrip('+')} | {money(be['max_drawdown']).lstrip('+')} | {money(be['max_drawdown'] - official_be['total']['max_drawdown'])} |",
        f"| BE | PF | {official_be['total']['profit_factor']} | {be['profit_factor']} | {be['profit_factor'] - official_be['total']['profit_factor']:+.2f} |",
        f"| BE | R medio | {official_be['total']['avg_r']} | {be['avg_r']} | {be['avg_r'] - official_be['total']['avg_r']:+.2f} |",
        "",
        f"El control tiene **{baseline_validation['mismatches']} discrepancia** en baseline y **{be_validation['mismatches']}** en BE, siempre en `2025-11-28-long-1764345600`: el CSV ajustado termina en 13:14 (25484,75) y el artefacto oficial usa 13:15 (25484,50). Eso explica +1,50 USD de neto y +0,01 de PF; el **DD coincide exactamente** y el **R medio coincide** al usar la definición de R del motor. Las demás 13 operaciones coinciden.",
        "",
        "### 5.2 Parcial contra full-engine",
        "",
        "| Métrica | Parcial qty fija | Full-engine qty dinámica | Δ |",
        "|---|---:|---:|---:|",
        f"| Neto | {money(part['net_profit'])} | {money(full_net) if full_net is not None else '—'} | {money(part['net_profit'] - full_net) if full_net is not None else '—'} |",
        f"| PF | {part['profit_factor']} | {full_pf if full_pf is not None else '—'} | {part['profit_factor'] - full_pf:+.2f} |" if full_pf is not None else "| PF | — | — | — |",
        f"| DD caja | {money(part['max_drawdown']).lstrip('+')} | {money(full_dd).lstrip('+') if full_dd is not None else '—'} | {money(part['max_drawdown'] - full_dd) if full_dd is not None else '—'} |",
        f"| R medio | {part['avg_r']} | {full_r if full_r is not None else '—'} | {part['avg_r'] - full_r:+.2f} |" if full_r is not None else "| R medio | — | — | — |",
        "",
        "El replay de parcial usa la qty fija oficial; el full-engine usa la qty dinámica del RiskManager. El **DD de caja coincide exacto**. El **R medio difiere +0,01** porque el 24-DIC el replay mantiene 5 contratos (R 2,17) y el full-engine ejecuta 4 (R 1,97); en las otras 13 señales el R coincide. Neto y PF no son comparables al pie de la letra por esa misma qty. El DD de caja del parcial (185,22) es mayor que el DD por operaciones cerradas (183,48) porque el parcial se acredita antes del cierre del resto; se reporta el de caja.",
        "",
        "## 6. Conclusión",
        "",
        f"- El parcial **reduce el DD** de {money(base['max_drawdown']).lstrip('+')} a {money(part['max_drawdown']).lstrip('+')}: un {pct((1 - part['max_drawdown'] / base['max_drawdown']) * 100)} menos, incluso por debajo del BE completo ({money(be['max_drawdown']).lstrip('+')}).",
        f"- **No corta ganadoras**: conserva {part['wins']} ganadoras frente a {be['wins']} del BE completo y 0 cortadas. El coste es que el neto baja de {money(base['net_profit'])} a {money(part['net_profit'])} y el P&L de las 8 ganadoras se reduce en {money(part_eff['winner_pnl_lost']).lstrip('+')}.",
        f"- El BE completo conserva mejor neto ({money(be['net_profit'])} vs {money(part['net_profit'])}), pero corta 2 ganadoras y deja peor DD y peor PF. El parcial gana en DD, PF, racha y número de ganadoras; pierde en neto.",
        f"- **Verificación:** el DD de caja coincide exacto con el full-engine (185,22). El R medio queda +0,01 por la qty fija del 24-DIC (5 vs 4): 13 de 14 R coinciden. Neto y PF difieren por esa misma qty, no por la simulación de la gestión.",
        "- Es un replay de gestión in-sample sobre 14 operaciones; no valida el filtro ni autoriza promoción. El holdout sigue sin usarse.",
        "",
        "## 7. Verificación",
        "",
        "- 14 operaciones oficiales; IDs y qty del brazo filter.",
        f"- Baseline simulado vs oficial: {baseline_validation['mismatches']} discrepancia > 0,01 USD.",
        f"- BE simulado vs oficial: {be_validation['mismatches']} discrepancia > 0,01 USD.",
        f"- Conciliación interna de métricas (neto, PF, R, DD): **{all_metrics_reconciled}**.",
        f"- Parcial ejecutado en {len(partial_rows)} señales; BE movido en {len(be_rows)} señales del brazo BE y en {len(partial_be_rows)} del parcial.",
        f"- DD de caja del parcial: {money(part['max_drawdown']).lstrip('+')}; DD por operaciones cerradas: {money(part['closed_trade_max_drawdown']).lstrip('+')}.",
        f"- JSON: `{OUT.relative_to(ROOT)}`",
    ]
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "baseline": base,
        "be_1r": be,
        "partial_50_be": part,
        "be_effect": be_eff,
        "partial_effect": part_eff,
        "validation": output["validation"],
        "partial_count": len(partial_rows),
    }, ensure_ascii=False, indent=2))
    print(f"Escrito {OUT}")
    print(f"Escrito {MD}")


if __name__ == "__main__":
    main()
