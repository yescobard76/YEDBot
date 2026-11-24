"""Compara stop floor con target original contra target recalculado a 3R.

Lee los tres JSON ya calculados sobre W1-W6 y escribe una comparación
estructurada y un informe legible. No ejecuta la estrategia, no lee barras y
no toca el holdout.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports/backtest"
BASE_PATH = REPORTS / "min_stop_or_ratio_protocol.json"
RECALC_PATH = REPORTS / "stop_floor_protocol.json"
ORIGINAL_PATH = REPORTS / "stop_floor_protocol_original_target.json"
JSON_PATH = REPORTS / "stop_floor_target_comparison.json"
MD_PATH = REPORTS / "STOP_FLOOR_TARGET_COMPARISON.md"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _by_id(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(trade["signal_id"]): trade for trade in trades}


def _net(trades: dict[str, dict[str, Any]], ids: list[str]) -> float:
    return round(sum(float(trades[sid]["pnl"]) for sid in ids), 2)


def _sum_r(trades: dict[str, dict[str, Any]], ids: list[str]) -> float:
    return round(sum(float(trades[sid]["r_multiple"]) for sid in ids), 4)


def _mean_r(trades: dict[str, dict[str, Any]], ids: list[str]) -> float:
    return round(_sum_r(trades, ids) / len(ids), 4)


def _r_pf(trades: dict[str, dict[str, Any]], ids: list[str]) -> dict[str, float | None]:
    gross_profit = sum(
        float(trades[sid]["r_multiple"])
        for sid in ids
        if float(trades[sid]["r_multiple"]) > 0
    )
    gross_loss = sum(
        float(trades[sid]["r_multiple"])
        for sid in ids
        if float(trades[sid]["r_multiple"]) < 0
    )
    return {
        "gross_profit_r": round(gross_profit, 4),
        "gross_loss_r": round(gross_loss, 4),
        "r_profit_factor": (
            round(gross_profit / abs(gross_loss), 4) if gross_loss < 0 else None
        ),
    }


def _metrics(arm: dict[str, Any]) -> dict[str, Any]:
    total = arm["total"]
    ex_w4 = arm["ex_w4"]
    return {
        key: total.get(key)
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
        )
    } | {
        "ex_w4_net_profit": ex_w4.get("net_profit"),
        "ex_w4_profit_factor": ex_w4.get("profit_factor"),
        "ex_w4_max_drawdown": ex_w4.get("max_drawdown"),
    }


def _money(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(value: float) -> str:
    return f"{value:.2f}%".replace(".", ",")


def _num(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main() -> int:
    base = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    recalc = json.loads(RECALC_PATH.read_text(encoding="utf-8"))
    original = json.loads(ORIGINAL_PATH.read_text(encoding="utf-8"))

    b = _by_id(base["baseline"]["trades"])
    r = _by_id(recalc["stop_floor"]["trades"])
    o = _by_id(original["stop_floor"]["trades"])
    common = sorted(set(r) & set(o))
    low_common = sorted(sid for sid in common if b[sid]["stop_or_ratio"] < 0.25)
    high_common = sorted(sid for sid in common if b[sid]["stop_or_ratio"] >= 0.25)
    removed = sorted(set(b) - set(o))

    arms = {
        "baseline": _metrics(base["baseline"]),
        "reject": _metrics(base["filter"]),
        "floor_recalc": _metrics(recalc["stop_floor"]),
        "floor_original": _metrics(original["stop_floor"]),
    }
    cohorts = {
        "all_common_34": {
            "signals": len(common),
            "baseline_net": _net(b, common),
            "baseline_total_r": _sum_r(b, common),
            "baseline_mean_r": _mean_r(b, common),
            "floor_recalc_net": _net(r, common),
            "floor_recalc_total_r": _sum_r(r, common),
            "floor_recalc_mean_r": _mean_r(r, common),
            "floor_original_net": _net(o, common),
            "floor_original_total_r": _sum_r(o, common),
            "floor_original_mean_r": _mean_r(o, common),
        },
        "low_ratio_20_kept": {
            "signals": len(low_common),
            "baseline_net": _net(b, low_common),
            "baseline_total_r": _sum_r(b, low_common),
            "baseline_mean_r": _mean_r(b, low_common),
            "floor_recalc_net": _net(r, low_common),
            "floor_recalc_total_r": _sum_r(r, low_common),
            "floor_recalc_mean_r": _mean_r(r, low_common),
            "floor_original_net": _net(o, low_common),
            "floor_original_total_r": _sum_r(o, low_common),
            "floor_original_mean_r": _mean_r(o, low_common),
        },
        "high_ratio_14": {
            "signals": len(high_common),
            "baseline_net": _net(b, high_common),
            "baseline_total_r": _sum_r(b, high_common),
            "floor_recalc_net": _net(r, high_common),
            "floor_recalc_total_r": _sum_r(r, high_common),
            "floor_original_net": _net(o, high_common),
            "floor_original_total_r": _sum_r(o, high_common),
        },
        "removed_by_max_sl_4": {
            "signals": len(removed),
            "baseline_net": _net(b, removed),
            "signal_ids": removed,
        },
    }

    winners = []
    for sid in sorted(
        (sid for sid in b if b[sid]["stop_or_ratio"] < 0.25 and b[sid]["pnl"] > 0),
        key=lambda value: b[value]["pnl"],
        reverse=True,
    ):
        original_winner = next(
            item
            for item in original["comparison"]["low_ratio_winners"]
            if item["signal_id"] == sid
        )
        winners.append(
            {
                "signal_id": sid,
                "baseline_pnl": round(float(b[sid]["pnl"]), 2),
                "baseline_r": round(float(b[sid]["r_multiple"]), 2),
                "baseline_stop_ticks": b[sid]["stop_ticks"],
                "floor_stop_ticks": r[sid]["stop_ticks"],
                "original_pnl": round(float(o[sid]["pnl"]), 2),
                "original_r": round(float(o[sid]["r_multiple"]), 2),
                "original_exit": o[sid]["exit_reason"],
                "original_target_r": original_winner["floor_target_r_multiple"],
                "recalc_pnl": round(float(r[sid]["pnl"]), 2),
                "recalc_r": round(float(r[sid]["r_multiple"]), 2),
                "recalc_exit": r[sid]["exit_reason"],
                "recalc_profitable": r[sid]["pnl"] > 0,
                "original_profitable": o[sid]["pnl"] > 0,
            }
        )

    changes = []
    for sid in common:
        if (
            abs(float(r[sid]["pnl"]) - float(o[sid]["pnl"])) > 1e-6
            or r[sid]["exit_reason"] != o[sid]["exit_reason"]
        ):
            changes.append(
                {
                    "signal_id": sid,
                    "ratio": round(float(b[sid]["stop_or_ratio"]), 6),
                    "baseline_pnl": round(float(b[sid]["pnl"]), 2),
                    "floor_original_pnl": round(float(o[sid]["pnl"]), 2),
                    "floor_original_exit": o[sid]["exit_reason"],
                    "floor_recalc_pnl": round(float(r[sid]["pnl"]), 2),
                    "floor_recalc_exit": r[sid]["exit_reason"],
                    "recalc_minus_original": round(
                        float(r[sid]["pnl"]) - float(o[sid]["pnl"]), 2
                    ),
                }
            )

    decomp = {
        "baseline_total": arms["baseline"]["net_profit"],
        "removed_4_stop_cap_net": _net(b, removed),
        "baseline_common_34_net": _net(b, common),
        "floor_original_total": arms["floor_original"]["net_profit"],
        "floor_recalc_total": arms["floor_recalc"]["net_profit"],
        "reject_total": arms["reject"]["net_profit"],
        "floor_original_minus_baseline": round(
            arms["floor_original"]["net_profit"] - arms["baseline"]["net_profit"], 2
        ),
        "floor_recalc_minus_baseline": round(
            arms["floor_recalc"]["net_profit"] - arms["baseline"]["net_profit"], 2
        ),
        "recalc_minus_original": round(
            arms["floor_recalc"]["net_profit"] - arms["floor_original"]["net_profit"], 2
        ),
        "recalc_minus_original_low_ratio_20": round(
            _net(r, low_common) - _net(o, low_common), 2
        ),
        "recalc_minus_original_high_ratio_path": round(
            _net(r, high_common) - _net(o, high_common), 2
        ),
        "low_ratio_20_original_minus_baseline": round(
            _net(o, low_common) - _net(b, low_common), 2
        ),
        "low_ratio_20_recalc_minus_baseline": round(
            _net(r, low_common) - _net(b, low_common), 2
        ),
        "reject_minus_original": round(
            arms["reject"]["net_profit"] - arms["floor_original"]["net_profit"], 2
        ),
    }

    r_metrics = {
        "all_common_34": {
            "baseline": {
                "total_r": _sum_r(b, common),
                "mean_r": _mean_r(b, common),
                **_r_pf(b, common),
            },
            "floor_original": {
                "total_r": _sum_r(o, common),
                "mean_r": _mean_r(o, common),
                **_r_pf(o, common),
            },
            "floor_recalc": {
                "total_r": _sum_r(r, common),
                "mean_r": _mean_r(r, common),
                **_r_pf(r, common),
            },
        },
        "low_ratio_20_kept": {
            "baseline": {
                "total_r": _sum_r(b, low_common),
                "mean_r": _mean_r(b, low_common),
                **_r_pf(b, low_common),
            },
            "floor_original": {
                "total_r": _sum_r(o, low_common),
                "mean_r": _mean_r(o, low_common),
                **_r_pf(o, low_common),
            },
            "floor_recalc": {
                "total_r": _sum_r(r, low_common),
                "mean_r": _mean_r(r, low_common),
                **_r_pf(r, low_common),
            },
        },
        "high_ratio_14": {
            "baseline": {
                "total_r": _sum_r(b, high_common),
                "mean_r": _mean_r(b, high_common),
                **_r_pf(b, high_common),
            },
            "floor_original": {
                "total_r": _sum_r(o, high_common),
                "mean_r": _mean_r(o, high_common),
                **_r_pf(o, high_common),
            },
            "floor_recalc": {
                "total_r": _sum_r(r, high_common),
                "mean_r": _mean_r(r, high_common),
                **_r_pf(r, high_common),
            },
        },
    }

    payload = {
        "schema": "stop-floor-target-comparison-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "W1-W6, 362 sesiones, desarrollo; holdout no usado",
        "sources": {
            "baseline_reject": str(BASE_PATH.relative_to(ROOT)),
            "baseline_reject_sha256": _sha(BASE_PATH),
            "floor_recalc": str(RECALC_PATH.relative_to(ROOT)),
            "floor_recalc_sha256": _sha(RECALC_PATH),
            "floor_original": str(ORIGINAL_PATH.relative_to(ROOT)),
            "floor_original_sha256": _sha(ORIGINAL_PATH),
        },
        "verification": {
            "sessions_total": original["verification"]["sessions_total"],
            "holdout_used": original["verification"]["holdout_used"],
            "baseline_matches_official": all(
                item["matches"]
                for item in original["comparison"]["baseline_matches_official"].values()
            ),
            "floor_signals": len(common),
            "low_ratio_signals": 24,
            "floor_accepted_low_ratio": 20,
            "floor_rejected_by_max_sl": 4,
            "floor_new_signals": original["comparison"]["floor_new_count"],
            "floor_removed_signals": original["comparison"]["floor_removed_count"],
        },
        "arms": arms,
        "cohorts": cohorts,
        "r_metrics": r_metrics,
        "low_ratio_winners": winners,
        "winner_summary": {
            "count": len(winners),
            "baseline_pnl": round(sum(item["baseline_pnl"] for item in winners), 2),
            "floor_original_pnl": round(
                sum(item["original_pnl"] for item in winners), 2
            ),
            "floor_recalc_pnl": round(sum(item["recalc_pnl"] for item in winners), 2),
            "floor_original_profitable": sum(
                1 for item in winners if item["original_profitable"]
            ),
            "floor_recalc_profitable": sum(
                1 for item in winners if item["recalc_profitable"]
            ),
        },
        "changed_trades": changes,
        "decomposition": decomp,
    }
    JSON_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        "# Comparación stop mínimo — target original vs target recalculado a 3R",
        "",
        "**Fecha:** 2026-11-22  ",
        "**Alcance:** W1–W6, 362 sesiones de desarrollo. Holdout no usado.  ",
        "**Naturaleza:** comparación descriptiva in-sample; no es una validación forward.  ",
        f"**Fuente nueva:** `{ORIGINAL_PATH.relative_to(ROOT)}`  ",
        f"**Comparación estructurada:** `{JSON_PATH.relative_to(ROOT)}`",
        "",
        "## 1. Qué se comparó",
        "",
        "La rama `stop_floor` amplía el stop a `0,25 × ORB` cuando el stop original es más estrecho, sin rechazar por ratio. Se compararon dos políticas de target:",
        "",
        "| Política | Stop | Target |",
        "|---|---|---|",
        "| `floor_recalc` | `0,25 × ORB` | `3R` del stop ampliado |",
        "| `floor_original` | `0,25 × ORB` | target original calculado con el stop original, sin recalcular |",
        "",
        "Las dos ramas usan el mismo conjunto de señales y el mismo tope `max_sl_ticks=200`. En ambas, 4 señales de bajo ratio son rechazadas por el tope, no por el ratio; quedan 20 señales de bajo ratio y 14 de alto ratio.",
        "",
        "## 2. Resultado agregado",
        "",
        "| Brazo | Ops | Neto USD | PF | Expectativa USD | R medio | DD USD | DD % | Peor racha | Neto ex-W4 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("baseline", "Baseline"),
        ("reject", "Rechazo ratio"),
        ("floor_recalc", "Floor + target 3R"),
        ("floor_original", "Floor + target original"),
    ):
        metrics = arms[key]
        lines.append(
            f"| {label} | {metrics['trades']} | {_money(metrics['net_profit'])} | "
            f"{_num(metrics['profit_factor'])} | {_money(metrics['expectancy'])} | "
            f"{_num(metrics['avg_r'])} | {_money(metrics['max_drawdown'])} | "
            f"{_pct(metrics['max_drawdown_pct'])} | {metrics['worst_loss_streak']} | "
            f"{_money(metrics['ex_w4_net_profit'])} |"
        )
    lines += [
        "",
        "El target original **mejora al baseline en USD** (+701,76) y reduce el drawdown (1.440,00 vs 1.967,82), pero **no supera al target recalculado en USD**: queda 361,76 por debajo. El rechazo por ratio sigue siendo muy superior (+3.026,88).",
        "",
        "## 2b. La misma comparación en R",
        "",
        "La diferencia en USD no es una medida limpia de selección: el tamaño de posición depende de la trayectoria de capital. En R, el target original es ligeramente superior al 3R, aunque ambos floor empeoran a baseline en las 34 operaciones retenidas.",
        "",
        "| Cohorte | Baseline R | Floor original R | Floor 3R R | Baseline R-PF | Floor original R-PF | Floor 3R R-PF |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cohort_key, cohort_label in (
        ("all_common_34", "34 comunes"),
        ("low_ratio_20_kept", "20 bajo ratio"),
        ("high_ratio_14", "14 alto ratio"),
    ):
        data = r_metrics[cohort_key]
        lines.append(
            f"| {cohort_label} | {_num(data['baseline']['total_r'])} | "
            f"{_num(data['floor_original']['total_r'])} | "
            f"{_num(data['floor_recalc']['total_r'])} | "
            f"{_num(data['baseline']['r_profit_factor'])} | "
            f"{_num(data['floor_original']['r_profit_factor'])} | "
            f"{_num(data['floor_recalc']['r_profit_factor'])} |"
        )
    lines += [
        "",
        "En las 34 operaciones comunes, el baseline suma 9,01R; el floor con target original, 5,88R; y el floor con target 3R, 5,79R. En las 20 de bajo ratio, el baseline suma -5,52R; el original, -8,65R; y el 3R, -8,74R. El target original no crea edge, pero tampoco lo empeora frente al 3R; la ventaja en USD del 3R es tamaño/trayectoria.",
        "",
        "## 3. Descomposición stop vs target",
        "",
        "| Componente | Neto USD | Lectura |",
        "|---|---:|---|",
        f"| Baseline completo | {_money(decomp['baseline_total'])} | 38 ops |",
        f"| 4 ops eliminadas por max_sl | {_money(decomp['removed_4_stop_cap_net'])} | Todas de bajo ratio; su exclusión explica la mejora del floor |",
        f"| Baseline sobre las 34 ops conservadas | {_money(decomp['baseline_common_34_net'])} | Mismo conjunto que el floor |",
        f"| Floor + target original | {_money(decomp['floor_original_total'])} | 34 ops; {_money(decomp['floor_original_minus_baseline'])} vs baseline |",
        f"| Floor + target 3R | {_money(decomp['floor_recalc_total'])} | 34 ops; {_money(decomp['floor_recalc_minus_baseline'])} vs baseline |",
        "",
        f"**Efecto stop con target original:** +{_money(decomp['floor_original_minus_baseline'])} = +{_money(abs(decomp['removed_4_stop_cap_net']))} por eliminar las 4 ops que superan el tope, menos {_money(abs(decomp['low_ratio_20_original_minus_baseline']))} por el peor resultado de las 20 ops de bajo ratio conservadas.",
        "",
        f"**Efecto target en USD (original → 3R):** +{_money(decomp['recalc_minus_original'])} = +{_money(decomp['recalc_minus_original_low_ratio_20'])} en las 20 ops de bajo ratio + {_money(decomp['recalc_minus_original_high_ratio_path'])} por un efecto de trayectoria/qty en una operación de alto ratio. **En R no hay esa mejora:** el target original suma 5,88R frente a 5,79R del 3R (+0,09R). La diferencia en USD es tamaño/trayectoria, no selección.",
        "",
        f"**Combinado:** +{_money(decomp['floor_recalc_minus_baseline'])} USD vs baseline; en R, el floor 3R suma 5,79R frente a 9,01R del baseline en las 34 comunes. El rechazo por ratio mejora al floor original en {_money(decomp['reject_minus_original'])} USD.",
        "",
        "La lectura incómoda: el floor **no mejora las 20 operaciones de bajo ratio que conserva**. En R, esas 20 pasan de -5,52R en baseline a -8,65R con target original y -8,74R con target 3R. En USD pierden 1.663,68 y 1.448,18 respectivamente, frente a 1.228,36 del baseline. La mejora agregada del floor viene de que 4 operaciones de bajo ratio, mucho peores, superan el tope de 200 ticks y quedan fuera.",
        "",
        "## 4. ¿Conserva los ganadores?",
        "",
        "Sí, conserva **como rentables** los 4 ganadores de bajo ratio del baseline, pero con menos P&L. El target recalculado a 3R solo conserva 2 de esos 4.",
        "",
        "| Señal | P&L baseline | Stop orig. → floor | Target original | Target 3R |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in winners:
        lines.append(
            f"| `{item['signal_id']}` | {_money(item['baseline_pnl'])} | "
            f"{_num(item['baseline_stop_ticks'], 1)} → {_num(item['floor_stop_ticks'], 1)} ticks | "
            f"{_money(item['original_pnl'])} ({item['original_exit']}, "
            f"{_num(item['original_target_r'])}R) | {_money(item['recalc_pnl'])} "
            f"({item['recalc_exit']}) |"
        )
    lines += [
        "",
        f"Los 4 ganadores suman **{_money(payload['winner_summary']['baseline_pnl'])}** en baseline, **{_money(payload['winner_summary']['floor_original_pnl'])}** con target original y **{_money(payload['winner_summary']['floor_recalc_pnl'])}** con target 3R. El target original conserva los 4, pero deja de capturar la extensión a 3R; el target 3R conserva solo 2, aunque compensa con otras operaciones.",
        "",
        "## 5. Operaciones que cambian entre las dos políticas",
        "",
        "| Señal | Ratio | Baseline | Floor original | Floor 3R | 3R − original |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in changes:
        lines.append(
            f"| `{item['signal_id']}` | {_num(item['ratio'], 3)} | "
            f"{_money(item['baseline_pnl'])} | {_money(item['floor_original_pnl'])} "
            f"({item['floor_original_exit']}) | {_money(item['floor_recalc_pnl'])} "
            f"({item['floor_recalc_exit']}) | {_money(item['recalc_minus_original'])} |"
        )
    lines += [
        "",
        "La operación `2025-02-14` es de alto ratio y no recibe floor; su diferencia es un efecto de qty/trayectoria de capital, no del target. El efecto puro de target en el cohorte de bajo ratio es +215,50 USD; el resto (+146,26) es trayectoria.",
        "",
        "## 6. Conclusión",
        "",
        "- El target original **sí conserva a los 4 ganadores** de bajo ratio, pero su P&L agregado cae de 1.439,18 a 864,86 USD.",
        "- El target recalculado a 3R **pierde 2 de esos 4 ganadores**, pero gana más en `2025-03-21` y convierte dos perdedores en ganadores; por eso su neto en USD es 361,76 mayor. **En R, en cambio, el original es ligeramente superior (5,88R vs 5,79R): la ventaja en USD del 3R es tamaño/trayectoria, no edge.**",
        "- El floor, con cualquiera de las dos políticas, **sigue sin arreglar el cohorte de bajo ratio**: las 20 operaciones conservadas pasan de -5,52R en baseline a -8,65R/-8,74R, y pierden entre 1.448 y 1.664 USD. Su mejora sobre baseline depende de eliminar 4 operaciones por el tope de 200 ticks.",
        "- Por tanto, separar stop y target no rescata la idea: el target original preserva los ganadores y no empeora el R, pero no mejora el agregado en R; el target 3R mejora el USD por tamaño/trayectoria, a costa de perder ganadores. El rechazo por ratio sigue siendo la alternativa claramente superior en W1–W6.",
        "- Este resultado es **in-sample** y no valida el filtro ni el floor. No se abrió el holdout.",
    ]
    MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Escrito {JSON_PATH.relative_to(ROOT)}")
    print(f"Escrito {MD_PATH.relative_to(ROOT)}")
    print(json.dumps({"arms": arms, "winner_summary": payload["winner_summary"], "decomposition": decomp}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
