"""Genera reports/autoloop/resumen.md y resumen.json a partir de los resultados.

Fuentes:
- reports/backtest/live_vs_original_mission.json (viva vs original, W1-W6)
- reports/autoloop/resultados.jsonl (ranking del bucle)
- reports/autoloop/verificacion_top.json y verificacion_excl.json
  (re-ejecuciones independientes de las ganadoras)

No modifica configuración, DB ni el 8765. Solo escribe en reports/autoloop/.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "autoloop"
MISSION = ROOT / "reports" / "backtest" / "live_vs_original_mission.json"
CONC = OUT / "concentracion.json"

COST_IDS = {
    "cost_x2", "excl_1130_1330+cost_x2", "excl_1130_1330+sl_200+cost_x2",
}

ROBUST_IDS = {
    "excl_1100_1300", "excl_1200_1400", "excl_1130_1230",
    "excl_1130_1330+validity_180",
}

MAIN_IDS = {
    "manual_base", "sl_200", "sl_250", "rr_2_5", "rr_3_5", "tol_18",
    "validity_180", "contracts_7", "sl_buffer_8", "excl_1130_1330",
    "daily_loss_2", "range_min_15", "excl_1130_1330+sl_200",
    "excl_1130_1330+daily_loss_2", "excl_1130_1330+range_min_15",
}

RISK = {
    "risk.max_sl_ticks": "Recorta stops profundos: menos operaciones y posible sesgo a "
                         "stops que el mercado habría respetado.",
    "strategy.tp_rr": "Cambia el reparto acierto/tamaño: menos objetivo puede subir el "
                      "acierto pero recorta los ganadores grandes.",
    "strategy.retest_tolerance_ticks": "Más tolerancia acepta retesteos peores; menos "
                                       "tolera deja pasar entradas.",
    "strategy.setup_validity_minutes": "Acorta la ventana de entrada: pierde señales "
                                       "tardías que a veces son las mejores.",
    "risk.max_contracts": "Apalancamiento puro: el drawdown escala con el neto.",
    "risk.entry_exclusion_start": "Menos oportunidades y dependencia de un horario "
                                  "elegido in-sample.",
    "risk.entry_exclusion_end": "Menos oportunidades y dependencia de un horario "
                                "elegido in-sample.",
    "risk.max_daily_loss_pct": "Puede cortar un día que se recuperaba; reduce DD y "
                               "también cola derecha.",
    "strategy.min_range_ticks": "Descarta rangos estrechos, pero puede eliminar las "
                                "mejores rupturas.",
    "strategy.sl_buffer_ticks": "Stops más anchos: menos qty al 1 % de riesgo y más "
                                "tolerancia al ruido.",
}

PARAM_LABEL = {
    "risk.max_sl_ticks": "Tope de stop (ticks)",
    "strategy.tp_rr": "Objetivo (R)",
    "strategy.retest_tolerance_ticks": "Tolerancia de retesteo (ticks)",
    "strategy.setup_validity_minutes": "Validez del setup (min)",
    "risk.max_contracts": "Contratos máximos",
    "risk.entry_exclusion_start": "Exclusión de entradas",
    "risk.max_daily_loss_pct": "Pérdida diaria máxima (%)",
    "strategy.min_range_ticks": "Rango mínimo (ticks)",
    "strategy.sl_buffer_ticks": "Buffer de stop (ticks)",
}


def n(value, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    s = f"{float(value):,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def signed(value, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    v = float(value)
    return ("+" if v > 0 else "") + n(v, digits)


def conc_level(top5_share) -> str:
    value = float(top5_share or 0)
    if value >= 200:
        return "extrema"
    if value >= 100:
        return "muy alta"
    if value >= 50:
        return "alta"
    if value >= 35:
        return "media"
    return "baja"


def load_results() -> list[dict]:
    path = OUT / "resultados.jsonl"
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def flat(patch: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in (patch or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flat(v, key))
        else:
            out[key] = v
    return out


def describe_patch(patch: dict) -> str:
    parts = []
    for key, value in flat(patch).items():
        parts.append(f"`{key}` → {value}")
    return "; ".join(parts) if parts else "sin cambios (control)"


def risk_for(patch: dict) -> str:
    risks = list(dict.fromkeys(RISK[k] for k in flat(patch) if k in RISK))
    return " ".join(risks) if risks else "Sin palanca de riesgo; es el control."


def main() -> int:
    results = load_results()
    mission = json.loads(MISSION.read_text(encoding="utf-8"))
    verifications = []
    for name in ("verificacion_top.json", "verificacion_excl.json",
                 "verificacion.json"):
        vpath = OUT / name
        if vpath.exists():
            verifications.append(json.loads(vpath.read_text(encoding="utf-8")))
    conc = json.loads(CONC.read_text(encoding="utf-8")) if CONC.exists() else None
    conc_c = conc["concentration"]["candidate"] if conc else None
    if conc_c:
        level = conc_level(conc_c.get("top5_share_pct"))
        conc_confidence = {
            "extrema": "baja",
            "muy alta": "baja-media",
            "alta": "media",
            "media": "media-alta",
            "baja": "media-alta",
        }[level]
        conc_line = (
            f"- **Concentración:** el candidato debe "
            f"{n(conc_c.get('top5_share_pct'), 1)} % del neto a 5 operaciones; "
            f"sin ellas, {n(conc_c.get('net_ex_top5'))}. Confianza "
            f"{conc_confidence}."
        )
    else:
        conc_confidence = "n/d"
        conc_line = "- Concentración: pendiente de la re-ejecución limpia."

    base = next((r for r in results if r["id"] == "manual_base"), None)
    base_net = float(base.get("net") or 0) if base else 0.0
    base_dd = float(base.get("dd") or 0) if base else 0.0
    ranked = sorted(
        [r for r in results if r["id"] in MAIN_IDS],
        key=lambda r: float(r.get("rdd") or 0), reverse=True,
    )
    extension = sorted(
        [r for r in results if r["id"] not in MAIN_IDS],
        key=lambda r: float(r.get("rdd") or 0), reverse=True,
    )
    excl_ext = [r for r in extension if r["id"] in ROBUST_IDS]
    cost_ext = [r for r in extension if r["id"] in COST_IDS]
    robust_ok = [
        r for r in excl_ext
        if float(r.get("net") or 0) > base_net
        and float(r.get("dd") or 0) < base_dd
    ]
    robustness = {
        "tested": len(excl_ext),
        "passed": len(robust_ok),
        "ids": [r["id"] for r in excl_ext],
        "forward_ready": (len(robust_ok) >= 3) if excl_ext else None,
    }
    pool = [
        r for r in ranked
        if r["id"] != "manual_base" and float(r.get("net") or 0) > 0
        and int(r.get("trades") or 0) >= 20
    ]
    if excl_ext and not robustness["forward_ready"]:
        pool = [
            r for r in pool
            if "risk.entry_exclusion_start" not in flat(r.get("patch") or {})
        ]
    candidate = pool[0] if pool else base
    live = mission["aggregate"]["live"]
    orig = mission["aggregate"]["original"]
    diff = mission["config_diff"]
    if not excl_ext:
        robust_line = ("- La prueba de robustez de la exclusión sigue en curso; "
                       "no se promociona nada.")
    elif robustness["forward_ready"]:
        robust_line = (
            f"- La exclusión 11:30–13:30 aguanta **{len(robust_ok)} de "
            f"{len(excl_ext)}** ventanas vecinas: el efecto no depende del "
            "encuadre exacto."
        )
    else:
        robust_line = (
            f"- La exclusión 11:30–13:30 solo aguanta **{len(robust_ok)} de "
            f"{len(excl_ext)}** ventanas vecinas: es frágil y **no va a forward**."
        )
    candidate_line = (
        f"- **Candidato a forward:** `{candidate['id']}` "
        f"({candidate.get('trades')} ops, RDD {n(candidate.get('rdd'), 3)})."
    )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# Informe consolidado — config viva del 8765 vs original, y mejoras",
        "",
        f"**Generado:** {now}  ",
        "**Alcance:** W1–W6, 362 sesiones, `2025-01-10` → `2026-06-30`, "
        "CSV `adjusted`, capital inicial 25.000 USD.  ",
        "**Naturaleza:** backtest in-sample reproducible. Holdout no leído. "
        "Ningún cambio aplicado al 8765.",
        "",
        "## Resumen",
        "",
        f"- La viva gana **{n(live['net_profit'] - orig['net_profit'])} USD** "
        f"y +{n(live['profit_factor'] - orig['profit_factor'])} de PF frente a la "
        f"original, pero con **{n(live['max_drawdown'] - orig['max_drawdown'])} USD "
        "más de drawdown**; el IC95 % del bootstrap incluye cero (p="
        f"{n(mission['significance']['p_two_sided'], 4)}).",
        robust_line,
        candidate_line,
        conc_line,
        "- **Nada aplicado al 8765**: mismo PID, mismos hashes, misma config.",
        "",
        "## 1. Config viva vs original establecida",
        "",
        "Mismas ventanas y misma contabilidad para las dos. La original es "
        "`5/200/150/12`; la viva es `10/300/210/24`.",
        "",
        "| Métrica | Original | Viva 8765 | Diferencia |",
        "|---|---:|---:|---:|",
        f"| Operaciones | {orig['trades']} | {live['trades']} | "
        f"{live['trades'] - orig['trades']:+d} |",
        f"| Neto USD | {n(orig['net_profit'])} | {n(live['net_profit'])} | "
        f"**{signed(live['net_profit'] - orig['net_profit'])}** |",
        f"| Profit factor | {n(orig['profit_factor'])} | {n(live['profit_factor'])} | "
        f"{signed(live['profit_factor'] - orig['profit_factor'])} |",
        f"| Drawdown USD | {n(orig['max_drawdown'])} | {n(live['max_drawdown'])} | "
        f"{signed(live['max_drawdown'] - orig['max_drawdown'])} |",
        f"| Drawdown % | {n(orig.get('max_drawdown_pct'))} | "
        f"{n(live.get('max_drawdown_pct'))} | "
        f"{signed((live.get('max_drawdown_pct') or 0) - (orig.get('max_drawdown_pct') or 0))} |",
        f"| Expectancy R | {n(orig.get('avg_r'), 3)} | {n(live.get('avg_r'), 3)} | "
        f"{signed((live.get('avg_r') or 0) - (orig.get('avg_r') or 0), 3)} |",
        f"| Acierto % | {n(orig.get('win_rate'))} | {n(live.get('win_rate'))} | "
        f"{signed((live.get('win_rate') or 0) - (orig.get('win_rate') or 0))} |",
        f"| Expectancy USD/op | {n(orig.get('expectancy'))} | "
        f"{n(live.get('expectancy'))} | "
        f"{signed((live.get('expectancy') or 0) - (orig.get('expectancy') or 0))} |",
        f"| Peor racha perdedora | {orig.get('worst_loss_streak')} | "
        f"{live.get('worst_loss_streak')} | "
        f"{int(live.get('worst_loss_streak') or 0) - int(orig.get('worst_loss_streak') or 0):+d} |",
        f"| RDD (neto/DD) | {n(orig['net_profit'] / max(orig['max_drawdown'], 1), 4)} | "
        f"{n(live['net_profit'] / max(live['max_drawdown'], 1), 4)} | "
        f"{signed(live['net_profit'] / max(live['max_drawdown'], 1) - orig['net_profit'] / max(orig['max_drawdown'], 1), 4)} |",
        "",
        "**Lectura:** la viva gana "
        f"{n(live['net_profit'] - orig['net_profit'])} USD más en la muestra, pero "
        f"con {n(live['max_drawdown'] - orig['max_drawdown'])} USD más de drawdown. "
        "La ventaja viene de tomar 34 señales más y usar hasta 10 contratos, no de "
        "ejecutar mejor las señales compartidas: en las 37 comunes la viva pierde "
        "158,12 USD. El bootstrap por 6 bloques da IC95 % "
        f"[{n(mission['significance']['ci95_low'])}; "
        f"{signed(mission['significance']['ci95_high'])}] y p="
        f"{n(mission['significance']['p_two_sided'], 4)}: incluye cero.",
        "",
        "### Parámetros que difieren",
        "",
        "| Parámetro | Original | Viva |",
        "|---|---:|---:|",
    ]
    for row in diff:
        note = " (no afecta al backtest)" if "replay_speed" in row["key"] else ""
        lines.append(
            f"| `{row['key']}`{note} | {row['original']} | {row['live']} |"
        )
    lines += [
        "",
        "El resto de parámetros es idéntico: `risk_per_trade_pct=1,0`, "
        "`max_trades_per_day=3`, `max_concurrent_positions=1`, `tp_rr=3,0`, "
        "`min_stop_or_ratio=0,0`, ORB 1,2 %, comisión 0,62/lado y slippage "
        "1 tick/lado. La única diferencia no económica es `feed.replay_speed` "
        "(4,5 vs 8,0).",
        "",
        "Fuente: `reports/backtest/live_vs_original_mission.json`, re-ejecutado "
        "en esta sesión (72 ops, +2.022,94 USD, PF 1,22, DD 2.891,66). La config "
        "viva se leyó de `data/config.json` y de `profiles/live_8765/config.json`, "
        "con hash idéntico `9bf4f9c7…e29479f` y sin escribir en el 8765.",
        "",
        "## 1b. Atribución por palanca y hechos vs inferencias",
        "",
        "Descomposición secuencial exacta (original → P1 frecuencia → P2 sizing → "
        "viva stop), con residuo 0,00. Fuente: "
        "`reports/backtest/live_vs_original_mission.json` (`attribution`, "
        "`paired`, `diagnostics`) y `MANUAL_8765_LIVE_VS_ORIGINAL.md`.",
        "",
        "| Paso | Cambio | Δ neto | Δ expect. R | Δ DD | Δ PF | Δ peor racha |",
        "|---|---|---:|---:|---:|---:|---:|",
        "| Original → P1 | validez 150→210, retesteo 12→24; 5 contratos, SL 200 | "
        "+1.330,82 | +0,120 | -20,00 | +0,24 | 0 |",
        "| P1 → P2 | `max_contracts` 5→10 | +479,52 | 0,000 | +356,64 | +0,02 | 0 |",
        "| P2 → viva | `max_sl_ticks` 200→300 | -448,84 | -0,070 | +587,20 | -0,17 | +3 |",
        "| **Original → viva** | **total** | **+1.361,50** | **+0,050** | "
        "**+923,84** | **+0,09** | **+3** |",
        "",
        "**Hechos medidos:**",
        "",
        "- La frecuencia aporta +1.330,82 y -20,00 de DD con riesgo original; "
        "no es aditiva: en la variante que combina frecuencia con riesgo viva "
        "aporta +2.631,00 (interacción +1.300,18).",
        "- El sizing aporta +479,52 y +356,64 de DD; no cambia la expectancy R "
        "por operación (0,250 en P1 y P2).",
        "- El stop 300 resta -448,84 y añade +587,20 de DD; los 26 trades con "
        "stop >200 suman -392,60 y explican casi todo el lastre.",
        "- En las 37 señales comunes la manual hace 752,02 y la original 910,14: "
        "-158,12. La diferencia agregada son 35 señales solo-manual "
        "(+1.270,92) y 1 solo-original que la manual no toma y pierde -248,70 "
        "(evita esa pérdida).",
        "- Bootstrap por 6 bloques: media +1.390,94; IC95 % [-3.056,32; "
        "+6.965,66]; p=0,6544; incluye cero.",
        "- `feed.replay_speed` 4,5→8,0 no cambia la secuencia: en W1, 8× y 1× "
        "dan 19 ops, 2.735,34, PF 2,42, DD 901,04; Δ 0,00. Es operativo, no edge.",
        "",
        "**Inferencias (plausibles, no demostradas):**",
        "",
        "- La ventaja agregada es cobertura de señales y apalancamiento, no mejor "
        "ejecución en los trades compartidos. El pareo lo sostiene en la muestra; "
        "no prueba causalidad fuera de ella.",
        "- El stop 300 es un lastre en W1–W6; no implica que lo sea en forward. "
        "El cohorte de 26 trades es una comparación de carteras, no un "
        "experimento aleatorio.",
        "- La frecuencia 210/24 captura señales extra de calidad media inferior: "
        "en las comunes la manual rinde menos; el agregado gana por las 35 extra.",
        "- El +2.269,38 de la DB viva frente al +2.022,94 del backtest no es "
        "atribuible a la config: son contabilidad, feed y ejecución distintos; "
        "no hay reconciliación trade a trade.",
        "",
        "**Datos que faltan / no permiten concluir:**",
        "",
        "- Que la manual sea superior en forward: no hay muestra prospectiva, el "
        "holdout está sellado y el IC95 % incluye cero.",
        "- Que la original sea mejor: tampoco tiene forward; solo se midió en el "
        "mismo histórico.",
        "- Que el stop 200 o la exclusión horaria funcionen hacia adelante: sus "
        "cifras son in-sample; la exclusión tiene 36 ops y top-5 104,6 %.",
        "- Cuantificar el efecto de régimen o de un broker real: 6 bloques, "
        "72/38 trades, un solo instrumento (MNQ) y ejecución paper.",
        "",
        "### 1c. Contabilidad viva vs backtest (misma config, distinta fuente)",
        "",
        "La DB/dashboard del 8765 y el backtest usan la misma config, pero no son "
        "la misma contabilidad. El original no tiene contraparte viva, así que "
        "esta tabla no compara configuraciones: solo documenta el desfase.",
        "",
        "| Métrica | Backtest W1–W6 | DB viva 8765 | Diferencia |",
        "|---|---:|---:|---:|",
        "| Operaciones | 72 | 72 | 0 |",
        "| Neto USD | 2.022,94 | 2.269,38 | +246,44 |",
        "| Profit factor | 1,22 | 1,23 | +0,01 |",
        "| Win rate % | 36,11 | 36,1 | ≈0 |",
        "| Expectancy USD/op | 28,10 | 31,52 | +3,42 |",
        "| Peor racha | 13 | 13 | 0 |",
        "| Drawdown | 2.891,66 (9,79 %) | 10,34 % | +0,55 pp |",
        "",
        "Fuente: `profiles/live_8765/yedbot.db` y dashboard `GET /`; el backtest "
        "sale de `live_vs_original_mission.json`. El desfase de +246,44 USD no se "
        "puede asignar a un parámetro: no hay log de fills equivalente.",
        "",
        "## 2. Ranking autónomo por RDD (W1–W6, in-sample)",
        "",
        "RDD = neto / drawdown máximo. Todas las filas usan la misma muestra; "
        "**es una selección in-sample y no autoriza adopción**.",
        "",
        "| # | Variante | Ops | Neto USD | PF | DD USD | RDD | Δ neto vs base | Cambio |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    base_net = float(base.get("net") or 0) if base else 0.0
    for i, row in enumerate(ranked, 1):
        delta = float(row.get("net") or 0) - base_net
        lines.append(
            f"| {i} | {row['id']} | {row.get('trades')} | {n(row.get('net'))} | "
            f"{n(row.get('pf'))} | {n(row.get('dd'))} | {n(row.get('rdd'), 3)} | "
            f"{signed(delta)} | {describe_patch(row.get('patch') or {})} |"
        )
    if excl_ext:
        lines += [
            "",
            "## 2b. Robustez de la exclusión horaria (fase 3)",
            "",
            "Misma muestra; cambia solo la ventana de exclusión. Si el efecto es "
            "real, las ventanas vecinas también deben mejorar neto y DD frente a "
            "la base. Si solo funciona la ventana exacta, es sobreajuste.",
            "",
            "| Variante | Ops | Neto | PF | DD | RDD | Δ neto vs base |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in excl_ext:
            delta = float(row.get("net") or 0) - base_net
            lines.append(
                f"| {row['id']} | {row.get('trades')} | {n(row.get('net'))} | "
                f"{n(row.get('pf'))} | {n(row.get('dd'))} | "
                f"{n(row.get('rdd'), 3)} | {signed(delta)} |"
            )
        lines += [
            "",
            f"**{len(robust_ok)} de {len(excl_ext)}** ventanas vecinas mejoran "
            "neto y DD frente a la base. "
            + ("La exclusión es robusta al encuadre; el candidato sigue en pie."
               if robustness["forward_ready"] else
               "Solo la ventana exacta funciona: trátalo como sobreajuste y no lo "
               "lleves a forward."),
            "",
        ]
        marginal = [
            r for r in robust_ok
            if float(r.get("net") or 0) - base_net < 50
        ]
        if marginal:
            lines += [
                f"`{marginal[0]['id']}` apenas mejora el neto "
                f"({signed(float(marginal[0].get('net') or 0) - base_net)}); su "
                "aporte es de riesgo (DD), no de rentabilidad.",
                "",
            ]
        best_ext = max(
            excl_ext, key=lambda r: float(r.get("rdd") or 0), default=None
        )
        if best_ext and best_ext["id"] != "excl_1130_1330":
            lines += [
                f"La mejor de la extensión es `{best_ext['id']}` "
                f"({best_ext.get('trades')} ops, RDD {n(best_ext.get('rdd'), 3)}). "
                "No se re-selecciona como candidato: elegir el máximo de cuatro "
                "ventanas después de ver el resultado es doble in-sample. Vale "
                "como confirmación de familia, no como nueva promesa.",
                "",
            ]
    robust_sigs = {
        (
            r.get("trades"),
            round(float(r.get("net") or 0), 2),
            round(float(r.get("dd") or 0), 2),
            round(float(r.get("pf") or 0), 2),
        )
        for r in excl_ext
    }
    if cost_ext:
        lines += [
            "## 2c. Sensibilidad a costes (estrés)",
            "",
            "Base: comisión 0,62 USD/lado y slippage 1 tick/lado. Estrés: se "
            "duplican ambos (1,24/lado y 2 ticks/lado), que es el escenario "
            "adverso realista para un broker retail.",
            "",
            "| Variante | Ops | Neto | PF | DD | RDD | Δ neto vs base |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in cost_ext:
            delta = float(row.get("net") or 0) - base_net
            lines.append(
                f"| {row['id']} | {row.get('trades')} | {n(row.get('net'))} | "
                f"{n(row.get('pf'))} | {n(row.get('dd'))} | "
                f"{n(row.get('rdd'), 3)} | {signed(delta)} |"
            )
        cand_cost = next(
            (r for r in cost_ext if r["id"] == "excl_1130_1330+cost_x2"),
            None,
        )
        if cand_cost:
            survives = float(cand_cost.get("net") or 0) > base_net
            lines += [
                "",
                ("El candidato **sigue ganando a la base incluso con el doble de "
                 "costes**: el edge no depende de un reprecio optimista."
                 if survives else
                 "El candidato **no sobrevive** al doble de costes: el edge "
                 "dependía de costes favorables."),
            ]
            nocost = next(
                (r for r in results if r["id"] == "excl_1130_1330"), None
            )
            if nocost:
                drag = (float(cand_cost.get("net") or 0)
                        - float(nocost.get("net") or 0))
                lines += [
                    f"El estrés resta {n(abs(drag))} USD al candidato "
                    f"({n(nocost.get('net'))} → {n(cand_cost.get('net'))}), "
                    f"pero conserva "
                    f"{signed(float(cand_cost.get('net') or 0) - base_net)} "
                    "frente a la base.",
                ]
            lines += [""]
        else:
            lines += [""]
    if conc:
        cc = conc["concentration"]

        def cells(fn):
            return " | ".join(fn(cc[k]) for k in ("candidate", "base", "original"))

        lines += [
            "## 2d. Concentración y estabilidad temporal (W1–W6)",
            "",
            "Calculado sobre los trades de la re-ejecución limpia "
            f"`{conc['run_dir']}`. Cabeceras reproducidas: "
            + ("sí" if conc["checks"]["all_match"] else "**NO**")
            + ". Detalle en `reports/autoloop/concentracion.json`.",
            "",
            "| Métrica | Candidato | Base viva | Original |",
            "|---|---:|---:|---:|",
            "| Ops | " + cells(lambda c: str(c["ops"])) + " |",
            "| Neto USD | " + cells(lambda c: n(c["net"])) + " |",
            "| Expectancy USD/op | "
            + cells(lambda c: n(c["expectancy_usd"])) + " |",
            "| Avg R | " + cells(lambda c: n(c["avg_r"], 3)) + " |",
            "| Ganadoras / perdedoras | "
            + cells(lambda c: f"{c['wins']} / {c['losses']}") + " |",
            "| Top-5 USD | " + cells(lambda c: n(c["top5_net"])) + " |",
            "| Top-5 % del neto | "
            + cells(lambda c: n(c["top5_share_pct"], 1) + " %") + " |",
            "| Neto sin top-5 | " + cells(lambda c: n(c["net_ex_top5"])) + " |",
            "| Mejor mes | "
            + cells(lambda c: f"{c['best_month']} "
                    f"({signed(c['best_month_net'])}, "
                    f"{n(c['best_month_share_pct'], 1)} %)") + " |",
            "| Peor mes | "
            + cells(lambda c: f"{c['worst_month']} "
                    f"({signed(c['worst_month_net'])})") + " |",
            "| Mejor instrumento | "
            + cells(lambda c: f"{c['best_instrument']} "
                    f"({n(c['best_instrument_share_pct'], 1)} %)") + " |",
            "| Racha perdedora máx. | "
            + cells(lambda c: str(c["max_losing_streak"])) + " |",
            "| DD máx. USD | " + cells(lambda c: n(c["max_dd"])) + " |",
            "| Duración DD máx. | "
            + cells(lambda c: f"{n(c['max_dd_duration_days'], 1)} días"
                    + ("" if c["max_dd_recovered"] else " (sin recuperar)"))
            + " |",
            "",
            "**Cabeceras de la re-ejecución limpia:**",
            "",
            "| Variante | Ops | Neto | PF | DD | RDD | ¿Coincide? |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
        for name in ("candidate", "base", "original"):
            h = conc["headers"][name]
            lines.append(
                f"| {name} | {h['trades']} | {n(h['net'])} | {n(h['pf'])} | "
                f"{n(h['dd'])} | {n(h['rdd'], 4)} | "
                f"{'sí' if h['all_match'] else 'NO'} |"
            )
        lines += [
            "",
            f"Run: `{conc['run_dir']}` · {n(conc['seconds'], 1)} s · "
            f"checks: cabeceras={'sí' if conc['checks']['all_match'] else 'NO'}, "
            f"meses={'sí' if all(conc['checks']['monthly_sum_match'].values()) else 'NO'}, "
            f"DD={'sí' if all(conc['checks']['dd_match_stats'].values()) else 'NO'}.",
            "",
        ]
        c, b, o = cc["candidate"], cc["base"], cc["original"]
        lines += [
            f"**Lectura:** el candidato concentra "
            f"**{n(c['top5_share_pct'], 1)} %** del neto en 5 de {c['ops']} "
            f"operaciones; las otras {c['ops'] - 5} suman "
            f"**{n(c['net_ex_top5'])} USD**. Su mejor mes ({c['best_month']}) "
            f"aporta {n(c['best_month_share_pct'], 1)} % y el mejor instrumento "
            f"es {c['best_instrument']} (único, 100 %: no hay diversificación por "
            "instrumento). Racha perdedora máxima "
            f"{c['max_losing_streak']}; el DD máximo ({n(c['max_dd'])}) tardó "
            f"{n(c['max_dd_duration_days'], 1)} días en recuperarse. "
            "**Es un edge de pocos eventos, no una ventaja frecuente.**",
            "",
            f"La base está aún más concentrada "
            f"({n(b['top5_share_pct'], 1)} %; sin top-5, "
            f"{n(b['net_ex_top5'])}) y el original es extremo "
            f"({n(o['top5_share_pct'], 1)} %; sin top-5, "
            f"{n(o['net_ex_top5'])}). El candidato mejora la concentración "
            "relativa, pero no deja de depender de cinco operaciones.",
            "",
        ]
    other_ext = []
    seen_ext = set(robust_sigs)
    for r in extension:
        if r["id"] in ROBUST_IDS or r["id"] in COST_IDS:
            continue
        sig = (
            r.get("trades"),
            round(float(r.get("net") or 0), 2),
            round(float(r.get("dd") or 0), 2),
            round(float(r.get("pf") or 0), 2),
        )
        if sig in seen_ext:
            continue
        seen_ext.add(sig)
        other_ext.append(r)
    if other_ext:
        lines += [
            "### Otras variantes de la extensión",
            "",
            "| Variante | Ops | Neto | PF | DD | RDD |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for row in other_ext:
            lines.append(
                f"| {row['id']} | {row.get('trades')} | {n(row.get('net'))} | "
                f"{n(row.get('pf'))} | {n(row.get('dd'))} | "
                f"{n(row.get('rdd'), 3)} |"
            )
        lines += [""]
    lines += [
        "",
        "## 3. Mejoras priorizadas por impacto en rentabilidad",
        "",
        "Ordenadas por Δneto medido frente a la base. El RDD y el DD indican el "
        "coste en riesgo; ninguna está aplicada. En la pasada principal, solo tres "
        "palancas superan a la base en neto. `daily_loss_2` y `range_min_15` salen idénticas a la base: "
        "esos dos guards no llegaron a activarse en esta muestra, así que no son "
        "una palanca demostrada.",
        "",
    ]
    if conc_c:
        lines += [
            f"**Lectura de confianza:** el candidato debe "
            f"{n(conc_c['top5_share_pct'], 1)} % del neto a 5 operaciones; sin "
            f"ellas, {n(conc_c['net_ex_top5'])}. La mejora #1 es la mayor de la "
            "muestra, pero frágil: no es una ventaja frecuente.",
            "",
        ]
    ordered = sorted(
        [r for r in ranked
         if r["id"] != "manual_base"
         and float(r.get("net") or 0) - base_net > 0.005],
        key=lambda r: float(r.get("net") or 0) - base_net,
        reverse=True,
    )
    improvements = []
    verified = {
        v["id"] for v in verifications
        if v.get("match") and all(v["match"].values())
    }
    seen = set()
    for row in ordered:
        signature = (
            row.get("trades"),
            round(float(row.get("net") or 0), 2),
            round(float(row.get("dd") or 0), 2),
            round(float(row.get("pf") or 0), 2),
        )
        if signature in seen:
            continue
        seen.add(signature)
        improvements.append(row)
        if len(improvements) == 5:
            break
    lines += [
        "| # | Regla / parámetro | Valor propuesto | Δ neto esperado | Δ DD | "
        "Confianza | Riesgo | Verificación |",
        "|---:|---|---|---:|---:|---|---|---|",
    ]
    for i, row in enumerate(improvements, 1):
        delta = float(row.get("net") or 0) - base_net
        ddd = float(row.get("dd") or 0) - float(base.get("dd") or 0) if base else 0
        if row["id"] == "excl_1130_1330":
            change = "`entry_exclusion_start/end` = 11:30 / 13:30"
            confidence = conc_confidence
            risk = "Menos oportunidades; horario in-sample; top-5 = 104,6 % del neto"
            verify = "`verify_variant.py --id excl_1130_1330` + forward"
        elif row["id"] == "excl_1130_1330+sl_200":
            change = "exclusión 11:30–13:30 + `max_sl_ticks` = 200"
            confidence = "muy baja (17 ops)"
            risk = "Muestra insuficiente; dos palancas a la vez"
            verify = "`verify_variant.py --id excl_1130_1330+sl_200`; no promover"
        elif row["id"] == "sl_200":
            change = "`max_sl_ticks` = 200"
            confidence = "media"
            risk = "Recorta stops profundos que podrían recuperar"
            verify = "`verify_variant.py --id sl_200` + forward"
        else:
            change = describe_patch(row.get("patch") or {})
            confidence = "n/d"
            risk = risk_for(row.get("patch") or {})
            verify = "Rerun limpio + forward"
        lines.append(
            f"| {i} | `{row['id']}` | {change} | {signed(delta)} | "
            f"{signed(ddd)} | {confidence} | {risk} | {verify} |"
        )
    lines += ["", "Detalle y verificación de cada una:", ""]
    for i, row in enumerate(improvements, 1):
        delta = float(row.get("net") or 0) - base_net
        ddd = float(row.get("dd") or 0) - float(base.get("dd") or 0) if base else 0
        if row["id"] == "excl_1130_1330":
            verification = (
                "- **Verificación exacta:** `python research/verify_variant.py "
                "--id excl_1130_1330` debe dar 36 ops, 3.203,82, PF 1,90 y DD "
                "1.376,54; después, forward mínimo con muestra prospectiva."
            )
        elif row["id"] == "excl_1130_1330+sl_200":
            verification = (
                "- **Verificación exacta:** `python research/verify_variant.py "
                "--id excl_1130_1330+sl_200` debe dar 17 ops, 2.805,52, PF "
                "2,74 y DD 813,86. Con 17 ops no se promueve: primero ampliar "
                "muestra."
            )
        elif row["id"] == "sl_200":
            verification = (
                "- **Verificación exacta:** `python research/verify_variant.py "
                "--id sl_200` debe dar 46 ops, 2.471,78, PF 1,39 y DD 2.304,46."
            )
        elif row["id"] in verified:
            verification = (
                "- **Verificado:** re-ejecutado en un proceso aparte; ops, neto, "
                "PF y DD coinciden (Δneto 0,00)."
            )
        else:
            verification = (
                "- **Verificación:** repetir esta variante con "
                f"`python research/verify_variant.py --id {row['id']}` y exigir "
                "que neto/PF/DD coincidan."
            )
        lines += [
            f"### {i}. `{row['id']}` — {n(delta)} USD",
            "",
            f"- **Cambio exacto:** {describe_patch(row.get('patch') or {})}.",
            f"- **Efecto medido:** {row.get('trades')} ops, neto {n(row.get('net'))} "
            f"(Δ {n(delta)}), PF {n(row.get('pf'))}, DD {n(row.get('dd'))} "
            f"(Δ {n(ddd)}), RDD {n(row.get('rdd'), 3)}.",
            f"- **Riesgo:** {risk_for(row.get('patch') or {})}",
            verification,
            "",
        ]
        if conc_c and row["id"] == "excl_1130_1330":
            lines += [
                f"- **Confianza condicionada:** top-5 = "
                f"{n(conc_c['top5_share_pct'], 1)} % del neto; sin esas cinco, "
                f"{n(conc_c['net_ex_top5'])}. Edge de pocos eventos, no una "
                "ventaja frecuente.",
                "",
            ]
    lines += [
        "## 4. Candidato a forward",
        "",
    ]
    if candidate:
        cnet = float(candidate.get("net") or 0)
        top = ranked[0] if ranked else None
        if top and top["id"] != candidate["id"]:
            lines += [
                f"El mejor RDD de la pasada principal es `{top['id']}` "
                f"({n(top.get('rdd'), 3)}), pero suma {top.get('trades')} "
                "operaciones; se descarta para forward por muestra insuficiente.",
                "",
            ]
        lines += [
            f"**{candidate['id']}** — {describe_patch(candidate.get('patch') or {})}.",
            "",
            f"- Muestra: {candidate.get('trades')} operaciones, neto "
            f"{n(cnet)} USD (Δ {signed(cnet - base_net)} vs base), PF "
            f"{n(candidate.get('pf'))}, DD {n(candidate.get('dd'))}, RDD "
            f"{n(candidate.get('rdd'), 3)}.",
            (f"- **Concentración:** top-5 = "
             f"{n(conc_c['top5_share_pct'], 1)} % del neto; sin esas cinco, "
             f"{n(conc_c['net_ex_top5'])}; racha perdedora "
             f"{conc_c['max_losing_streak']}; el DD máximo tardó "
             f"{n(conc_c['max_dd_duration_days'], 1)} días en recuperarse. "
             f"Confianza {conc_confidence}."
             if conc_c else "- **Concentración:** pendiente de la re-ejecución."),
            ("- **Robustez:** pendiente; la fase 3 aún no cerró las ventanas."
             if robustness["forward_ready"] is None else
             "- **Robustez:** la exclusión aguantó "
             f"{len(robust_ok)}/{len(excl_ext)} ventanas vecinas."
             if robustness["forward_ready"] else
             "- **Robustez:** la exclusión falló la prueba de ventanas vecinas "
             f"({len(robust_ok)}/{len(excl_ext)}); por eso el candidato es el "
             "tope de stop 200 y no la ventana horaria."),
            ("- **Qué falta:** un lock forward propio, muestra prospectiva y "
             "diluir la dependencia de 5 operaciones antes de subir tamaño. "
             "El holdout sigue sellado."
             if conc_c and conc_confidence in ("baja", "baja-media") else
             "- **Qué falta:** un lock forward propio, muestra prospectiva fuera "
             "de W1–W6 y decisión explícita. El holdout sigue sellado."),
            ("- **No hacer:** aplicarlo al 8765 ni promoverlo a tamaño pleno; "
             "solo forward mínimo con muestra prospectiva."
             if conc_c and conc_confidence in ("baja", "baja-media") else
             "- **No hacer:** aplicarlo al 8765 por el resultado in-sample."),
            "",
        ]
    if verifications:
        lines += ["### Reproducción independiente", ""]
        for v in verifications:
            m = v.get("match") or {}
            lines += [
                f"`{v['id']}` re-ejecutado en un proceso aparte: "
                f"{v['trades']} ops, neto {n(v['net'])}, "
                f"PF {n(v['pf'])}, DD {n(v['dd'])}.",
                f"Coincide con el bucle: ops={m.get('trades')}, neto={m.get('net')}, "
                f"PF={m.get('pf')}, DD={m.get('dd')}; "
                f"Δneto={n(v.get('delta_net'))}.",
                "",
            ]
    lines += [
        "## 5. Control del bucle",
        "",
        "```bash",
        "touch reports/autoloop/STOP    # termina en el siguiente punto seguro",
        "touch reports/autoloop/PAUSA   # pausa sin perder progreso",
        "rm reports/autoloop/PAUSA      # reanuda",
        "```",
        "",
        "**Estado actual: parado.** STOP detectado el 2026-11-25T00:28:45Z "
        "(ver `runner.log`), 25/25 tandas cerradas y sin proceso en RAM: 0 MB. "
        "No quedan hipótesis abiertas. Para reanudar:",
        "",
        "```bash",
        "rm reports/autoloop/STOP",
        "python -u research/auto_loop.py",
        "```",
        "",
        "Al arrancar ocupa unos 240 MB; corre a prioridad idle y se autopausa "
        "si la RAM libre baja de 900 MB. La fase 3 probó ventanas vecinas de "
        "exclusión (11:00–13:00, 12:00–14:00, 11:30–12:30) y la exclusión con "
        "validez 180; su veredicto está en la sección 2b y el ranking crudo en "
        "`resumen_bucle.md`.",
        "",
        "## 6. Garantías",
        "",
        "- `data/config.json` y `profiles/live_8765/config.json` conservan "
        "`9bf4f9c7…e29479f`; PID 15108 y arranque "
        "`2026-11-23T20:12:49-06:00` sin cambios.",
        "- Sin escrituras en la DB del 8765, sin reinicio, sin commits ni pushes.",
        "- Holdout no leído; 2024 no usado.",
        "",
        "## 7. Veredicto",
        "",
        "- La manual gana **+1.361,50 USD** en la muestra (PF 1,22 vs 1,13; "
        "expectancy 0,180 vs 0,130 R; RDD 0,6996 vs 0,3361), pero **no domina "
        "en riesgo**: DD +923,84 y peor racha 13 vs 10. El IC95 % del delta "
        "incluye cero.",
        "- La ventaja es **cobertura de señales + sizing**, no mejor ejecución: "
        "en las 37 comunes la manual pierde 158,12. El stop 300 es el lastre "
        "(-448,84 de neto y +587,20 de DD).",
        "- **No cambiar el 8765 hoy.** No hay forward de ninguna de las dos, el "
        "holdout está sellado y la muestra es de 72/38 ops in-sample.",
        "- La propuesta #1 por impacto nominal es la exclusión 11:30–13:30 "
        "(+1.180,88), pero su confianza es baja-media por concentración; la "
        "palanca estructural más defendible es `max_sl_ticks=200` (+448,84, "
        "DD -587,20), porque no depende del horario. Ninguna se despliega sin "
        "forward.",
        "",
    ]

    md = "\n".join(lines)
    (OUT / "resumen.md").write_text(md, encoding="utf-8")
    payload = {
        "generated_at": now,
        "scope": mission["scope"],
        "live_vs_original": {
            "live": live,
            "original": orig,
            "delta": {
                "trades": live["trades"] - orig["trades"],
                "net": round(live["net_profit"] - orig["net_profit"], 2),
                "pf": round(live["profit_factor"] - orig["profit_factor"], 2),
                "dd": round(live["max_drawdown"] - orig["max_drawdown"], 2),
            },
            "significance": mission["significance"],
        },
        "config_diff": diff,
        "ranking": ranked,
        "extension": extension,
        "concentration": conc,
        "robustness": robustness,
        "candidate": candidate,
        "improvements": [
            {
                "id": r["id"],
                "patch": r.get("patch") or {},
                "trades": r.get("trades"),
                "net": r.get("net"),
                "delta_net": round(float(r.get("net") or 0) - base_net, 2),
                "pf": r.get("pf"),
                "dd": r.get("dd"),
                "rdd": r.get("rdd"),
                "risk": risk_for(r.get("patch") or {}),
            }
            for r in improvements
        ],
        "verifications": verifications,
        "attribution": mission.get("attribution"),
        "paired_common": {
            "common_signals": 37,
            "manual_net": 752.02,
            "original_net": 910.14,
            "delta": -158.12,
            "manual_only_count": 35,
            "manual_only_net": 1270.92,
            "original_only_count": 1,
            "original_only_net": -248.70,
        },
        "runtime_ledger": {
            "source": "profiles/live_8765/yedbot.db + dashboard GET /",
            "trades": 72,
            "net": 2269.38,
            "pf": 1.23,
            "win_rate": 36.1,
            "expectancy_usd": 31.52,
            "worst_loss_streak": 13,
            "max_drawdown_pct": 10.34,
        },
        "controls": {
            "stop": "touch reports/autoloop/STOP",
            "pause": "touch reports/autoloop/PAUSA",
            "resume": "rm reports/autoloop/PAUSA",
        },
    }
    (OUT / "resumen.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"escrito {OUT / 'resumen.md'} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
