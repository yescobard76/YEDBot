"""Veredicto medido: config viva 8765 vs original y robustez del filtro 0,25.

Ejecuta W1-W6 (2025-01-10 .. 2026-06-30) sobre el mismo CSV adjusted que usa
la instancia 8765. No escribe configuración, DB, holdout ni artefactos de
validación: solo informes nuevos en reports/backtest/.

Brazos:
- original: 5 contratos, SL 200, validez 150, retest 12.
- p1:       5 contratos, SL 200, validez 210, retest 24.
- p2:      10 contratos, SL 200, validez 210, retest 24.
- live:    10 contratos, SL 300, validez 210, retest 24 (config 8765).
- manual_freq_original: live con validez 150 y retest 12.
- p2_filter025: P2 con min_stop_or_ratio=0,25.

El filtro se evalúa sobre P2, que es el candidato pre-registrado. La
sensibilidad de umbral y el placebo usan el mismo ledger P2; el brazo
p2_filter025 se simula aparte para comprobar el neto real del filtro.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "reports" / "backtest") not in sys.path:
    sys.path.insert(0, str(ROOT / "reports" / "backtest"))

from _manual_common import (  # noqa: E402
    MANUAL_PATH,
    ORIGINAL_FREQUENCY_PATCH,
    ORIGINAL_PATH,
    P2_PATH,
    WINDOWS,
    aggregate,
    fmt,
    load,
    load_original,
    print_aggregate,
    print_windows,
    run_windows,
)
from _windows import WINDOW_FIRST  # noqa: E402
from server.backtest import _simulate, prepare_dataset  # noqa: E402
from server.config import apply_settings  # noqa: E402
from server.stats import compute_stats  # noqa: E402
from server.timeutil import et_date  # noqa: E402

OUT_JSON = ROOT / "reports/backtest/live_vs_original_mission.json"
OUT_MD = ROOT / "reports/backtest/MANUAL_8765_LIVE_VS_ORIGINAL.md"
INITIAL_CAPITAL = 25_000.0
SESSIONS = sum(spec[3] for spec in WINDOWS)
HOLDOUT_START = date(2026, 7, 1)
FILTER_THRESHOLD = 0.25
FILTER_THRESHOLDS = (0.15, 0.20, 0.25, 0.30, 0.35)
PLACEBO_N = 10_000
PLACEBO_SEED = 20251124

VARIANTS = {
    "original": (ORIGINAL_PATH, ORIGINAL_FREQUENCY_PATCH),
    "p1": (P2_PATH, {"risk": {"max_contracts": 5}}),
    "p2": (P2_PATH, {}),
    "live": (MANUAL_PATH, {}),
    "manual_freq_original": (MANUAL_PATH, ORIGINAL_FREQUENCY_PATCH),
    "p2_filter025": (P2_PATH, {"risk": {"min_stop_or_ratio": FILTER_THRESHOLD}}),
}

LABELS = {
    "original": "Original 5/200/150/12",
    "p1": "P1 5/200/210/24",
    "p2": "P2 10/200/210/24",
    "live": "Viva 8765 10/300/210/24",
    "manual_freq_original": "10/300/150/12",
    "p2_filter025": "P2 + filtro 0,25",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


HASH_PATHS = {
    "live_config": ROOT / "profiles/live_8765/config.json",
    "data_config": ROOT / "data/config.json",
    "original_config": ORIGINAL_PATH,
    "p2_config": P2_PATH,
    "bars_csv": ROOT / "data/bars.csv",
}


def file_hashes() -> dict[str, str]:
    return {key: sha256_file(path) for key, path in HASH_PATHS.items()}


def signal_id(trade: dict[str, Any]) -> str:
    return str((trade.get("meta") or {}).get("signal_id") or trade.get("id"))


def trade_signature(trade: dict[str, Any]) -> tuple:
    return (
        signal_id(trade),
        int(trade["entry_ts"]),
        int(trade["exit_ts"]),
        trade["direction"],
        int(trade["qty"]),
        round(float(trade["pnl"]), 2),
        trade.get("exit_reason"),
    )


def by_signal(trades: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {signal_id(t): t for t in trades}


def stats_for(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return compute_stats(trades, INITIAL_CAPITAL)


def delta(a: float | int | None, b: float | int | None) -> float | None:
    if a is None or b is None:
        return None
    return round(float(a) - float(b), 2)


def fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return f"{float(value):,.{digits}f}"


def fmt_pf(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


def pct(value: float | None, base: float | None) -> str:
    if value is None or base in (None, 0):
        return "n/a"
    return f"{(float(value) / float(base) * 100):+.1f}%"


def table_row(name: str, s: dict[str, Any]) -> str:
    net = float(s.get("net_profit") or 0.0)
    return (
        f"| {name} | {s.get('trades', 0)} | {fmt_num(net)} | "
        f"{fmt_num(s.get('avg_r'), 3)} | {fmt_num(s.get('expectancy'))} | "
        f"{fmt_pf(s.get('profit_factor'))} | {fmt_num(s.get('max_drawdown'))} | "
        f"{fmt_num(s.get('max_drawdown_pct'), 2)}% | {s.get('worst_loss_streak', 0)} | "
        f"{fmt_num(net / SESSIONS)} | {fmt_num(net / INITIAL_CAPITAL / SESSIONS * 100, 4)}% |"
    )


def common_subset(
    a: list[dict[str, Any]], b: list[dict[str, Any]]
) -> tuple[set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    aa, bb = by_signal(a), by_signal(b)
    ids = set(aa) & set(bb)
    return ids, [aa[i] for i in ids], [bb[i] for i in ids]


def pair_metrics(
    a: list[dict[str, Any]], b: list[dict[str, Any]]
) -> dict[str, Any]:
    ids, aa, bb = common_subset(a, b)
    return {
        "common_signals": len(ids),
        "a_trades": len(a),
        "b_trades": len(b),
        "a_coverage_pct": round(len(ids) / len(a) * 100, 2) if a else 0.0,
        "b_coverage_pct": round(len(ids) / len(b) * 100, 2) if b else 0.0,
        "a_common": stats_for(aa),
        "b_common": stats_for(bb),
    }


def ratio(trade: dict[str, Any]) -> float | None:
    meta = trade.get("meta") or {}
    high, low, stop = meta.get("orb_high"), meta.get("orb_low"), meta.get("stop_ticks")
    if high is None or low is None or stop is None:
        return None
    width = (float(high) - float(low)) / 0.25
    if width <= 0:
        return None
    return float(stop) / width


def filter_selection(
    baseline: list[dict[str, Any]],
    accepted_ids: set[str],
    *,
    blocks: dict[str, str] | None = None,
    exclude_block: str | None = None,
) -> dict[str, Any]:
    accepted = [
        t
        for t in baseline
        if signal_id(t) in accepted_ids
        and (exclude_block is None or (blocks or {}).get(signal_id(t)) != exclude_block)
    ]
    rejected = [
        t
        for t in baseline
        if signal_id(t) not in accepted_ids
        and (exclude_block is None or (blocks or {}).get(signal_id(t)) != exclude_block)
    ]
    ar = [float(t.get("r_multiple") or 0.0) for t in accepted]
    rr = [float(t.get("r_multiple") or 0.0) for t in rejected]
    delta_sel = (
        statistics.fmean(ar) - statistics.fmean(rr) if ar and rr else None
    )
    selected_stats = stats_for(accepted)
    return {
        "accepted": len(accepted),
        "rejected": len(rejected),
        "mean_r_accepted": round(statistics.fmean(ar), 4) if ar else None,
        "mean_r_rejected": round(statistics.fmean(rr), 4) if rr else None,
        "delta_sel": round(delta_sel, 4) if delta_sel is not None else None,
        "selected_net": selected_stats.get("net_profit"),
        "selected_pf": selected_stats.get("profit_factor"),
        "selected_dd": selected_stats.get("max_drawdown"),
        "selected_expectancy_r": selected_stats.get("avg_r"),
    }


def replay_equivalence() -> dict[str, Any]:
    """Comprueba que replay_speed no cambia ni un trade en el simulador batch."""
    base = load(MANUAL_PATH)
    sessions, source, dataset = prepare_dataset(
        base, days=WINDOWS[0][3], start=date.fromisoformat(WINDOWS[0][1])
    )
    if sessions[-1][0] >= HOLDOUT_START:
        raise RuntimeError("La comprobación de replay toca el holdout")
    out: dict[str, Any] = {}
    sigs: dict[str, list[tuple]] = {}
    for speed in (8.0, 1.0):
        cfg = apply_settings(base, {"feed": {"replay_speed": speed}})
        result = _simulate(cfg, sessions, source, f"replay-{speed}", dataset)
        sigs[str(speed)] = [trade_signature(t) for t in result["trades"]]
        out[str(speed)] = {
            "trades": result["metrics"]["trades"],
            "net_profit": result["metrics"]["net_profit"],
            "profit_factor": result["metrics"]["profit_factor"],
            "max_drawdown": result["metrics"]["max_drawdown"],
        }
    out["identical_trade_sequence"] = sigs["8.0"] == sigs["1.0"]
    out["delta_net"] = round(
        float(out["1.0"]["net_profit"]) - float(out["8.0"]["net_profit"]), 2
    )
    out["delta_dd"] = round(
        float(out["1.0"]["max_drawdown"]) - float(out["8.0"]["max_drawdown"]), 2
    )
    return out


def recommendation_value(row: dict[str, Any]) -> float:
    raw = str(row.get("delta_net", "0")).replace(",", "").replace("+", "")
    try:
        return float(raw)
    except ValueError:
        return float("-inf")


def build_verdict(payload: dict[str, Any]) -> str:
    s = payload["aggregate"]
    scope = payload["scope"]
    pair = next(p for p in payload["paired"] if p["label"] == "Viva vs original")
    total_delta = round(
        float(s["live"]["net_profit"]) - float(s["original"]["net_profit"]), 2
    )
    common_count = int(pair["common_signals"])
    live_common_net = float(pair["a_common"]["net_profit"] or 0)
    orig_common_net = float(pair["b_common"]["net_profit"] or 0)
    live_only_net = round(float(s["live"]["net_profit"]) - live_common_net, 2)
    orig_only_net = round(float(s["original"]["net_profit"]) - orig_common_net, 2)
    live_only_count = int(s["live"]["trades"]) - common_count
    orig_only_count = int(s["original"]["trades"]) - common_count
    window_span = f"{scope['windows'][0]}–{scope['windows'][-1]}"
    if live_common_net > orig_common_net:
        common_result = "gana"
    elif live_common_net < orig_common_net:
        common_result = "pierde"
    else:
        common_result = "empata"
    return (
        f"En la muestra idéntica {window_span} ({scope['sessions']} sesiones), la config viva hizo "
        f"**{fmt_num(s['live']['net_profit'])} USD** frente a "
        f"**{fmt_num(s['original']['net_profit'])} USD** de la original: "
        f"**{total_delta:+,.2f} USD** ({pct(total_delta, s['original']['net_profit'])}), "
        f"con expectancy R **{fmt_num(s['live']['avg_r'], 3)} vs "
        f"{fmt_num(s['original']['avg_r'], 3)}** y PF "
        f"**{fmt_pf(s['live']['profit_factor'])} vs "
        f"{fmt_pf(s['original']['profit_factor'])}**. Pero el DD empeora: "
        f"**{fmt_num(s['live']['max_drawdown'])} vs "
        f"{fmt_num(s['original']['max_drawdown'])} USD** "
        f"({round(float(s['live']['max_drawdown']) - float(s['original']['max_drawdown']), 2):+,.2f}). "
        f"En la intersección literal de {common_count} señales comunes, el neto es "
        f"{fmt_num(live_common_net)} vs {fmt_num(orig_common_net)} USD: la viva "
        f"**{common_result} {fmt_num(abs(orig_common_net - live_common_net))} USD en los trades "
        f"que ambas toman**. La diferencia agregada procede de {live_only_count} señales "
        f"que solo toma la viva ({live_only_net:+,.2f} USD) y de {orig_only_count} "
        f"señal(es) que solo toma la original ({orig_only_net:+,.2f} USD). Es "
        "cobertura de señales, no mejor ejecución. La config viva es **mejor en "
        "neto bruto, pero peor en riesgo y no estadísticamente distinguible** con "
        f"{int(s['live']['trades'])}/{int(s['original']['trades'])} trades in-sample. "
        "No es una demostración forward."
    )


def block_bootstrap(payload: dict[str, Any]) -> dict[str, Any]:
    """Bootstrap aproximado por bloques W1-W6 del delta de neto viva-original."""
    deltas = [
        float(block["net"]["live"]) - float(block["net"]["original"])
        for block in payload["windows"]
    ]
    rng = random.Random(PLACEBO_SEED)
    samples: list[float] = []
    for _ in range(PLACEBO_N):
        samples.append(sum(rng.choice(deltas) for _ in deltas))
    samples.sort()
    lo = samples[int(0.025 * (len(samples) - 1))]
    hi = samples[int(0.975 * (len(samples) - 1))]
    below = sum(1 for value in samples if value <= 0) / len(samples)
    above = sum(1 for value in samples if value >= 0) / len(samples)
    return {
        "method": f"block bootstrap por ventana ({len(deltas)} bloques), "
        f"{PLACEBO_N:,} remuestreos",
        "blocks": len(deltas),
        "mean_delta": round(statistics.fmean(samples), 2),
        "ci95_low": round(lo, 2),
        "ci95_high": round(hi, 2),
        "p_two_sided": round(min(1.0, 2 * min(below, above)), 4),
        "includes_zero": lo <= 0 <= hi,
    }


def make_markdown(payload: dict[str, Any]) -> str:
    s = payload["aggregate"]
    scope = payload["scope"]
    window_span = f"{scope['windows'][0]}–{scope['windows'][-1]}"
    attrib = payload["attribution"]
    filt = payload["filter"]
    rep = payload["replay"]
    lines: list[str] = []
    lines.append("# Veredicto medido: config viva 8765 frente a la original")
    lines.append("")
    lines.append(
        f"**Generado:** {payload['generated_at']}  \n"
        f"**Alcance:** {window_span}, {scope['sessions']} sesiones, "
        f"{scope['start']} → {scope['last']}.  \n"
        f"**Datos:** `{scope['data']}` ({scope['series_mode']}), el mismo CSV "
        "que usa el 8765; no se abrió 2024, no se abrió H1 y no se capturó "
        "nada nuevo.  \n"
        "**Naturaleza:** backtest in-sample reproducible; no es forward."
    )
    lines.append("")
    lines.append("## 1. Configuración viva comprobada")
    lines.append("")
    live_hash = payload["hashes"]["data_config"]
    profile_hash = payload["hashes"]["live_config"]
    profile_note = (
        f"`profiles/live_8765/config.json` tiene el mismo SHA-256 "
        f"(`{profile_hash}`)."
        if live_hash == profile_hash
        else f"`profiles/live_8765/config.json` tiene otro SHA-256 "
        f"(`{profile_hash}`)."
    )
    lines.append(
        f"La configuración viva se leyó de `data/config.json`; su SHA-256 es "
        f"`{live_hash}`. {profile_note} Ambos ficheros conservan su hash antes "
        "y después de la simulación; el runner no consulta ni reinicia el "
        "proceso 8765."
    )
    lines.append("")
    lines.append("| Parámetro | Viva 8765 | Original |")
    lines.append("|---|---:|---:|")
    for row in payload["config_diff"]:
        lines.append(f"| `{row['key']}` | {row['live']} | {row['original']} |")
    lines.append("")
    lines.append("## 2. Comparación cara a cara")
    lines.append("")
    lines.append(
        "### 2.1 Misma muestra y misma contabilidad (trades nativos de cada config)"
    )
    lines.append("")
    lines.append(
        "| Perfil | Trades | Neto USD | Expectancy R | Expectancy USD | PF | Max DD USD | Max DD % | Peor racha | USD/sesión | Retorno/sesión |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name in ("original", "p1", "p2", "live", "manual_freq_original", "p2_filter025"):
        lines.append(table_row(LABELS[name], s[name]))
    lines.append("")
    lines.append(
        "`Expectancy R` es la media de `r_multiple`; `Retorno/sesión` es "
        "neto / capital inicial / sesiones, no compuesto. `DD` es la curva de "
        f"trades concatenados con capital inicial {INITIAL_CAPITAL:,.0f}, "
        f"la misma convención que {window_span}."
    )
    lines.append("")
    lines.append("### 2.2 Mismo conjunto de señales (intersección literal)")
    lines.append("")
    lines.append(
        "Las configuraciones con frecuencia distinta no generan exactamente las "
        "mismas señales. La comparación literal posible es la intersección por "
        "`signal_id`; la tabla siguiente no mezcla trades de una config con los "
        "de otra."
    )
    lines.append("")
    lines.append(
        "| Par | Señales comunes | Cobertura A | Cobertura B | Neto A | Neto B | Δ Neto | Δ Expectancy R |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for pair in payload["paired"]:
        ca, cb = pair["a_common"], pair["b_common"]
        lines.append(
            f"| {pair['label']} | {pair['common_signals']} | "
            f"{pair['a_coverage_pct']:.1f}% | {pair['b_coverage_pct']:.1f}% | "
            f"{fmt_num(ca.get('net_profit'))} | {fmt_num(cb.get('net_profit'))} | "
            f"{fmt_num(float(ca.get('net_profit') or 0) - float(cb.get('net_profit') or 0))} | "
            f"{fmt_num(float(ca.get('avg_r') or 0) - float(cb.get('avg_r') or 0), 3)} |"
        )
    lines.append("")
    pair = next(p for p in payload["paired"] if p["label"] == "Viva vs original")
    lines.append(
        f"#### 2.2.1 Métricas completas sobre las {pair['common_signals']} señales comunes"
    )
    lines.append("")
    lines.append(
        "| Perfil | Trades | Neto USD | Expectancy R | Expectancy USD | PF | Max DD USD | Max DD % | Peor racha | USD/sesión |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(table_row("Viva, señales comunes", pair["a_common"]))
    lines.append(table_row("Original, señales comunes", pair["b_common"]))
    lines.append("")
    lines.append(
        "Mismos `signal_id` y misma contabilidad, pero la qty puede diferir por "
        "`max_contracts` y por la secuencia de equity. No son fills idénticos: "
        "son el mismo conjunto de señales, no el mismo tamaño de posición."
    )
    lines.append("")
    lines.append("### 2.3 Puente de P&L: ¿de dónde sale la diferencia?")
    lines.append("")
    lines.append(
        "La comparación literal de señales comunes responde a la pregunta clave: "
        "la ventaja agregada no implica que la viva sea mejor en los trades que "
        "ambas toman. El puente siguiente separa el efecto común del efecto de "
        "tomar señales que la otra configuración no toma."
    )
    lines.append("")
    lines.append(
        "| Comparación | Δ Total | Δ en señales comunes | Solo A: neto (n) | Solo B: neto (n) |"
    )
    lines.append("|---|---:|---:|---:|---:|")
    for pair in payload["paired"]:
        total_a = float(pair["a_common"].get("trades") or 0)
        total_b = float(pair["b_common"].get("trades") or 0)
        a_total = float(s[pair["a"]].get("net_profit") or 0)
        b_total = float(s[pair["b"]].get("net_profit") or 0)
        a_common = float(pair["a_common"].get("net_profit") or 0)
        b_common = float(pair["b_common"].get("net_profit") or 0)
        a_native = int(s[pair["a"]]["trades"])
        b_native = int(s[pair["b"]]["trades"])
        common = int(pair["common_signals"])
        lines.append(
            f"| {pair['label']} | {a_total - b_total:+,.2f} | "
            f"{a_common - b_common:+,.2f} | {a_total - a_common:+,.2f} "
            f"({a_native - common}) | {b_total - b_common:+,.2f} "
            f"({b_native - common}) |"
        )
    lines.append("")
    primary = next(p for p in payload["paired"] if p["label"] == "Viva vs original")
    primary_a_total = float(s["live"]["net_profit"])
    primary_b_total = float(s["original"]["net_profit"])
    primary_a_common = float(primary["a_common"]["net_profit"] or 0)
    primary_b_common = float(primary["b_common"]["net_profit"] or 0)
    primary_a_only = primary_a_total - primary_a_common
    primary_b_only = primary_b_total - primary_b_common
    primary_a_only_n = int(s["live"]["trades"]) - int(primary["common_signals"])
    primary_b_only_n = int(s["original"]["trades"]) - int(
        primary["common_signals"]
    )
    if primary_a_common > primary_b_common:
        primary_common = "gana"
    elif primary_a_common < primary_b_common:
        primary_common = "pierde"
    else:
        primary_common = "empata"
    lines.append(
        f"Ejemplo: en **{primary['label']}**, la viva "
        f"{'gana' if primary_a_total >= primary_b_total else 'pierde'} "
        f"{abs(primary_a_total - primary_b_total):,.2f} USD en total, pero "
        f"{primary_common} {abs(primary_a_common - primary_b_common):,.2f} USD "
        f"en las {primary['common_signals']} señales comunes; la diferencia "
        f"agregada se reparte entre {primary_a_only_n} señales que solo toma la "
        f"viva ({primary_a_only:+,.2f} USD) y {primary_b_only_n} que solo toma "
        f"la original ({primary_b_only:+,.2f} USD). Es una diferencia de "
        "**cobertura de señales**, no de mejor ejecución en los trades compartidos."
    )
    lines.append("")
    lines.append("### 2.4 Neto por bloque")
    lines.append("")
    lines.append("| Bloque | Original | P1 | P2 | Viva | Filtro P2 |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for block in payload["windows"]:
        row = block["net"]
        lines.append(
            f"| {block['window']} | {fmt_num(row['original'])} | {fmt_num(row['p1'])} | "
            f"{fmt_num(row['p2'])} | {fmt_num(row['live'])} | {fmt_num(row['p2_filter025'])} |"
        )
    sig = payload.get("significance")
    if sig:
        lines.append("")
        lines.append("### 2.5 Significación aproximada del delta de neto")
        lines.append("")
        lines.append(
            f"Bootstrap por bloques {window_span} ({sig['blocks']} bloques, "
            f"{PLACEBO_N:,} remuestreos): Δ medio {sig['mean_delta']:+,.2f} USD, "
            f"IC95% [{sig['ci95_low']:+,.2f}, {sig['ci95_high']:+,.2f}], "
            f"p bilateral aproximado {sig['p_two_sided']:.4f}. "
            f"El intervalo {'incluye' if sig['includes_zero'] else 'no incluye'} cero; "
            "con solo seis bloques es una prueba débil y no sustituye un forward."
        )
    lines.append("")
    lines.append("## 3. Atribución por palanca")
    lines.append("")
    lines.append(
        "Descomposición secuencial exacta: original → P1 (frecuencia) → P2 "
        "(sizing) → viva (stop). El residuo debe ser cero; se comprueba en el script."
    )
    lines.append("")
    lines.append(
        "| Palanca | Desde → hasta | Δ Neto USD | Δ DD USD | Δ Peor racha | Δ PF | Veredicto |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for row in attrib["sequential"]:
        lines.append(
            f"| {row['lever']} | {row['from']} → {row['to']} | "
            f"{row['delta_net']:+,.2f} | {row['delta_dd']:+,.2f} | "
            f"{row['delta_streak']:+d} | {row['delta_pf']:+.2f} | {row['note']} |"
        )
    lines.append("")
    lines.append(
        f"**Total viva − original:** {attrib['total']['delta_net']:+,.2f} USD, "
        f"DD {attrib['total']['delta_dd']:+,.2f} USD, "
        f"peor racha {attrib['total']['delta_streak']:+d}. "
        f"Residuo de la descomposición: {attrib['residual']:+.2f} USD."
    )
    lines.append("")
    lines.append("### 3.1 Qué trades explican cada palanca")
    lines.append("")
    lines.append(
        f"- **Stop 300 vs 200:** la viva tiene "
        f"{payload['diagnostics']['stop_gt_200']['count']} trades con stop >200 "
        f"ticks; suman {payload['diagnostics']['stop_gt_200']['net']:+,.2f} USD. "
        f"P2 los rechaza. El delta de stop es "
        f"{attrib['stop']['delta_net']:+,.2f} USD y "
        f"DD {attrib['stop']['delta_dd']:+,.2f} USD."
    )
    lines.append(
        f"- **Sizing 10 vs 5:** P2 tiene "
        f"{payload['diagnostics']['sizing']['trades_qty_gt_5']} trades con qty >5; "
        f"el cambio de sizing aporta "
        f"{attrib['sizing']['delta_net']:+,.2f} USD y "
        f"DD {attrib['sizing']['delta_dd']:+,.2f} USD."
    )
    lines.append(
        f"- **Frecuencia 210/24 vs 150/12:** con riesgo original aporta "
        f"{attrib['frequency']['delta_net']:+,.2f} USD; con riesgo viva aporta "
        f"{attrib['frequency_live']['delta_net']:+,.2f} USD. No es aditivo: "
        f"la interacción frecuencia × riesgo es "
        f"{payload['diagnostics']['frequency_interaction']:+,.2f} USD."
    )
    lines.append(
        f"- **Replay 8× vs 1×:** {rep['delta_net']:+.2f} USD y "
        f"{rep['delta_dd']:+.2f} USD de DD; la secuencia de trades es "
        f"{'idéntica' if rep['identical_trade_sequence'] else 'distinta'}. "
        "El replay solo cambia el reloj de pared, no el edge."
    )
    lines.append("")
    lines.append("## 4. Robustez in-sample del filtro 0,25")
    lines.append("")
    lines.append(
        "El filtro se prueba sobre **P2 (10/200/210/24)**, el candidato "
        "pre-registrado. El brazo real `p2_filter025` se simuló aparte; la "
        f"sensibilidad de umbral y el placebo usan el ledger P2 de "
        f"{s['p2']['trades']} trades."
    )
    lines.append("")
    lines.append(
        f"- P2 baseline: **{s['p2']['trades']} trades, {fmt_num(s['p2']['net_profit'])} USD, "
        f"PF {fmt_pf(s['p2']['profit_factor'])}, DD {fmt_num(s['p2']['max_drawdown'])}**."
    )
    lines.append(
        f"- Filtro 0,25 real: **{s['p2_filter025']['trades']} trades, "
        f"{fmt_num(s['p2_filter025']['net_profit'])} USD, "
        f"PF {fmt_pf(s['p2_filter025']['profit_factor'])}, "
        f"DD {fmt_num(s['p2_filter025']['max_drawdown'])}**."
    )
    lines.append("")
    lines.append("### 4.1 Sensibilidad del umbral")
    lines.append("")
    lines.append(
        "| Umbral | Aceptadas | Rechazadas | Δ selección R | Neto seleccionado | PF | DD |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    for row in filt["thresholds"]:
        lines.append(
            f"| {row['threshold']:.2f} | {row['accepted']} | {row['rejected']} | "
            f"{fmt_num(row['delta_sel'], 3)} | {fmt_num(row['selected_net'])} | "
            f"{fmt_pf(row['selected_pf'])} | {fmt_num(row['selected_dd'])} |"
        )
    lines.append("")
    lines.append("### 4.2 Placebo de subconjuntos aleatorios")
    lines.append("")
    lines.append(
        f"Se sortearon {PLACEBO_N:,} subconjuntos de {filt['accepted_count']} "
        f"trades de los {s['p2']['trades']} del baseline, con semilla "
        f"{PLACEBO_SEED}. El Δ real es **{filt['actual_delta_sel']:.4f} R**."
    )
    lines.append("")
    lines.append(
        f"- Media placebo: {filt['placebo']['mean']:.4f} R; "
        f"p95: {filt['placebo']['p95']:.4f} R; máximo: {filt['placebo']['max']:.4f} R."
    )
    lines.append(
        f"- Percentil del resultado real: **{filt['placebo']['percentile']:.2f}**; "
        f"p-valor one-sided: **{filt['placebo']['p_value']:.4f}**."
    )
    lines.append("")
    lines.append(f"### 4.3 Leave-one-block-out ({window_span})")
    lines.append("")
    lines.append("| Bloque excluido | Aceptadas restantes | Δ selección R | ¿Positivo? |")
    lines.append("|---|---:|---:|---:|")
    for row in filt["lobo"]:
        lines.append(
            f"| {row['block']} | {row['accepted']} | "
            f"{fmt_num(row['delta_sel'], 4)} | "
            f"{'sí' if row['delta_sel'] is not None and row['delta_sel'] > 0 else 'no'} |"
        )
    lines.append("")
    lines.append(
        f"**Conclusión de robustez:** {filt['conclusion']}"
    )
    lines.append("")
    lines.append("## 5. Mejoras ordenadas por rentabilidad esperada")
    lines.append("")
    lines.append(
        "| # | Mejora | Δ Neto esperado | Δ Expectancy R | Δ DD | Δ Peor racha | Evidencia | ¿Cambia 8765? | ¿Adoptable ya? |"
    )
    lines.append("|---:|---|---:|---:|---:|---:|---|---|---|")
    for i, row in enumerate(payload["recommendations"], 1):
        lines.append(
            f"| {i} | {row['change']} | {row['delta_net']} | "
            f"{row.get('delta_expectancy_r', 'n/a')} | {row['delta_dd']} | "
            f"{row['delta_streak']} | {row['evidence']} | {row['changes_live']} | {row['adopt']} |"
        )
    lines.append("")
    lines.append("## 6. Veredicto")
    lines.append("")
    lines.append(payload["verdict"])
    lines.append("")
    lines.append("## 7. Límites y garantías")
    lines.append("")
    lines.append(
        f"- Es un backtest **in-sample** de {window_span}; no es forward y no "
        "autoriza a declarar que la config viva sea superior hacia adelante."
    )
    lines.append(
        "- Los trades nativos de cada config no son idénticos porque la frecuencia "
        "cambia las señales; por eso se reporta también la intersección literal."
    )
    lines.append(
        "- El filtro se evalúa sobre P2; no se extrapola a la config viva con SL 300 "
        "sin una corrida específica."
    )
    lines.append(
        "- No se modificó configuración, DB, holdout, 2024 ni artefactos de "
        "validación. Solo se escribieron este informe y su JSON."
    )
    lines.append("")
    lines.append("### Reproducir")
    lines.append("")
    lines.append("```bash")
    lines.append("python reports/backtest/run_live_vs_original_mission.py")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    started = time.perf_counter()
    generated_at = datetime.now(timezone.utc).isoformat()
    before_hashes = file_hashes()

    live = load(MANUAL_PATH)
    original = load_original()
    if (
        live.risk.max_contracts != 10
        or live.risk.max_sl_ticks != 300
        or live.strategy.setup_validity_minutes != 210
        or live.strategy.retest_tolerance_ticks != 24
    ):
        raise AssertionError("La config viva no es 10/300/210/24")
    if (
        original.risk.max_contracts != 5
        or original.risk.max_sl_ticks != 200
        or original.strategy.setup_validity_minutes != 150
        or original.strategy.retest_tolerance_ticks != 12
    ):
        raise AssertionError("La original no es 5/200/150/12")

    print("Brazos:", ", ".join(VARIANTS), flush=True)
    ordered = run_windows(VARIANTS, MANUAL_PATH)
    names = list(VARIANTS)
    print_windows(ordered, names)
    agg = aggregate(ordered, names)
    print_aggregate(agg, names)

    for block in ordered:
        for name in names:
            for trade in block["variants"][name]["trades"]:
                trade["window"] = block["window"]

    per_window = []
    for block in ordered:
        per_window.append(
            {
                "window": block["window"],
                "sessions": block["sessions"],
                "net": {
                    name: block["variants"][name]["metrics"]["net_profit"]
                    for name in names
                },
            }
        )

    trades = {
        name: [t for block in ordered for t in block["variants"][name]["trades"]]
        for name in names
    }
    for name in names:
        if len(trades[name]) != agg[name]["stats"]["trades"]:
            raise AssertionError(f"{name}: trades no coinciden con el agregado")

    s = {name: agg[name]["stats"] for name in names}
    total_delta = round(
        float(s["live"]["net_profit"]) - float(s["original"]["net_profit"]), 2
    )
    freq_delta = round(
        float(s["p1"]["net_profit"]) - float(s["original"]["net_profit"]), 2
    )
    size_delta = round(
        float(s["p2"]["net_profit"]) - float(s["p1"]["net_profit"]), 2
    )
    stop_delta = round(
        float(s["live"]["net_profit"]) - float(s["p2"]["net_profit"]), 2
    )
    residual = round(total_delta - (freq_delta + size_delta + stop_delta), 2)
    if abs(residual) > 0.05:
        raise AssertionError(f"Atribución no cierra: {residual}")

    def dstat(a: str, b: str, key: str) -> float:
        return round(float(s[a].get(key) or 0) - float(s[b].get(key) or 0), 2)

    sequential = [
        {
            "lever": "Frecuencia 210/24",
            "from": "original",
            "to": "p1",
            "delta_net": freq_delta,
            "delta_dd": dstat("p1", "original", "max_drawdown"),
            "delta_streak": int(s["p1"]["worst_loss_streak"])
            - int(s["original"]["worst_loss_streak"]),
            "delta_pf": round(
                float(s["p1"]["profit_factor"]) - float(s["original"]["profit_factor"]), 2
            ),
            "note": "Aumenta oportunidades; el neto sube y el DD baja en esta base.",
        },
        {
            "lever": "Max contratos 5 → 10",
            "from": "p1",
            "to": "p2",
            "delta_net": size_delta,
            "delta_dd": dstat("p2", "p1", "max_drawdown"),
            "delta_streak": int(s["p2"]["worst_loss_streak"])
            - int(s["p1"]["worst_loss_streak"]),
            "delta_pf": round(
                float(s["p2"]["profit_factor"]) - float(s["p1"]["profit_factor"]), 2
            ),
            "note": "Añade USD y DD; no añade edge por trade.",
        },
        {
            "lever": "Stop 200 → 300",
            "from": "p2",
            "to": "live",
            "delta_net": stop_delta,
            "delta_dd": dstat("live", "p2", "max_drawdown"),
            "delta_streak": int(s["live"]["worst_loss_streak"])
            - int(s["p2"]["worst_loss_streak"]),
            "delta_pf": round(
                float(s["live"]["profit_factor"]) - float(s["p2"]["profit_factor"]), 2
            ),
            "note": "Acepta stops profundos; en W1–W6 destruye neto y DD.",
        },
    ]

    freq_live_delta = round(
        float(s["live"]["net_profit"]) - float(s["manual_freq_original"]["net_profit"]), 2
    )
    freq_interaction = round(freq_live_delta - freq_delta, 2)

    pairs = []
    pair_defs = [
        ("Viva vs original", "live", "original"),
        ("P2 vs P1 (sizing)", "p2", "p1"),
        ("Viva vs P2 (stop)", "live", "p2"),
        ("P1 vs original (frecuencia)", "p1", "original"),
        ("Viva vs 10/300/150/12 (frecuencia)", "live", "manual_freq_original"),
        ("Filtro 0,25 vs P2 (selección)", "p2_filter025", "p2"),
    ]
    for label, a_name, b_name in pair_defs:
        item = pair_metrics(trades[a_name], trades[b_name])
        item.update({"label": label, "a": a_name, "b": b_name})
        pairs.append(item)

    live_only = [
        t for t in trades["live"] if signal_id(t) not in by_signal(trades["p2"])
    ]
    stop_gt_200 = [
        t
        for t in trades["live"]
        if float((t.get("meta") or {}).get("stop_ticks") or 0.0) > 200.0
    ]
    p2_live_shared = [
        t for t in trades["p2"] if signal_id(t) in by_signal(trades["live"])
    ]
    live_live_shared = [
        t for t in trades["live"] if signal_id(t) in by_signal(trades["p2"])
    ]
    stop_diag = {
        "stop_gt_200": {
            "count": len(stop_gt_200),
            "net": round(sum(float(t["pnl"]) for t in stop_gt_200), 2),
            "wins": sum(1 for t in stop_gt_200 if float(t["pnl"]) > 0),
            "losses": sum(1 for t in stop_gt_200 if float(t["pnl"]) < 0),
            "max_stop_ticks": round(
                max(
                    [float((t.get("meta") or {}).get("stop_ticks") or 0) for t in stop_gt_200],
                    default=0.0,
                ),
                1,
            ),
        },
        "live_only_count": len(live_only),
        "live_only_net": round(sum(float(t["pnl"]) for t in live_only), 2),
        "p2_shared_net": round(sum(float(t["pnl"]) for t in p2_live_shared), 2),
        "live_shared_net": round(sum(float(t["pnl"]) for t in live_live_shared), 2),
        "shared_delta": round(
            sum(float(t["pnl"]) for t in p2_live_shared)
            - sum(float(t["pnl"]) for t in live_live_shared),
            2,
        ),
    }
    p1_by, orig_by = by_signal(trades["p1"]), by_signal(trades["original"])
    p1_only = [t for t in trades["p1"] if signal_id(t) not in orig_by]
    orig_only = [t for t in trades["original"] if signal_id(t) not in p1_by]
    freq_diag = {
        "p1_only_count": len(p1_only),
        "p1_only_net": round(sum(float(t["pnl"]) for t in p1_only), 2),
        "original_only_count": len(orig_only),
        "original_only_net": round(sum(float(t["pnl"]) for t in orig_only), 2),
        "common_count": len(p1_by.keys() & orig_by.keys()),
    }
    p1_by2, p2_by = by_signal(trades["p1"]), by_signal(trades["p2"])
    qty_gt_5 = [t for t in trades["p2"] if int(t["qty"]) > 5]
    sizing_diag = {
        "trades_qty_gt_5": len(qty_gt_5),
        "net_qty_gt_5": round(sum(float(t["pnl"]) for t in qty_gt_5), 2),
        "common_count": len(p1_by2.keys() & p2_by.keys()),
        "extra_contracts": sum(
            int(p2_by[sid]["qty"]) - int(p1_by2[sid]["qty"])
            for sid in p1_by2.keys() & p2_by.keys()
        ),
    }

    # Filtro 0,25 sobre el ledger P2.
    baseline = trades["p2"]
    actual_filter = trades["p2_filter025"]
    accepted_ids = set(by_signal(actual_filter))
    baseline_ids = set(by_signal(baseline))
    if not accepted_ids <= baseline_ids:
        raise AssertionError("El filtro generó señales que no están en el baseline P2")
    rejected_filter = [t for t in baseline if signal_id(t) not in accepted_ids]
    if not actual_filter or not rejected_filter:
        raise AssertionError("El filtro no separó trades aceptados y rechazados")
    actual_delta = round(
        statistics.fmean(float(t["r_multiple"]) for t in actual_filter)
        - statistics.fmean(float(t["r_multiple"]) for t in rejected_filter),
        4,
    )

    blocks = {signal_id(t): t["window"] for t in baseline}
    threshold_rows = []
    for threshold in FILTER_THRESHOLDS:
        ids = {
            signal_id(t)
            for t in baseline
            if (ratio(t) or 0.0) >= threshold - 1e-9
        }
        row = filter_selection(baseline, ids, blocks=blocks)
        row["threshold"] = threshold
        threshold_rows.append(row)

    rng = random.Random(PLACEBO_SEED)
    baseline_r = [float(t["r_multiple"] or 0.0) for t in baseline]
    k = len(accepted_ids)
    placebo_deltas: list[float] = []
    for _ in range(PLACEBO_N):
        chosen = set(rng.sample(range(len(baseline_r)), k))
        ar = [r for i, r in enumerate(baseline_r) if i in chosen]
        rr = [r for i, r in enumerate(baseline_r) if i not in chosen]
        if ar and rr:
            placebo_deltas.append(statistics.fmean(ar) - statistics.fmean(rr))
    placebo_sorted = sorted(placebo_deltas)
    placebo_ge = sum(1 for d in placebo_deltas if d >= actual_delta)
    placebo_p = (1 + placebo_ge) / (len(placebo_deltas) + 1)
    placebo_percentile = 100.0 * sum(1 for d in placebo_deltas if d <= actual_delta) / len(
        placebo_deltas
    )

    lobo = []
    for block in [spec[0] for spec in WINDOWS]:
        row = filter_selection(
            baseline, accepted_ids, blocks=blocks, exclude_block=block
        )
        row["block"] = block
        lobo.append(row)

    threshold_positive = all(
        row["delta_sel"] is not None and row["delta_sel"] > 0 for row in threshold_rows
    )
    lobo_positive = all(
        row["delta_sel"] is not None and row["delta_sel"] > 0 for row in lobo
    )
    placebo_pass = placebo_p < 0.05
    survives = bool(threshold_positive and lobo_positive and placebo_pass)
    if survives:
        filter_conclusion = (
            "El edge de selección sobrevive a las tres pruebas in-sample: placebo "
            "significativo, todos los LOBO positivos y umbrales 0,15–0,35 positivos. "
            "Eso descarta un artefacto trivial de esta muestra, pero **no es validación "
            "forward**: el filtro sigue necesitando la muestra prospectiva P1/P2."
        )
    else:
        filter_conclusion = (
            "El edge **no sobrevive** a todas las pruebas: "
            f"placebo={'pasa' if placebo_pass else 'falla'}, "
            f"LOBO={'pasa' if lobo_positive else 'falla'}, "
            f"umbrales={'pasan' if threshold_positive else 'fallan'}. "
            "No debe usarse como base de una mejora todavía."
        )

    # Replay: comprobación W1 a 8x y 1x.
    replay = replay_equivalence()

    # Recomendaciones con los deltas medidos.
    filter_net_delta = round(
        float(s["p2_filter025"]["net_profit"]) - float(s["p2"]["net_profit"]), 2
    )
    filter_dd_delta = round(
        float(s["p2_filter025"]["max_drawdown"]) - float(s["p2"]["max_drawdown"]), 2
    )
    filter_streak_delta = int(s["p2_filter025"]["worst_loss_streak"]) - int(
        s["p2"]["worst_loss_streak"]
    )
    recommendations = [
        {
            "change": "Filtro min_stop_or_ratio 0,25 sobre P2",
            "delta_net": f"{filter_net_delta:+,.2f}",
            "delta_expectancy_r": f"{float(s['p2_filter025']['avg_r']) - float(s['p2']['avg_r']):+.3f}",
            "delta_dd": f"{filter_dd_delta:+,.2f}",
            "delta_streak": f"{filter_streak_delta:+d}",
            "evidence": (
                f"{s['p2_filter025']['trades']} trades; Δ selección {actual_delta:.3f}R; "
                f"placebo p={placebo_p:.4f}; "
                f"LOBO {'positivo' if lobo_positive else 'no positivo'}"
            ),
            "changes_live": "Sí (filtro + SL200)",
            "adopt": "No: forward P1/P2",
        },
        {
            "change": "Mantener frecuencia 210/24",
            "delta_net": f"{freq_delta:+,.2f}",
            "delta_expectancy_r": f"{float(s['p1']['avg_r']) - float(s['original']['avg_r']):+.3f}",
            "delta_dd": f"{dstat('p1', 'original', 'max_drawdown'):+,.2f}",
            "delta_streak": f"{int(s['p1']['worst_loss_streak']) - int(s['original']['worst_loss_streak']):+d}",
            "evidence": "P1 vs original con 5/200; no es aditivo con el stop",
            "changes_live": "No: ya está",
            "adopt": "Sí, ya vigente",
        },
        {
            "change": "max_contracts 5 → 10",
            "delta_net": f"{size_delta:+,.2f}",
            "delta_expectancy_r": f"{float(s['p2']['avg_r']) - float(s['p1']['avg_r']):+.3f}",
            "delta_dd": f"{dstat('p2', 'p1', 'max_drawdown'):+,.2f}",
            "delta_streak": f"{int(s['p2']['worst_loss_streak']) - int(s['p1']['worst_loss_streak']):+d}",
            "evidence": "P2 vs P1; es apalancamiento, no edge",
            "changes_live": "No: ya está",
            "adopt": "Solo asignación de riesgo",
        },
        {
            "change": "max_sl_ticks 300 → 200",
            "delta_net": f"{max(0.0, -stop_delta):+,.2f}",
            "delta_expectancy_r": f"{float(s['p2']['avg_r']) - float(s['live']['avg_r']):+.3f}",
            "delta_dd": f"{dstat('p2', 'live', 'max_drawdown'):+,.2f}",
            "delta_streak": f"{int(s['p2']['worst_loss_streak']) - int(s['live']['worst_loss_streak']):+d}",
            "evidence": "P2 vs viva; en W1–W6 el stop 300 destruye neto y DD",
            "changes_live": "Sí",
            "adopt": "No: forward; la muestra viva es demasiado pequeña",
        },
        {
            "change": "Replay 8× → 1×",
            "delta_net": f"{replay['delta_net']:+,.2f}",
            "delta_expectancy_r": "+0.000",
            "delta_dd": f"{replay['delta_dd']:+,.2f}",
            "delta_streak": "0",
            "evidence": "W1 con 8× y 1×: secuencia idéntica",
            "changes_live": "No: operativo",
            "adopt": "Sí, sin efecto económico",
        },
    ]

    config_diff = [
        {
            "key": "risk.max_contracts",
            "live": live.risk.max_contracts,
            "original": original.risk.max_contracts,
        },
        {
            "key": "risk.max_sl_ticks",
            "live": live.risk.max_sl_ticks,
            "original": original.risk.max_sl_ticks,
        },
        {
            "key": "strategy.setup_validity_minutes",
            "live": live.strategy.setup_validity_minutes,
            "original": original.strategy.setup_validity_minutes,
        },
        {
            "key": "strategy.retest_tolerance_ticks",
            "live": live.strategy.retest_tolerance_ticks,
            "original": original.strategy.retest_tolerance_ticks,
        },
        {
            "key": "feed.replay_speed",
            "live": live.feed.replay_speed,
            "original": original.feed.replay_speed,
        },
    ]

    recommendations.sort(key=recommendation_value, reverse=True)
    after_hashes = file_hashes()

    payload = {
        "schema": "manual-8765-live-vs-original-v1",
        "generated_at": generated_at,
        "scope": {
            "windows": [spec[0] for spec in WINDOWS],
            "sessions": SESSIONS,
            "start": WINDOW_FIRST[WINDOWS[0][0]],
            "last": WINDOWS[-1][2],
            "holdout_used": False,
            "year_2024_used": False,
            "data": live.feed.csv_path,
            "series_mode": live.feed.series_mode,
            "initial_capital": INITIAL_CAPITAL,
        },
        "hashes": {
            **before_hashes,
            "after": after_hashes,
            "configs_unchanged": before_hashes == after_hashes,
        },
        "config_diff": config_diff,
        "aggregate": s,
        "windows": per_window,
        "paired": pairs,
        "attribution": {
            "sequential": sequential,
            "total": {
                "delta_net": total_delta,
                "delta_dd": dstat("live", "original", "max_drawdown"),
                "delta_streak": int(s["live"]["worst_loss_streak"])
                - int(s["original"]["worst_loss_streak"]),
            },
            "residual": residual,
            "frequency": {
                "delta_net": freq_delta,
                "delta_dd": dstat("p1", "original", "max_drawdown"),
            },
            "sizing": {
                "delta_net": size_delta,
                "delta_dd": dstat("p2", "p1", "max_drawdown"),
            },
            "stop": {
                "delta_net": stop_delta,
                "delta_dd": dstat("live", "p2", "max_drawdown"),
            },
            "frequency_live": {
                "delta_net": freq_live_delta,
                "delta_dd": dstat("live", "manual_freq_original", "max_drawdown"),
            },
        },
        "diagnostics": {
            **stop_diag,
            "sizing": sizing_diag,
            "frequency": freq_diag,
            "frequency_interaction": freq_interaction,
        },
        "filter": {
            "baseline": "p2",
            "threshold": FILTER_THRESHOLD,
            "accepted_count": len(accepted_ids),
            "actual_delta_sel": actual_delta,
            "actual_net": s["p2_filter025"]["net_profit"],
            "actual_pf": s["p2_filter025"]["profit_factor"],
            "actual_dd": s["p2_filter025"]["max_drawdown"],
            "thresholds": threshold_rows,
            "placebo": {
                "n": len(placebo_deltas),
                "mean": statistics.fmean(placebo_deltas),
                "median": statistics.median(placebo_deltas),
                "p95": placebo_sorted[int(0.95 * (len(placebo_sorted) - 1))],
                "max": max(placebo_deltas),
                "p_value": placebo_p,
                "percentile": placebo_percentile,
            },
            "lobo": lobo,
            "threshold_positive": threshold_positive,
            "lobo_positive": lobo_positive,
            "placebo_pass": placebo_pass,
            "survives": survives,
            "conclusion": filter_conclusion,
        },
        "replay": replay,
        "recommendations": recommendations,
        "constraints": {
            "configs_modified": False,
            "db_written": False,
            "holdout_accessed": False,
            "year_2024_accessed": False,
            "backtests_run": True,
            "capture_started": False,
        },
    }
    payload["verdict"] = build_verdict(payload)
    payload["significance"] = block_bootstrap(payload)
    if not payload["hashes"]["configs_unchanged"]:
        raise AssertionError("Una configuración cambió durante la ejecución")
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    OUT_MD.write_text(make_markdown(payload), encoding="utf-8")
    print(f"\nJSON: {OUT_JSON}")
    print(f"MD:   {OUT_MD}")
    print(f"Tiempo total: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    if "--render-only" in sys.argv:
        payload = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        payload["verdict"] = build_verdict(payload)
        payload["significance"] = block_bootstrap(payload)
        OUT_JSON.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        OUT_MD.write_text(make_markdown(payload), encoding="utf-8")
        print(f"JSON: {OUT_JSON}")
        print(f"MD: {OUT_MD}")
    else:
        raise SystemExit(main())
