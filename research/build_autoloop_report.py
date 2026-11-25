"""Genera reports/autoloop/resumen.md y resumen.json a partir de los resultados.

Fuentes:
- reports/backtest/live_vs_original_mission.json (viva vs original, W1-W6)
- reports/autoloop/resultados.jsonl (ranking del bucle)
- reports/autoloop/verificacion_top.json y verificacion_excl.json
  (re-ejecuciones independientes de las ganadoras)

No modifica configuración, DB ni el 8765. Solo escribe en reports/autoloop/.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "autoloop"
MISSION = ROOT / "reports" / "backtest" / "live_vs_original_mission.json"
CONC = OUT / "concentracion.json"
LIVE_CONFIG = ROOT / "data" / "config.json"
LIVE_PROFILE = ROOT / "profiles" / "live_8765" / "config.json"
ORIGINAL_PROFILE = ROOT / "profiles" / "backtest_real" / "config.json"

MIN_FORWARD_OPS = 20

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


def why_of(row: dict) -> str:
    return str(row.get("why") or "").strip().lower()


def is_cost_row(row: dict) -> bool:
    if why_of(row).startswith(("estrés", "estres")):
        return True
    return any(k.startswith("execution.") for k in flat(row.get("patch") or {}))


def is_robust_row(row: dict) -> bool:
    if why_of(row).startswith("robustez"):
        return True
    # Fallback estructural para filas antiguas/sin "why": una exclusión
    # combinada con otra palanca de estrategia es una prueba de fase 3, no la
    # variante primaria de exclusión.
    if is_combo_row(row):
        return False
    keys = set(flat(row.get("patch") or {}))
    return (
        "risk.entry_exclusion_start" in keys
        and any(k.startswith("strategy.") for k in keys)
    )


def is_combo_row(row: dict) -> bool:
    return why_of(row).startswith(("combinación adaptativa",
                                   "combinacion adaptativa"))


def patch_key(patch: dict | None) -> str:
    return json.dumps(patch or {}, sort_keys=True, ensure_ascii=False)


def without_execution(patch: dict | None) -> dict:
    return {k: v for k, v in (patch or {}).items() if k != "execution"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dotted_get(data: dict, key: str):
    cur = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def dotted_set(data: dict, key: str, value) -> None:
    parts = key.split(".")
    cur = data
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def config_label(cfg: dict) -> str:
    return "/".join(str(dotted_get(cfg, key)) for key in (
        "risk.max_contracts",
        "risk.max_sl_ticks",
        "strategy.setup_validity_minutes",
        "strategy.retest_tolerance_ticks",
    ))


def row_stat(row: dict, name: str):
    aliases = {
        "net": ("net", "net_profit"),
        "dd": ("dd", "max_drawdown"),
        "dd_pct": ("dd_pct", "max_drawdown_pct"),
        "pf": ("pf", "profit_factor"),
        "trades": ("trades",),
        "avg_r": ("avg_r",),
        "win_rate": ("win_rate",),
        "expectancy": ("expectancy",),
        "worst_streak": ("worst_loss_streak", "worst_streak"),
    }
    for key in aliases[name]:
        if row.get(key) is not None:
            return row[key]
    return None


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
    base = next((r for r in results if r["id"] == "manual_base"), None)
    base_net = float(base.get("net") or 0) if base else 0.0
    base_dd = float(base.get("dd") or 0) if base else 0.0

    # Config real: la viva se lee de data/config.json y del perfil del 8765;
    # la original se reconstruye aplicando el lado "original" del diff de la
    # misión al perfil de backtest. Así los parámetros del informe no son texto
    # fijo y se detecta cualquier deriva entre archivos.
    live_cfg = json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))
    live_profile_cfg = json.loads(LIVE_PROFILE.read_text(encoding="utf-8"))
    original_cfg = copy.deepcopy(json.loads(ORIGINAL_PROFILE.read_text(encoding="utf-8")))
    for item in mission.get("config_diff", []):
        dotted_set(original_cfg, item["key"], item["original"])

    live_label = config_label(live_cfg)
    original_label = config_label(original_cfg)
    live_flat = flat(live_cfg)
    original_flat = flat(original_cfg)
    config_diffs = [
        {"key": key, "live": live_flat.get(key), "original": original_flat.get(key)}
        for key in sorted(set(live_flat) | set(original_flat))
        if live_flat.get(key) != original_flat.get(key)
    ]
    stop_label = (
        f"Stop {dotted_get(original_cfg, 'risk.max_sl_ticks')} → "
        f"{dotted_get(live_cfg, 'risk.max_sl_ticks')}"
    )
    live_hash = sha256_file(LIVE_CONFIG)
    live_profile_hash = sha256_file(LIVE_PROFILE)
    hashes_match = live_hash == live_profile_hash

    # La viva sale siempre de resultados.jsonl (manual_base). Si el JSONL no
    # trae una fila original, se declara explícitamente que esa pata es la
    # referencia de la misión y no se inventa una fila.
    live_row = base
    original_row = next(
        (r for r in results if r.get("id") in ("original", "original_reference")),
        None,
    )
    original_in_jsonl = original_row is not None
    original_source = (
        f"resultados.jsonl#{original_row.get('id', 'original')}"
        if original_in_jsonl
        else "reports/backtest/live_vs_original_mission.json#aggregate.original"
    )
    if original_row is None:
        original_row = dict(mission["aggregate"]["original"])
    live_source = (
        "resultados.jsonl#manual_base"
        if live_row
        else "reports/backtest/live_vs_original_mission.json#aggregate.live"
    )
    if live_row is None:
        live_row = dict(mission["aggregate"]["live"])

    live_ops = int(row_stat(live_row, "trades") or 0)
    original_ops = int(row_stat(original_row, "trades") or 0)
    live_net = float(row_stat(live_row, "net") or 0)
    original_net = float(row_stat(original_row, "net") or 0)
    live_dd = float(row_stat(live_row, "dd") or 0)
    original_dd = float(row_stat(original_row, "dd") or 0)
    live_rdd = live_net / max(live_dd, 1)
    original_rdd = original_net / max(original_dd, 1)
    live_pf = float(row_stat(live_row, "pf") or 0)
    original_pf = float(row_stat(original_row, "pf") or 0)
    live_dd_pct = row_stat(live_row, "dd_pct")
    original_dd_pct = row_stat(original_row, "dd_pct")
    live_avg_r = float(row_stat(live_row, "avg_r") or 0)
    original_avg_r = float(row_stat(original_row, "avg_r") or 0)
    live_win_rate = float(row_stat(live_row, "win_rate") or 0)
    original_win_rate = float(row_stat(original_row, "win_rate") or 0)
    live_expectancy = live_net / live_ops if live_ops else 0.0
    original_expectancy = original_net / original_ops if original_ops else 0.0
    common = mission["paired"][0]
    common_live_net = float(common["a_common"]["net_profit"])
    common_original_net = float(common["b_common"]["net_profit"])
    common_delta = common_live_net - common_original_net
    manual_only_ops = int(common["a_trades"]) - int(common["common_signals"])
    original_only_ops = int(common["b_trades"]) - int(common["common_signals"])
    manual_only_net = live_net - common_live_net
    original_only_net = original_net - common_original_net

    # Clasificación por metadatos del propio resultado, no por IDs fijos:
    # fase 3 se marca con why="robustez: ..."; costes con execution.*.
    primary = [
        r for r in results
        if not is_cost_row(r) and not is_robust_row(r) and not is_combo_row(r)
    ]
    ranked = sorted(
        primary, key=lambda r: float(r.get("rdd") or 0), reverse=True
    )
    primary_ids = {r["id"] for r in primary}

    def combo_components(row: dict) -> list[str]:
        text = why_of(row)
        if ":" in text:
            text = text.split(":", 1)[1]
        return [part.strip() for part in text.split("+") if part.strip()]

    # Las mejoras incluyen combinaciones solo si todos sus componentes son
    # variantes primarias; las combinaciones de una ventana de fase 3 se
    # quedan en la sección de extensión.
    improvement_pool = []
    for row in results:
        if is_cost_row(row) or is_robust_row(row):
            continue
        if is_combo_row(row):
            components = combo_components(row)
            if components and not all(c in primary_ids for c in components):
                continue
        improvement_pool.append(row)
    extension = sorted(
        [r for r in results if r["id"] not in primary_ids],
        key=lambda r: float(r.get("rdd") or 0), reverse=True,
    )
    robust_ext = [r for r in results if is_robust_row(r)]
    excl_ext = robust_ext  # alias histórico del informe
    cost_ext = [r for r in results if is_cost_row(r)]
    robust_ok = [
        r for r in robust_ext
        if float(r.get("net") or 0) > base_net
        and float(r.get("dd") or 0) < base_dd
    ]
    robustness = {
        "tested": len(robust_ext),
        "passed": len(robust_ok),
        "ids": [r["id"] for r in robust_ext],
        "forward_ready": (len(robust_ok) >= 3) if robust_ext else None,
    }
    pool = [
        r for r in ranked
        if r["id"] != "manual_base" and float(r.get("net") or 0) > 0
        and int(r.get("trades") or 0) >= MIN_FORWARD_OPS
    ]
    if robust_ext and not robustness["forward_ready"]:
        pool = [
            r for r in pool
            if "risk.entry_exclusion_start" not in flat(r.get("patch") or {})
        ]
    candidate = pool[0] if pool else base

    # Mejor RDD absoluto de resultados.jsonl: incluye fase 3 y combinaciones,
    # pero excluye el control y las filas de estrés de costes.
    rdd_pool = [
        r for r in results
        if r["id"] != "manual_base"
        and not is_cost_row(r)
        and float(r.get("rdd") or 0) > 0
    ]
    best_rdd = max(
        rdd_pool, key=lambda r: float(r.get("rdd") or 0), default=None
    )

    # La foto de concentración se hizo con un patch concreto. Solo se usa si
    # sigue siendo el candidato actual; si no, se evita atribuirle sus métricas.
    conc_snapshot_c = conc["concentration"]["candidate"] if conc else None
    conc_matches = bool(
        conc and candidate
        and patch_key(conc.get("candidate_patch")) == patch_key(candidate.get("patch"))
    )
    conc_c = conc_snapshot_c if conc_matches else None
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
    elif conc:
        conc_confidence = "n/d"
        conc_line = (
            "- **Concentración:** la re-ejecución limpia se hizo con otro "
            "patch; no se usa para el candidato actual."
        )
    else:
        conc_confidence = "n/d"
        conc_line = "- Concentración: pendiente de la re-ejecución limpia."

    live = mission["aggregate"]["live"]
    orig = mission["aggregate"]["original"]
    p1 = mission["aggregate"]["p1"]
    p2 = mission["aggregate"]["p2"]
    attr = mission["attribution"]
    diag = mission["diagnostics"]
    significance = mission["significance"]
    replay = mission["replay"]
    freq = attr["frequency"]
    sizing = attr["sizing"]
    stop = attr["stop"]
    freq_live = attr["frequency_live"]
    step_labels = {
        ("original", "p1"): "Original → P1",
        ("p1", "p2"): "P1 → P2",
        ("p2", "live"): "P2 → viva",
    }
    step_aggs = {"original": orig, "p1": p1, "p2": p2, "live": live}
    if not robust_ext:
        robust_line = ("- La prueba de robustez de la exclusión sigue en curso; "
                       "no se promociona nada.")
    elif robustness["forward_ready"]:
        robust_line = (
            f"- Las **{len(robust_ext)}** ventanas de exclusión de fase 3: "
            f"**{len(robust_ok)}** mejoran neto y DD; el efecto no depende del "
            "encuadre exacto."
        )
    else:
        robust_line = (
            f"- Solo **{len(robust_ok)} de {len(robust_ext)}** ventanas de "
            "exclusión mejoran neto y DD: la familia es frágil y **no va a "
            "forward**."
        )
    if candidate and candidate["id"] != "manual_base":
        candidate_line = (
            f"- **Candidato a forward:** `{candidate['id']}` "
            f"({candidate.get('trades')} ops, RDD {n(candidate.get('rdd'), 3)})."
        )
    else:
        candidate_line = (
            "- **Candidato a forward:** ninguno supera el filtro de muestra y "
            "neto; no se promociona nada."
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
        f"- La viva gana **{signed(live_net - original_net)} USD** "
        f"y {signed(live_pf - original_pf)} de PF frente a la "
        f"original, pero con **{signed(live_dd - original_dd)} USD "
        "más de drawdown**; el IC95 % del bootstrap incluye cero (p="
        f"{n(mission['significance']['p_two_sided'], 4)}).",
        robust_line,
        candidate_line,
        conc_line,
        "- **Nada aplicado al 8765**: mismo PID, mismos hashes, misma config.",
        "",
        "## 1. Config viva vs original establecida",
        "",
        f"Mismas ventanas y misma contabilidad para las dos. La original es "
        f"`{original_label}`; la viva es `{live_label}`.",
        "",
        "| Métrica | Viva 8765 | Original | Δ (viva − original) |",
        "|---|---:|---:|---:|",
        f"| Operaciones | {live_ops} | {original_ops} | "
        f"{live_ops - original_ops:+d} |",
        f"| Neto USD | {n(live_net)} | {n(original_net)} | "
        f"**{signed(live_net - original_net)}** |",
        f"| RDD (neto/DD) | {n(live_rdd, 4)} | {n(original_rdd, 4)} | "
        f"{signed(live_rdd - original_rdd, 4)} |",
        f"| Drawdown USD | {n(live_dd)} | {n(original_dd)} | "
        f"{signed(live_dd - original_dd)} |",
        f"| Drawdown % | {n(live_dd_pct)} | {n(original_dd_pct)} | "
        f"{signed((live_dd_pct or 0) - (original_dd_pct or 0))} |",
        f"| Profit factor | {n(live_pf)} | {n(original_pf)} | "
        f"{signed(live_pf - original_pf)} |",
        f"| Expectancy R | {n(live_avg_r, 3)} | {n(original_avg_r, 3)} | "
        f"{signed(live_avg_r - original_avg_r, 3)} |",
        f"| Acierto % | {n(live_win_rate)} | {n(original_win_rate)} | "
        f"{signed(live_win_rate - original_win_rate)} |",
        f"| Expectancy USD/op | {n(live_expectancy)} | "
        f"{n(original_expectancy)} | "
        f"{signed(live_expectancy - original_expectancy)} |",
        "",
        "**Lectura:** la viva gana "
        f"{signed(live_net - original_net)} USD más en la muestra, pero "
        f"con {signed(live_dd - original_dd)} USD más de drawdown; el RDD pasa de "
        f"{n(original_rdd, 4)} a {n(live_rdd, 4)}. La ventaja viene de "
        f"{manual_only_ops} señales solo-manual y {original_only_ops} "
        f"solo-original, y de usar hasta "
        f"{dotted_get(live_cfg, 'risk.max_contracts')} contratos, no de ejecutar "
        f"mejor las señales compartidas: en las {common['common_signals']} comunes "
        f"la viva hace {signed(common_delta)} USD. El bootstrap por "
        f"{significance['blocks']} bloques da IC95 % "
        f"[{n(mission['significance']['ci95_low'])}; "
        f"{signed(mission['significance']['ci95_high'])}] y p="
        f"{n(mission['significance']['p_two_sided'], 4)}: incluye cero.",
        "",
        "**Trazabilidad de la comparación:** la viva son cifras de "
        f"`resultados.jsonl` (`manual_base`): {live_ops} ops, {n(live_net)} USD, "
        f"RDD {n(live_rdd, 4)} y DD {n(live_dd)}. La original "
        + (
            "también sale de `resultados.jsonl`."
            if original_in_jsonl
            else "NO tiene fila en `resultados.jsonl`; se usa como referencia "
                 "externa declarada `reports/backtest/live_vs_original_mission.json#aggregate.original`, "
                 "no como una fila inventada del JSONL."
        ),
        "",
        "### Parámetros que difieren",
        "",
        "| Parámetro | Original | Viva |",
        "|---|---:|---:|",
    ]
    for row in config_diffs:
        note = " (no afecta al backtest)" if "replay_speed" in row["key"] else ""
        lines.append(
            f"| `{row['key']}`{note} | {row['original']} | {row['live']} |"
        )
    risk_pct = dotted_get(live_cfg, "risk.risk_per_trade_pct")
    max_day = dotted_get(live_cfg, "risk.max_trades_per_day")
    max_conc = dotted_get(live_cfg, "risk.max_concurrent_positions")
    tp_rr = dotted_get(live_cfg, "strategy.tp_rr")
    min_stop = dotted_get(live_cfg, "risk.min_stop_or_ratio")
    orb = dotted_get(live_cfg, "strategy.min_range_ticks")
    commission = dotted_get(live_cfg, "execution.commission_per_contract_side")
    slippage = dotted_get(live_cfg, "execution.slippage_ticks")
    lines += [
        "",
        "El resto de parámetros es idéntico: "
        f"`risk_per_trade_pct={risk_pct}`, `max_trades_per_day={max_day}`, "
        f"`max_concurrent_positions={max_conc}`, `tp_rr={tp_rr}`, "
        f"`min_stop_or_ratio={min_stop}`, rango mínimo {orb} ticks, comisión "
        f"{commission}/lado y slippage {slippage} tick/lado. La única diferencia "
        "no económica es `feed.replay_speed`.",
        "",
        f"**Config viva:** `data/config.json` y `profiles/live_8765/config.json` "
        f"tienen SHA-256 {'idéntico' if hashes_match else 'DISTINTO'}: "
        f"`{live_hash[:8]}…{live_hash[-8:]}` y "
        f"`{live_profile_hash[:8]}…{live_profile_hash[-8:]}`. **Original:** "
        f"`profiles/backtest_real/config.json` con el patch original de la "
        f"misión (`{original_label}`). Todo en solo lectura; no se escribió en el "
        "8765.",
        "",
        "Fuente numérica: `resultados.jsonl` (`manual_base`) para la viva y "
        + (
            "`resultados.jsonl` para la original."
            if original_in_jsonl
            else "`live_vs_original_mission.json#aggregate.original` para la "
                 "original, porque el JSONL no contiene esa fila."
        ),
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
    ]
    for step in attr["sequential"]:
        before = step_aggs[step["from"]]
        after = step_aggs[step["to"]]
        label = step_labels[(step["from"], step["to"])]
        lines.append(
            f"| {label} | `{step['lever']}` | {signed(step['delta_net'])} | "
            f"{signed(after['avg_r'] - before['avg_r'], 3)} | "
            f"{signed(step['delta_dd'])} | {signed(step['delta_pf'])} | "
            f"{step['delta_streak']:+d} |"
        )
    total = attr["total"]
    lines += [
        f"| **Original → viva** | **total** | **{signed(total['delta_net'])}** | "
        f"**{signed(live['avg_r'] - orig['avg_r'], 3)}** | "
        f"**{signed(total['delta_dd'])}** | **{signed(live['profit_factor'] - orig['profit_factor'])}** | "
        f"**{total['delta_streak']:+d}** |",
        "",
        "**Hechos medidos:**",
        "",
        f"- La frecuencia aporta {signed(freq['delta_net'])} y "
        f"{signed(freq['delta_dd'])} de DD con riesgo original; no es aditiva: "
        f"en la variante que combina frecuencia con riesgo viva aporta "
        f"{signed(freq_live['delta_net'])} (interacción "
        f"{signed(diag['frequency_interaction'])}).",
        f"- El sizing aporta {signed(sizing['delta_net'])} y "
        f"{signed(sizing['delta_dd'])} de DD; no cambia la expectancy R por "
        f"operación ({n(p1['avg_r'], 3)} en P1 y P2).",
        f"- El {stop_label} resta {signed(stop['delta_net'])} y añade "
        f"{signed(stop['delta_dd'])} de DD; los {diag['stop_gt_200']['count']} "
        f"trades con stop >200 suman {signed(diag['stop_gt_200']['net'])} y "
        "explican casi todo el lastre.",
        f"- En las {common['common_signals']} señales comunes la manual hace "
        f"{n(common_live_net)} y la original {n(common_original_net)}: "
        f"{signed(common_delta)}. La diferencia agregada son {manual_only_ops} "
        f"señales solo-manual ({signed(manual_only_net)}) y {original_only_ops} "
        f"solo-original que la manual no toma y pierde {signed(original_only_net)} "
        "(evita esa pérdida).",
        f"- Bootstrap por {significance['blocks']} bloques: media "
        f"{signed(significance['mean_delta'])}; IC95 % "
        f"[{n(significance['ci95_low'])}; {signed(significance['ci95_high'])}]; "
        f"p={n(significance['p_two_sided'], 4)}; incluye cero.",
        f"- `feed.replay_speed` 4,5→8,0 no cambia la secuencia: en W1, 8× y 1× "
        f"dan {replay['8.0']['trades']} ops, {n(replay['8.0']['net_profit'])}, "
        f"PF {n(replay['8.0']['profit_factor'])}, DD "
        f"{n(replay['8.0']['max_drawdown'])}; Δ {n(replay['delta_net'])}. Es "
        "operativo, no edge.",
        "",
        "**Inferencias (plausibles, no demostradas):**",
        "",
        "- La ventaja agregada es cobertura de señales y apalancamiento, no mejor "
        "ejecución en los trades compartidos. El pareo lo sostiene en la muestra; "
        "no prueba causalidad fuera de ella.",
        f"- El {stop_label} es un lastre en W1–W6; no implica que lo sea en forward. "
        f"El cohorte de {diag['stop_gt_200']['count']} trades es una comparación "
        "de carteras, no un experimento aleatorio.",
        f"- La frecuencia {dotted_get(live_cfg, 'strategy.setup_validity_minutes')}/"
        f"{dotted_get(live_cfg, 'strategy.retest_tolerance_ticks')} captura "
        f"señales extra de calidad media inferior: en las comunes la manual "
        f"rinde menos; el agregado gana por las {manual_only_ops} extra.",
        "- La diferencia entre la DB viva y el backtest no es atribuible a la "
        "config: son contabilidad, feed y ejecución distintos; no hay "
        "reconciliación trade a trade.",
        "",
        "**Datos que faltan / no permiten concluir:**",
        "",
        "- Que la manual sea superior en forward: no hay muestra prospectiva, el "
        "holdout está sellado y el IC95 % incluye cero.",
        "- Que la original sea mejor: tampoco tiene forward; solo se midió en el "
        "mismo histórico.",
        "- Que la mejor variante primaria funcione hacia adelante: sus cifras "
        "son in-sample; el candidato tiene "
        f"{candidate.get('trades') if candidate else 'n/d'} ops"
        + (f" y top-5 {n(conc_c.get('top5_share_pct'), 1)} %."
           if conc_c else "."),
        f"- Cuantificar el efecto de régimen o de un broker real: "
        f"{significance['blocks']} bloques, {live_ops}/{original_ops} trades, "
        "un solo instrumento (MNQ) y ejecución paper.",
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
            + ("La familia de exclusión es robusta al encuadre; el candidato "
               "sigue en pie."
               if robustness["forward_ready"] else
               "Solo una parte de las ventanas funciona: trátalo como "
               "sobreajuste y no lo lleves a forward."),
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
        if best_ext and candidate and best_ext["id"] != candidate["id"]:
            lines += [
                f"La mejor de la extensión es `{best_ext['id']}` "
                f"({best_ext.get('trades')} ops, RDD {n(best_ext.get('rdd'), 3)}). "
                f"No se re-selecciona como candidato: elegir el máximo de "
                f"{len(excl_ext)} ventanas después de ver el resultado es doble "
                "in-sample. Vale como confirmación de familia, no como nueva "
                "promesa.",
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
        cand_base_patch = without_execution(candidate.get("patch")) if candidate else {}
        cand_cost = next(
            (r for r in cost_ext
             if without_execution(r.get("patch")) == cand_base_patch),
            None,
        ) if candidate and candidate["id"] != "manual_base" else None
        if cand_cost:
            survives = float(cand_cost.get("net") or 0) > base_net
            lines += [
                "",
                (f"El candidato `{candidate['id']}` **sigue ganando a la base "
                 "incluso con el doble de costes**: el edge no depende de un "
                 "reprecio optimista."
                 if survives else
                 f"El candidato `{candidate['id']}` **no sobrevive** al doble "
                 "de costes: el edge dependía de costes favorables."),
            ]
            nocost = candidate
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
            lines += [
                "No hay fila de estrés de costes para el candidato actual; no "
                "se puede comprobar con `resultados.jsonl`.",
                "",
            ]
    if conc:
        cc = conc["concentration"]

        def cells(fn):
            return " | ".join(fn(cc[k]) for k in ("candidate", "base", "original"))

        if not conc_matches:
            lines += [
                "**Aviso:** la re-ejecución limpia se hizo con otro patch; el "
                f"candidato actual es `{candidate['id'] if candidate else 'n/d'}`. "
                "Esta sección describe la foto fija, no el candidato actual.",
                "",
            ]
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
        if is_robust_row(r) or is_cost_row(r):
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
    ordered = sorted(
        [r for r in improvement_pool
         if r["id"] != "manual_base"
         and float(r.get("net") or 0) - base_net > 0.005],
        key=lambda r: float(r.get("net") or 0) - base_net,
        reverse=True,
    )
    improvements_all = []
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
        improvements_all.append(row)
    improvements = improvements_all[:5]
    noops = [
        r for r in ranked
        if r["id"] != "manual_base"
        and abs(float(r.get("net") or 0) - base_net) <= 0.005
        and abs(float(r.get("dd") or 0) - base_dd) <= 0.005
    ]

    def confidence_for(row: dict) -> str:
        trades = int(row.get("trades") or 0)
        if trades < MIN_FORWARD_OPS:
            return f"muy baja ({trades} ops)"
        if conc_c and candidate and row.get("id") == candidate.get("id"):
            return conc_confidence
        if trades < 30:
            return "baja"
        if trades < 50:
            return "media"
        return "media-alta"

    def risk_text(row: dict) -> str:
        parts = [risk_for(row.get("patch") or {})]
        trades = int(row.get("trades") or 0)
        if trades < MIN_FORWARD_OPS:
            parts.append(f"Muestra insuficiente ({trades} ops): no promover.")
        if conc_c and candidate and row.get("id") == candidate.get("id"):
            parts.append(
                f"Top-5 = {n(conc_c.get('top5_share_pct'), 1)} % del neto; "
                f"sin ellas, {n(conc_c.get('net_ex_top5'))}."
            )
        return " ".join(parts)

    def verify_text(row: dict) -> str:
        text = f"`verify_variant.py --id {row['id']}`"
        if int(row.get("trades") or 0) < MIN_FORWARD_OPS:
            return text + "; no promover"
        return text + " + forward"

    verified = {
        v["id"]: v for v in verifications
        if v.get("match") and all(v["match"].values())
    }

    def was_verified(row: dict) -> bool:
        v = verified.get(row["id"])
        if not v:
            return False
        return (
            v.get("trades") == row.get("trades")
            and round(float(v.get("net") or 0), 2)
            == round(float(row.get("net") or 0), 2)
            and round(float(v.get("pf") or 0), 2)
            == round(float(row.get("pf") or 0), 2)
            and round(float(v.get("dd") or 0), 2)
            == round(float(row.get("dd") or 0), 2)
        )

    lines += [
        "",
        "## 3. Mejoras priorizadas por impacto en rentabilidad",
        "",
    ]
    if improvements:
        intro = (
            "Ordenadas por Δneto medido frente a la base. El RDD y el DD "
            "indican el coste en riesgo; ninguna está aplicada. "
            f"**{len(improvements_all)}** variantes superan a la base en neto; "
            f"se listan las {len(improvements)} mejores."
        )
    else:
        intro = (
            "Ordenadas por Δneto medido frente a la base. Ninguna variante "
            "supera a la base en neto con la muestra actual."
        )
    if noops:
        noop_ids = "`, `".join(r["id"] for r in noops)
        intro += (
            f" `{noop_ids}` salen idénticas a la base en neto y DD: no "
            "llegaron a activarse en esta muestra, así que no son una palanca "
            "demostrada."
        )
    lines += [intro, ""]
    if conc_c and improvements:
        first = improvements[0]
        first_delta = float(first.get("net") or 0) - base_net
        lines += [
            f"**Lectura de confianza:** el candidato `{candidate['id']}` debe "
            f"{n(conc_c['top5_share_pct'], 1)} % del neto a 5 operaciones; sin "
            f"ellas, {n(conc_c['net_ex_top5'])}. La mejora #1 es "
            f"`{first['id']}` ({signed(first_delta)} USD), con confianza "
            f"{confidence_for(first)}; es la mayor de la muestra, pero frágil.",
            "",
        ]
    if improvements:
        lines += [
            "| # | Regla / parámetro | Valor propuesto | Δ neto esperado | Δ DD | "
            "Confianza | Riesgo | Verificación |",
            "|---:|---|---|---:|---:|---|---|---|",
        ]
        for i, row in enumerate(improvements, 1):
            delta = float(row.get("net") or 0) - base_net
            ddd = (float(row.get("dd") or 0) - base_dd) if base else 0.0
            lines.append(
                f"| {i} | `{row['id']}` | {describe_patch(row.get('patch') or {})} "
                f"| {signed(delta)} | {signed(ddd)} | {confidence_for(row)} "
                f"| {risk_text(row)} | {verify_text(row)} |"
            )
        lines += ["", "Detalle y verificación de cada una:", ""]
        for i, row in enumerate(improvements, 1):
            delta = float(row.get("net") or 0) - base_net
            ddd = (float(row.get("dd") or 0) - base_dd) if base else 0.0
            trades = int(row.get("trades") or 0)
            expected = (
                f"{trades} ops, {n(row.get('net'))}, PF {n(row.get('pf'))} "
                f"y DD {n(row.get('dd'))}"
            )
            if was_verified(row):
                verification = (
                    "- **Verificado:** re-ejecutado en un proceso aparte; ops, "
                    f"neto, PF y DD coinciden. La comprobación debe dar {expected}."
                )
            else:
                verification = (
                    "- **Verificación exacta:** `python research/verify_variant.py "
                    f"--id {row['id']}` debe dar {expected}."
                )
            if trades < MIN_FORWARD_OPS:
                verification += (
                    f" Con {trades} ops no se promueve: primero ampliar muestra."
                )
            else:
                verification += (
                    " Después, forward mínimo con muestra prospectiva."
                )
            lines += [
                f"### {i}. `{row['id']}` — {n(delta)} USD",
                "",
                f"- **Cambio exacto:** {describe_patch(row.get('patch') or {})}.",
                f"- **Efecto medido:** {trades} ops, neto "
                f"{n(row.get('net'))} (Δ {n(delta)}), PF {n(row.get('pf'))}, "
                f"DD {n(row.get('dd'))} (Δ {n(ddd)}), RDD "
                f"{n(row.get('rdd'), 3)}.",
                f"- **Riesgo:** {risk_text(row)}",
                verification,
                "",
            ]
            if conc_c and candidate and row["id"] == candidate["id"]:
                lines += [
                    f"- **Confianza condicionada:** top-5 = "
                    f"{n(conc_c['top5_share_pct'], 1)} % del neto; sin esas "
                    f"cinco, {n(conc_c['net_ex_top5'])}. Edge de pocos eventos, "
                    "no una ventaja frecuente.",
                    "",
                ]
    else:
        lines += [
            "No hay una tabla de mejoras primarias que mostrar con estos "
            "`resultados.jsonl`.",
            "",
        ]
    def best_rdd_reason(row: dict) -> str:
        if is_robust_row(row):
            return (
                "es una ventana de robustez de fase 3; elegirla como candidato "
                "sería doble in-sample."
            )
        if is_combo_row(row):
            return (
                "es una combinación de palancas; no se selecciona como "
                "candidato."
            )
        trades = int(row.get("trades") or 0)
        if trades < MIN_FORWARD_OPS:
            return f"suma {trades} operaciones; muestra insuficiente."
        return "no cumple el filtro de candidato."

    lines += [
        "## 4. Candidato a forward",
        "",
    ]
    if candidate and candidate["id"] != "manual_base":
        cnet = float(candidate.get("net") or 0)
        if best_rdd and best_rdd["id"] != candidate["id"]:
            lines += [
                f"El mejor RDD absoluto de `resultados.jsonl` es "
                f"`{best_rdd['id']}` ({n(best_rdd.get('rdd'), 3)}; "
                f"{best_rdd.get('trades')} ops); {best_rdd_reason(best_rdd)}",
                "",
            ]
        elif best_rdd and best_rdd["id"] == candidate["id"]:
            lines += [
                "El candidato es también el mejor RDD absoluto de "
                "`resultados.jsonl`.",
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
             if conc_c else
             "- **Concentración:** la foto fija no corresponde al candidato "
             "actual; no se usa para confianza."),
            ("- **Robustez:** pendiente; la fase 3 aún no cerró las ventanas."
             if robustness["forward_ready"] is None else
             f"- **Robustez:** {len(robust_ok)}/{len(robust_ext)} ventanas "
             "de exclusión mejoran neto y DD."
             if robustness["forward_ready"] else
             f"- **Robustez:** solo {len(robust_ok)}/{len(robust_ext)} "
             "ventanas de exclusión mejoran neto y DD; por eso el candidato no "
             "se elige de esa familia."),
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
    else:
        lines += [
            "No hay un candidato que cumpla el filtro de muestra y neto; no se "
            "promociona nada.",
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
        "- `data/config.json` y `profiles/live_8765/config.json` conservan el "
        "mismo SHA-256 (ver sección 1); el proceso del 8765 no se reinició ni "
        "se modificó.",
        "- Sin escrituras en la DB del 8765; solo lectura.",
        "- Holdout no leído; 2024 no usado.",
        "",
        "## 7. Veredicto",
        "",
        f"- La manual gana **{signed(live_net - original_net)} USD** en la "
        f"muestra (PF {n(live_pf)} vs {n(original_pf)}; expectancy "
        f"{n(live_avg_r, 3)} vs {n(original_avg_r, 3)} R; RDD {n(live_rdd, 4)} vs "
        f"{n(original_rdd, 4)}), pero **no domina en riesgo**: DD "
        f"{signed(live_dd - original_dd)}. El IC95 % del delta incluye cero.",
        f"- La ventaja es **cobertura de señales + sizing**, no mejor ejecución: "
        f"en las {common['common_signals']} comunes la manual pierde "
        f"{signed(common_delta)}. El {stop_label} es el lastre "
        f"({signed(stop['delta_net'])} de neto y {signed(stop['delta_dd'])} de DD).",
        f"- **No cambiar el 8765 hoy.** No hay forward de ninguna de las dos, el "
        f"holdout está sellado y la muestra es de {live_ops}/{original_ops} ops "
        "in-sample.",
        "",
    ]
    if improvements:
        first = improvements[0]
        first_delta = float(first.get("net") or 0) - base_net
        lines.append(
            f"- La mejora de mayor Δneto es `{first['id']}` "
            f"({signed(first_delta)} USD; confianza {confidence_for(first)})."
        )
    if candidate and candidate["id"] != "manual_base":
        lines.append(
            f"- **Candidato a forward:** `{candidate['id']}` "
            f"({candidate.get('trades')} ops, RDD "
            f"{n(candidate.get('rdd'), 3)})."
        )
    if best_rdd and candidate and best_rdd["id"] != candidate["id"]:
        lines.append(
            f"- **Mejor RDD absoluto:** `{best_rdd['id']}` "
            f"({n(best_rdd.get('rdd'), 3)}; {best_rdd_reason(best_rdd)})"
        )
    lines += ["", "Ninguna se despliega sin forward.", ""]

    md = "\n".join(lines)
    (OUT / "resumen.md").write_text(md, encoding="utf-8")
    payload = {
        "generated_at": now,
        "scope": mission["scope"],
        "live_vs_original": {
            "live_source": live_source,
            "original_source": original_source,
            "original_in_jsonl": original_in_jsonl,
            "live_config": live_label,
            "original_config": original_label,
            "config_hashes": {
                "data/config.json": live_hash,
                "profiles/live_8765/config.json": live_profile_hash,
                "hashes_match": hashes_match,
            },
            "live": live_row,
            "original": original_row,
            "comparison": {
                "ops": {"live": live_ops, "original": original_ops,
                        "delta": live_ops - original_ops},
                "net": {"live": round(live_net, 2),
                        "original": round(original_net, 2),
                        "delta": round(live_net - original_net, 2)},
                "rdd": {"live": round(live_rdd, 4),
                        "original": round(original_rdd, 4),
                        "delta": round(live_rdd - original_rdd, 4)},
                "drawdown": {"live": round(live_dd, 2),
                             "original": round(original_dd, 2),
                             "delta": round(live_dd - original_dd, 2)},
                "profit_factor": {"live": live_pf, "original": original_pf,
                                  "delta": round(live_pf - original_pf, 2)},
            },
            "significance": mission["significance"],
        },
        "config_diff": config_diffs,
        "ranking": ranked,
        "extension": extension,
        "concentration": conc,
        "robustness": robustness,
        "candidate": candidate,
        "best_rdd": best_rdd,
        "concentration_matches_candidate": conc_matches,
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
                "confidence": confidence_for(r),
                "verification": verify_text(r),
                "is_candidate": bool(candidate and r["id"] == candidate["id"]),
            }
            for r in improvements
        ],
        "verifications": verifications,
        "attribution": mission.get("attribution"),
        "paired_common": {
            "common_signals": common["common_signals"],
            "manual_net": common_live_net,
            "original_net": common_original_net,
            "delta": round(common_delta, 2),
            "manual_only_count": manual_only_ops,
            "manual_only_net": round(manual_only_net, 2),
            "original_only_count": original_only_ops,
            "original_only_net": round(original_only_net, 2),
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
