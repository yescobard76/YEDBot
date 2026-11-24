"""Evaluador read-only de gates historicos del filtro min_stop_or_ratio=0.25.

La entrada son dos artefactos ya generados:

- ``reports/backtest/_manual_filter025_w1_w6.json``: 17 trades aceptados.
- ``reports/backtest/p2_w1_w6_confirm.json``: 46 trades baseline P2.

No ejecuta backtests, no carga barras, no modifica DB/configuración y no lee el
holdout. Solo comprueba la partición, agrega los trades existentes y evalúa las
puertas recalibradas definidas en ``filter025_gates.config.json``.

La diferencia deliberada con las puertas forward originales es que los bloques
vacíos no son neutrales: la cobertura se evalúa como una puerta propia, y el
bootstrap no puede aprobar sin muestra y cobertura mínimas.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("filter025_gates.config.json")
DEFAULT_OUTPUT = Path(__file__).with_name("filter025_gates.json")


# --------------------------------------------------------------------------- IO
def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} no contiene un objeto JSON")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_safe(value: Any) -> Any:
    """Convierte inf/nan en texto para que el JSON sea estricto."""
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


# --------------------------------------------------------------------- helpers
def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile / 100.0
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _pf_r(trades: list[dict[str, Any]]) -> float | None:
    gross_profit = sum(float(t["r_multiple"]) for t in trades if float(t["r_multiple"]) > 0)
    gross_loss = -sum(float(t["r_multiple"]) for t in trades if float(t["r_multiple"]) < 0)
    if not trades:
        return None
    if gross_loss == 0:
        return float("inf") if gross_profit else None
    return gross_profit / gross_loss


def _pf_usd(trades: list[dict[str, Any]]) -> float | None:
    gross_profit = sum(float(t["pnl"]) for t in trades if float(t["pnl"]) > 0)
    gross_loss = -sum(float(t["pnl"]) for t in trades if float(t["pnl"]) < 0)
    if not trades:
        return None
    if gross_loss == 0:
        return float("inf") if gross_profit else None
    return gross_profit / gross_loss


def _max_drawdown_r(trades: list[dict[str, Any]]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for trade in sorted(trades, key=lambda item: int(item["entry_ts"])):
        equity += float(trade["r_multiple"])
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _max_drawdown_usd(trades: list[dict[str, Any]]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for trade in sorted(trades, key=lambda item: int(item["entry_ts"])):
        equity += float(trade["pnl"])
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _worst_loss_streak(trades: list[dict[str, Any]]) -> int:
    current = 0
    worst = 0
    for trade in sorted(trades, key=lambda item: int(item["entry_ts"])):
        if float(trade["pnl"]) < 0:
            current += 1
            worst = max(worst, current)
        else:
            current = 0
    return worst


def _et_date(ts: int) -> date:
    # Las sesiones del artefacto son RTH de EE. UU.; UTC y ET coinciden en fecha.
    return datetime.fromtimestamp(ts, timezone.utc).date()


def _quarter_label(iso_date: str) -> str:
    parsed = date.fromisoformat(iso_date[:10])
    return f"{parsed.year}-Q{(parsed.month - 1) // 3 + 1}"


def _month_key(ts: int) -> str:
    return _et_date(ts).strftime("%Y-%m")


def _months_between(start: date, end: date) -> list[str]:
    current = date(start.year, start.month, 1)
    out: list[str] = []
    while current <= date(end.year, end.month, 1):
        out.append(current.strftime("%Y-%m"))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return out


def _gate(
    gate_id: str,
    family: str,
    title: str,
    state: str,
    reason: str,
    threshold: str,
    values: dict[str, Any],
    *,
    legacy_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": gate_id,
        "legacy_id": legacy_id,
        "family": family,
        "title": title,
        "state": state,
        "reason": reason,
        "threshold": threshold,
        "values": values,
    }


def _signal_id(trade: dict[str, Any]) -> str:
    signal_id = (trade.get("meta") or {}).get("signal_id")
    if not signal_id:
        raise ValueError(f"Trade sin signal_id: {trade.get('id')}")
    return str(signal_id)


def _signature(trade: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _signal_id(trade),
        int(trade["entry_ts"]),
        int(trade["exit_ts"]),
        trade["direction"],
        int(trade["qty"]),
        round(float(trade["entry_price"]), 4),
        round(float(trade["exit_price"]), 4),
        round(float(trade["pnl"]), 2),
        trade["exit_reason"],
    )


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "trades": len(trades),
        "net": round(sum(float(t["pnl"]) for t in trades), 2),
        "pf_usd": _pf_usd(trades),
        "sum_r": round(sum(float(t["r_multiple"]) for t in trades), 4),
        "mean_r": round(_mean([float(t["r_multiple"]) for t in trades]), 4)
        if trades
        else None,
        "pf_r": _pf_r(trades),
        "dd_r": round(_max_drawdown_r(trades), 4),
        "dd_usd": round(_max_drawdown_usd(trades), 2),
        "worst_loss_streak": _worst_loss_streak(trades),
        "shorts": sum(t["direction"] == "short" for t in trades),
        "longs": sum(t["direction"] == "long" for t in trades),
    }


# ------------------------------------------------------------------- evaluate
def evaluate(
    config_path: Path | str = DEFAULT_CONFIG,
    *,
    write: bool = False,
    output_path: Path | str = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    config_path = Path(config_path)
    config = _load_json(config_path)
    if config.get("schema") != "filter025-gates-config-v1":
        raise ValueError("Schema de configuracion de gates no reconocido")

    filter_path = ROOT / config["inputs"]["filter_artifact"]
    baseline_path = ROOT / config["inputs"]["baseline_artifact"]
    filter_payload = _load_json(filter_path)
    baseline_payload = _load_json(baseline_path)
    filter_variant = config["inputs"]["filter_variant"]
    baseline_variant = config["inputs"]["baseline_variant"]

    if float(filter_payload.get("filter_threshold", -1)) != float(config["filter_threshold"]):
        raise ValueError("El artefacto no corresponde al umbral 0.25 congelado")
    if filter_payload.get("invariant_max10_eq_max5") is not True:
        raise ValueError("El artefacto no declara la invariancia max10=max5")

    filter_windows = filter_payload.get("windows") or []
    baseline_windows = baseline_payload.get("windows") or []
    filter_ids = [item["window"] for item in filter_windows]
    baseline_ids = [item["window"] for item in baseline_windows]
    if filter_ids != baseline_ids or len(filter_ids) != 6:
        raise ValueError("Los artefactos no contienen las mismas seis ventanas W1-W6")

    accepted_by_window: dict[str, list[dict[str, Any]]] = {}
    baseline_by_window: dict[str, list[dict[str, Any]]] = {}
    for filter_window, baseline_window in zip(filter_windows, baseline_windows):
        window_id = filter_window["window"]
        accepted = filter_window["variants"][filter_variant]["trades"]
        baseline = baseline_window["variants"][baseline_variant]["trades"]
        accepted_by_window[window_id] = accepted
        baseline_by_window[window_id] = baseline

    accepted = [t for window in filter_ids for t in accepted_by_window[window]]
    baseline = [t for window in filter_ids for t in baseline_by_window[window]]
    accepted_ids = [_signal_id(t) for t in accepted]
    baseline_ids_trades = [_signal_id(t) for t in baseline]
    if len(accepted_ids) != len(set(accepted_ids)):
        raise ValueError("Hay signal_id duplicados en el cohorte aceptado")
    if len(baseline_ids_trades) != len(set(baseline_ids_trades)):
        raise ValueError("Hay signal_id duplicados en el baseline")
    if not set(accepted_ids).issubset(set(baseline_ids_trades)):
        raise ValueError("El cohorte aceptado no es un subconjunto del baseline")
    rejected = [t for t in baseline if _signal_id(t) not in set(accepted_ids)]
    if len(accepted) + len(rejected) != len(baseline):
        raise ValueError("La particion aceptados/rechazados no cubre el baseline")

    # Verifica que los dos brazos del filtro sean economicamente identicos.
    other_variant = "filter025_max10" if filter_variant == "filter025_max5" else "filter025_max5"
    other = [t for item in filter_windows for t in item["variants"][other_variant]["trades"]]
    if len(other) != len(accepted) or [_signature(t) for t in other] != [_signature(t) for t in accepted]:
        raise ValueError("Los brazos max10/max5 no son identicos; no se puede usar el artefacto")

    # Comprueba el alcance sin abrir ningun fichero de holdout.
    starts = [date.fromisoformat(item["start"][:10]) for item in filter_windows]
    ends = [date.fromisoformat(item["last"][:10]) for item in filter_windows]
    scope_start, scope_end = min(starts), max(ends)
    outside_scope = [
        _signal_id(t)
        for t in baseline
        if not (scope_start <= _et_date(int(t["entry_ts"])) <= scope_end)
    ]
    holdout_dates = [
        _signal_id(t)
        for t in baseline
        if _et_date(int(t["entry_ts"])) > date(2026, 6, 30)
    ]

    acc_stats = _metrics(accepted)
    base_stats = _metrics(baseline)
    rej_stats = _metrics(rejected)

    # ------------------------------------------------------------- block data
    blocks: list[dict[str, Any]] = []
    for item in filter_windows:
        window_id = item["window"]
        acc = accepted_by_window[window_id]
        base = baseline_by_window[window_id]
        rej = [t for t in base if _signal_id(t) not in set(accepted_ids)]
        block = {
            "id": window_id,
            "quarter": _quarter_label(item["start"]),
            "start": item["start"][:10],
            "end": item["last"][:10],
            "accepted": len(acc),
            "baseline": len(base),
            "rejected": len(rej),
            "accepted_net": round(sum(float(t["pnl"]) for t in acc), 2),
            "accepted_r": round(sum(float(t["r_multiple"]) for t in acc), 4),
            "rejected_r": round(sum(float(t["r_multiple"]) for t in rej), 4),
            "accepted_pf": _pf_usd(acc),
            "baseline_pf": _pf_usd(base),
            "rejected_pf": _pf_usd(rej),
            "empty_accepted": len(acc) == 0,
            "empty_rejected": len(rej) == 0,
        }
        blocks.append(block)

    active_blocks = [b for b in blocks if b["accepted"] > 0]
    active_quarters = len(active_blocks)
    positive_active = [b for b in active_blocks if b["accepted_r"] > 0]
    positive_share = len(positive_active) / active_quarters if active_quarters else 0.0
    worst_active_r = min((b["accepted_r"] for b in active_blocks), default=0.0)
    quarter_net = sorted(
        ((b["quarter"], b["accepted_net"]) for b in active_blocks),
        key=lambda item: item[1],
        reverse=True,
    )
    top2_net = sum(value for _, value in quarter_net[:2])
    top2_share = top2_net / acc_stats["net"] * 100.0 if acc_stats["net"] > 0 else None

    rejected_passes = sum(1 for b in blocks if not b["empty_rejected"] and b["rejected_r"] <= 0)
    rejected_empty = [b["id"] for b in blocks if b["empty_rejected"]]

    # Umbral de bloque dinamico: no puede ser inerte por construccion.
    block_pf_min = max(
        int(config["quarterly"]["min_block_pf_trades"]),
        math.ceil(len(accepted) / 6) if accepted else int(config["quarterly"]["min_block_pf_trades"]),
    )
    eligible_pf_blocks = [b for b in blocks if b["accepted"] >= block_pf_min]
    bad_pf_blocks = [
        b
        for b in eligible_pf_blocks
        if b["accepted_pf"] is not None and b["accepted_pf"] < float(config["quarterly"]["min_block_pf"])
    ]
    block_pf_state = (
        "INCONCLUSO"
        if not eligible_pf_blocks
        else "PASS"
        if not bad_pf_blocks
        else "FALLA"
    )
    min_eligible_pf = min(
        (b["accepted_pf"] for b in eligible_pf_blocks if b["accepted_pf"] is not None),
        default=None,
    )

    # G7 historico, solo para demostrar el agujero que corrige la recalibracion.
    old_g7_above = sum(
        1 for b in blocks if b["accepted_pf"] is not None and b["accepted_pf"] > 1
    )
    old_g7_bad = [b for b in blocks if b["baseline"] >= 15 and b["accepted_pf"] is not None and b["accepted_pf"] < 0.70]
    old_g7_state = "PASS" if old_g7_above >= 4 and not old_g7_bad else "FALLA"
    empty_block_ids = [b["id"] for b in blocks if b["empty_accepted"]]
    max_block_trades = max((b["accepted"] for b in blocks), default=0)
    old_min_reachable = any(b["baseline"] >= 15 for b in blocks)

    # ------------------------------------------------------------ monthly gate
    accepted_months = sorted({_month_key(int(t["entry_ts"])) for t in accepted})
    all_months = _months_between(scope_start, scope_end)
    zero_months = [month for month in all_months if month not in accepted_months]
    max_zero_run = 0
    current_run = 0
    for month in all_months:
        if month in accepted_months:
            current_run = 0
        else:
            current_run += 1
            max_zero_run = max(max_zero_run, current_run)

    # -------------------------------------------------------------- bootstrap
    session_groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"accepted": [], "rejected": []})
    accepted_set = set(accepted_ids)
    for trade in baseline:
        key = _et_date(int(trade["entry_ts"])).isoformat()
        group = "accepted" if _signal_id(trade) in accepted_set else "rejected"
        session_groups[key][group].append(float(trade["r_multiple"]))

    bootstrap_config = config["bootstrap"]
    rng = random.Random(int(bootstrap_config["seed"]))
    sessions = list(session_groups.values())
    deltas: list[float] = []
    invalid = 0
    for _ in range(int(bootstrap_config["resamples"])):
        sample = [sessions[rng.randrange(len(sessions))] for _ in range(len(sessions))]
        a = [value for item in sample for value in item["accepted"]]
        r = [value for item in sample for value in item["rejected"]]
        if not a or not r:
            invalid += 1
            continue
        deltas.append(_mean(a) - _mean(r))  # type: ignore[operator]
    lower = _percentile(deltas, (100.0 - float(bootstrap_config["confidence_pct"])) / 2.0)
    upper = _percentile(deltas, 100.0 - (100.0 - float(bootstrap_config["confidence_pct"])) / 2.0)
    p_value = (1 + sum(value <= 0 for value in deltas)) / (len(deltas) + 1) if deltas else None
    observed_delta = (_mean([float(t["r_multiple"]) for t in accepted]) or 0.0) - (
        _mean([float(t["r_multiple"]) for t in rejected]) or 0.0
    )
    valid_reps_ok = len(deltas) >= int(bootstrap_config["min_valid_resamples"])
    bootstrap_sample_ok = (
        len(accepted) >= int(bootstrap_config["min_accepted"])
        and len(rejected) >= int(bootstrap_config["min_rejected"])
    )
    bootstrap_coverage_ok = active_quarters >= int(bootstrap_config["min_active_quarters"])
    numeric_bootstrap_ok = lower is not None and lower > 0
    if not valid_reps_ok or not bootstrap_sample_ok or not bootstrap_coverage_ok:
        e2_state = "INCONCLUSO"
    elif numeric_bootstrap_ok:
        e2_state = "PASS"
    elif upper is not None and upper < 0:
        e2_state = "FALLA"
    else:
        e2_state = "INCONCLUSO"

    # ---------------------------------------------------------- target metrics
    top3_r = sorted((float(t["r_multiple"]) for t in accepted), reverse=True)[:3]
    drop_best3_r = sum(float(t["r_multiple"]) for t in accepted) - sum(top3_r)
    monthly_r: dict[str, float] = defaultdict(float)
    monthly_pnl: dict[str, float] = defaultdict(float)
    for trade in accepted:
        key = _month_key(int(trade["exit_ts"]))
        monthly_r[key] += float(trade["r_multiple"])
        monthly_pnl[key] += float(trade["pnl"])
    best_month = max(monthly_r, key=monthly_r.get) if monthly_r else None
    best_month_r = monthly_r[best_month] if best_month else 0.0
    drop_best_month_r = sum(float(t["r_multiple"]) for t in accepted) - best_month_r
    gross_positive_r = sum(float(t["r_multiple"]) for t in accepted if float(t["r_multiple"]) > 0)
    top_trade_r = max((float(t["r_multiple"]) for t in accepted), default=0.0)
    top_trade_share = top_trade_r / gross_positive_r * 100.0 if gross_positive_r else None
    top5_pnl = sorted((float(t["pnl"]) for t in accepted), reverse=True)[:5]
    top5_share_gross = (
        sum(top5_pnl) / sum(float(t["pnl"]) for t in accepted if float(t["pnl"]) > 0) * 100.0
        if acc_stats["net"] > 0
        else None
    )

    # Coste aproximado solo diagnostico; no se convierte en PASS sin reprecio.
    stress_net = 0.0
    stress_pnls: list[float] = []
    for trade in accepted:
        qty = int(trade["qty"])
        extra = (1.24 - 0.62) * 2 * qty + qty * 1.0
        stress_value = float(trade["pnl"]) - extra
        stress_pnls.append(stress_value)
        stress_net += stress_value
    stress_positive = sum(value for value in stress_pnls if value > 0)
    stress_negative = -sum(value for value in stress_pnls if value < 0)
    stress_pf = stress_positive / stress_negative if stress_negative else None
    stress_mean_r = stress_net / len(accepted) / max(
        (_mean([float(t["risk_amount"]) for t in accepted]) or 1.0), 1.0
    ) if accepted else None

    # ------------------------------------------------------------------ gates
    gates: list[dict[str, Any]] = [
        _gate(
            "I1_SCOPE",
            "I",
            "Alcance historico y holdout sellado",
            "PASS" if not outside_scope and not holdout_dates else "FALLA",
            (
                "Los 46 trades pertenecen a W1-W6; no se abrio ningun fichero del holdout."
                if not outside_scope and not holdout_dates
                else "Hay trades fuera de W1-W6 o posteriores al 2026-06-30."
            ),
            "cero trades fuera de W1-W6 y cero lectura de holdout",
            {
                "outside_scope": len(outside_scope),
                "holdout_dates": len(holdout_dates),
                "holdout_read": False,
                "scope_start": scope_start.isoformat(),
                "scope_end": scope_end.isoformat(),
            },
        ),
        _gate(
            "I2_PARTITION",
            "I",
            "Particion aceptados/rechazados",
            "PASS" if len(accepted) + len(rejected) == len(baseline) else "FALLA",
            "Aceptados + rechazados = baseline; signal_id unicos y subconjunto verificado.",
            "17 + 29 = 46 y umbral 0,25 congelado",
            {
                "accepted": len(accepted),
                "rejected": len(rejected),
                "baseline": len(baseline),
                "filter_threshold": filter_payload.get("filter_threshold"),
            },
        ),
        _gate(
            "S0_TOTAL_SAMPLE",
            "S",
            "Muestra total y por direccion",
            "PASS"
            if len(accepted) >= int(config["sample"]["min_total_trades"])
            and acc_stats["longs"] >= int(config["sample"]["min_per_direction"])
            and acc_stats["shorts"] >= int(config["sample"]["min_per_direction"])
            else "INCONCLUSO",
            (
                f"{len(accepted)} trades y {acc_stats['longs']}/{acc_stats['shorts']} largos/cortos: "
                f"no alcanza {config['sample']['min_total_trades']} totales ni "
                f"{config['sample']['min_per_direction']} por direccion. No se rebaja el minimo."
            ),
            f">= {config['sample']['min_total_trades']} totales y >= {config['sample']['min_per_direction']}/direccion",
            {
                "trades": len(accepted),
                "longs": acc_stats["longs"],
                "shorts": acc_stats["shorts"],
            },
            legacy_id="G4",
        ),
        _gate(
            "S2_BASELINE",
            "S",
            "Baseline forward",
            "PASS" if len(baseline) >= int(config["sample"]["min_baseline_trades"]) else "INCONCLUSO",
            f"Baseline de {len(baseline)} trades; el minimo forward es {config['sample']['min_baseline_trades']}.",
            f">= {config['sample']['min_baseline_trades']} trades baseline",
            {"baseline": len(baseline)},
        ),
        _gate(
            "S3_COHORT",
            "S",
            "Tamaño de cohortes",
            "PASS" if len(accepted) >= int(config["sample"]["min_accepted"]) and len(rejected) >= int(config["sample"]["min_rejected"]) else "INCONCLUSO",
            (
                f"{len(accepted)} aceptados y {len(rejected)} rechazados; "
                f"se exigen {config['sample']['min_accepted']} y {config['sample']['min_rejected']}."
            ),
            f">= {config['sample']['min_accepted']} aceptados y >= {config['sample']['min_rejected']} rechazados",
            {"accepted": len(accepted), "rejected": len(rejected)},
        ),
        _gate(
            "S4_BLOCK_SAMPLE",
            "S",
            "Muestra por bloque",
            "PASS"
            if sum(
                1
                for b in blocks
                if b["baseline"] >= int(config["sample"]["block_min_trades"])
                and b["accepted"] >= int(config["sample"]["block_min_accepted"])
            )
            >= int(config["sample"]["min_blocks_with_sample"])
            else "INCONCLUSO",
            (
                f"Solo {sum(1 for b in blocks if b['baseline'] >= int(config['sample']['block_min_trades']) and b['accepted'] >= int(config['sample']['block_min_accepted']))}/6 bloques "
                f"tienen baseline >= {config['sample']['block_min_trades']} y aceptadas >= {config['sample']['block_min_accepted']}; "
                f"se exigen {config['sample']['min_blocks_with_sample']}/6."
            ),
            f">= {config['sample']['min_blocks_with_sample']}/6 bloques con baseline >= {config['sample']['block_min_trades']} y aceptadas >= {config['sample']['block_min_accepted']}",
            {
                "qualifying_blocks": sum(
                    1
                    for b in blocks
                    if b["baseline"] >= int(config["sample"]["block_min_trades"])
                    and b["accepted"] >= int(config["sample"]["block_min_accepted"])
                ),
                "blocks": [
                    {
                        "id": b["id"],
                        "baseline": b["baseline"],
                        "accepted": b["accepted"],
                    }
                    for b in blocks
                ],
            },
        ),
        _gate(
            "S5_SHORT_PARTICIPATION",
            "S",
            "Participacion de cortos",
            "PASS" if len([t for t in accepted if t["direction"] == "short"]) >= int(config["sample"]["min_short_accepted"]) else "INCONCLUSO",
            f"{acc_stats['shorts']} cortos aceptados; minimo de participacion {config['sample']['min_short_accepted']}.",
            f">= {config['sample']['min_short_accepted']} cortos aceptados",
            {"shorts": acc_stats["shorts"]},
        ),
        _gate(
            "E1_SELECTION",
            "E",
            "Diferencia de seleccion",
            "PASS" if observed_delta >= 0.25 else "FALLA",
            f"Delta aceptados-rechazados = {observed_delta:.4f} R; umbral +0,25 R.",
            "delta_sel >= +0,25 R",
            {
                "delta_sel": round(observed_delta, 4),
                "mean_accepted_r": acc_stats["mean_r"],
                "mean_rejected_r": rej_stats["mean_r"],
            },
        ),
        _gate(
            "E2_BOOTSTRAP",
            "E",
            "Bootstrap por sesion con precondiciones",
            e2_state,
            (
                (
                    f"IC95% [{lower:.4f}, {upper:.4f}] R, p={p_value:.4f}, {len(deltas)} replicas validas; "
                    if lower is not None and upper is not None and p_value is not None
                    else "Bootstrap sin replicas validas; "
                )
                + (
                    f"muestra {len(accepted)}/{len(rejected)} (min 24/30) y cobertura {active_quarters}/6 "
                    f"(min {config['bootstrap']['min_active_quarters']}/6): el bootstrap no puede dar PASS."
                    if not (bootstrap_sample_ok and bootstrap_coverage_ok and valid_reps_ok)
                    else "precondiciones de muestra/cobertura cumplidas."
                )
            ),
            "IC95% inferior > 0, >= 24 aceptados, >= 30 rechazados, >= 5/6 trimestres y >= 9.500 replicas",
            {
                "delta_sel": round(observed_delta, 4),
                "ci_lower": round(lower, 4) if lower is not None else None,
                "ci_upper": round(upper, 4) if upper is not None else None,
                "p_value": round(p_value, 5) if p_value is not None else None,
                "valid_resamples": len(deltas),
                "invalid_resamples": invalid,
                "numeric_ci_lower_positive": numeric_bootstrap_ok,
                "sample_ok": bootstrap_sample_ok,
                "coverage_ok": bootstrap_coverage_ok,
                "min_valid_resamples_ok": valid_reps_ok,
            },
            legacy_id="E2",
        ),
        _gate(
            "E3_MEAN_R",
            "E",
            "Media R aceptada",
            "PASS" if (acc_stats["mean_r"] or 0) >= 0.20 else "FALLA",
            f"Media R aceptada = {acc_stats['mean_r']}; umbral +0,20 R.",
            "mean_r_accepted >= +0,20 R",
            {"mean_r_accepted": acc_stats["mean_r"]},
        ),
        _gate(
            "P1_REJECTED_R",
            "P",
            "R total del cohorte rechazado",
            "PASS" if rej_stats["sum_r"] <= 0 else "FALLA",
            f"R total rechazado = {rej_stats['sum_r']}; debe ser <= 0.",
            "sum_r_rejected <= 0",
            {"sum_r_rejected": rej_stats["sum_r"], "net_rejected": rej_stats["net"]},
        ),
        _gate(
            "P2_PF_R",
            "P",
            "Profit factor en R",
            "PASS" if (acc_stats["pf_r"] or 0) >= 1.25 else "FALLA",
            f"PF-R aceptado = {acc_stats['pf_r']:.4f}; minimo 1,25.",
            "PF_R_accepted >= 1,25",
            {"pf_r_accepted": acc_stats["pf_r"]},
        ),
        _gate(
            "P3_DRAWDOWN",
            "P",
            "Drawdown",
            "PASS"
            if acc_stats["dd_r"] <= min(8.0, base_stats["dd_r"])
            and acc_stats["dd_usd"] <= min(2000.0, base_stats["dd_usd"])
            else "FALLA",
            (
                f"DD-R {acc_stats['dd_r']:.4f} vs limite {min(8.0, base_stats['dd_r']):.4f}; "
                f"DD-USD {acc_stats['dd_usd']:.2f} vs limite {min(2000.0, base_stats['dd_usd']):.2f}."
            ),
            "DD_R <= min(8R, baseline) y DD_USD <= min(2.000, baseline)",
            {
                "dd_r": acc_stats["dd_r"],
                "baseline_dd_r": base_stats["dd_r"],
                "dd_usd": acc_stats["dd_usd"],
                "baseline_dd_usd": base_stats["dd_usd"],
            },
        ),
        _gate(
            "Q1_QUARTER_COVERAGE",
            "Q",
            "Cobertura trimestral",
            "PASS" if active_quarters >= int(config["quarterly"]["min_active_quarters"]) else "FALLA",
            (
                f"{active_quarters}/6 trimestres con al menos un aceptado; "
                f"se exigen {config['quarterly']['min_active_quarters']}/6. "
                f"Bloques vacios: {', '.join(empty_block_ids) or 'ninguno'}. "
                "Un bloque vacio no cuenta como pase neutral."
            ),
            f">= {config['quarterly']['min_active_quarters']}/6 trimestres con aceptados",
            {
                "active_quarters": active_quarters,
                "empty_blocks": empty_block_ids,
                "blocks": [
                    {
                        "id": b["id"],
                        "quarter": b["quarter"],
                        "accepted": b["accepted"],
                        "rejected": b["rejected"],
                        "accepted_net": b["accepted_net"],
                        "accepted_r": b["accepted_r"],
                    }
                    for b in blocks
                ],
            },
        ),
        _gate(
            "Q2_QUARTER_CONSISTENCY",
            "Q",
            "Consistencia de trimestres activos",
            "INCONCLUSO"
            if active_quarters < int(config["quarterly"]["min_active_for_consistency"])
            else "PASS"
            if positive_share >= float(config["quarterly"]["min_positive_share"])
            and worst_active_r >= -float(config["quarterly"]["max_negative_active_quarter_r"])
            else "FALLA",
            (
                f"{len(positive_active)}/{active_quarters} trimestres activos con R>0 "
                f"({positive_share:.2%}); peor trimestre activo {worst_active_r:.4f} R; "
                f"se exige {config['quarterly']['min_positive_share']:.0%} y ninguno < "
                f"-{config['quarterly']['max_negative_active_quarter_r']} R."
            ),
            f">= {config['quarterly']['min_positive_share']:.0%} de trimestres activos con R>0 y ninguno < -{config['quarterly']['max_negative_active_quarter_r']} R",
            {
                "active_quarters": active_quarters,
                "positive_active": len(positive_active),
                "positive_share": round(positive_share, 4),
                "worst_active_r": worst_active_r,
                "quarterly_r": [
                    {"id": b["id"], "quarter": b["quarter"], "r": b["accepted_r"]}
                    for b in active_blocks
                ],
            },
        ),
        _gate(
            "Q3_QUARTER_CONCENTRATION",
            "Q",
            "Concentracion trimestral",
            "PASS"
            if top2_share is not None
            and top2_share <= float(config["quarterly"]["max_top2_net_share_pct"])
            else "FALLA",
            (
                f"Los dos mejores trimestres concentran {top2_share:.2f}% del neto; "
                f"limite {config['quarterly']['max_top2_net_share_pct']:.1f}%."
                if top2_share is not None
                else "No hay neto positivo para calcular concentracion."
            ),
            f"top-2 trimestres <= {config['quarterly']['max_top2_net_share_pct']:.1f}% del neto",
            {
                "top2_net": round(top2_net, 2),
                "net": acc_stats["net"],
                "top2_share_pct": round(top2_share, 2) if top2_share is not None else None,
                "quarters": [
                    {"quarter": quarter, "net": round(net, 2)}
                    for quarter, net in quarter_net
                ],
            },
        ),
        _gate(
            "Q4_REJECTED_CONSISTENCY",
            "Q",
            "Consistencia trimestral del cohorte rechazado",
            "PASS" if rejected_passes >= int(config["quarterly"]["min_rejected_negative_quarters"]) else "FALLA",
            (
                f"{rejected_passes}/6 trimestres con R rechazado <=0; "
                f"se exigen {config['quarterly']['min_rejected_negative_quarters']}/6. "
                f"Bloques sin rechazados se cuentan como fallo: {', '.join(rejected_empty) or 'ninguno'}."
            ),
            f">= {config['quarterly']['min_rejected_negative_quarters']}/6 trimestres con R rechazado <=0; vacios = fallo",
            {
                "passing_quarters": rejected_passes,
                "empty_rejected_blocks": rejected_empty,
                "blocks": [
                    {
                        "id": b["id"],
                        "quarter": b["quarter"],
                        "rejected": b["rejected"],
                        "rejected_r": b["rejected_r"],
                        "pass": (not b["empty_rejected"]) and b["rejected_r"] <= 0,
                    }
                    for b in blocks
                ],
            },
            legacy_id="P4",
        ),
        _gate(
            "Q5_BLOCK_PF",
            "Q",
            "PF por bloque con umbral activo",
            block_pf_state,
            (
                f"Umbral de bloque = max({config['quarterly']['min_block_pf_trades']}, ceil({len(accepted)}/6)) = {block_pf_min} trades; "
                f"{len(eligible_pf_blocks)} bloques evaluables, minimo PF "
                f"{min_eligible_pf if min_eligible_pf is None else round(min_eligible_pf, 4)}. "
                f"El umbral antiguo de 15 trades no era alcanzable (max bloque {max_block_trades})."
            ),
            f"bloques con >= {block_pf_min} aceptados y PF >= {config['quarterly']['min_block_pf']}",
            {
                "old_min_trades": 15,
                "new_min_trades": block_pf_min,
                "old_min_reachable": old_min_reachable,
                "eligible_blocks": [
                    {
                        "id": b["id"],
                        "accepted": b["accepted"],
                        "pf": b["accepted_pf"],
                    }
                    for b in eligible_pf_blocks
                ],
                "bad_blocks": [b["id"] for b in bad_pf_blocks],
            },
        ),
        _gate(
            "P5_ROBUSTNESS",
            "P",
            "Outliers y concentracion de trades",
            "PASS"
            if drop_best3_r > 0
            and drop_best_month_r > 0
            and top_trade_share is not None
            and top_trade_share <= 50.0
            else "FALLA",
            (
                f"Drop-best-3 R={drop_best3_r:.4f}; drop-best-month R={drop_best_month_r:.4f}; "
                f"mejor trade={top_trade_share:.2f}% del bruto R."
            ),
            "drop_best_3_R > 0, drop_best_month_R > 0 y top_trade_share <= 50%",
            {
                "drop_best_3_r": round(drop_best3_r, 4),
                "drop_best_month_r": round(drop_best_month_r, 4),
                "top_trade_share_gross_r_pct": round(top_trade_share, 2) if top_trade_share is not None else None,
                "top5_share_gross_profit_pct": round(top5_share_gross, 2) if top5_share_gross is not None else None,
            },
        ),
        _gate(
            "P6_COST_STRESS",
            "P",
            "Coste stress del filtro",
            "NO_EVALUABLE",
            "No existe un artefacto de reprecio exacto para el filtro; stress_costs.json es del perfil original de 38 trades y no se usa. La estimacion uniforme es solo diagnostico.",
            "reprecio exacto con comision 1,24/lado y slippage 2",
            {
                "artifact": config["cost_stress"].get("artifact"),
                "approx_stress_net": round(stress_net, 2),
                "approx_stress_pf": round(stress_pf, 4) if stress_pf is not None else None,
                "approx_stress_mean_r": round(stress_mean_r, 4) if stress_mean_r is not None else None,
                "gate_used": False,
            },
        ),
        _gate(
            "P7_MONTHLY_COVERAGE",
            "P",
            "Cobertura mensual",
            "PASS"
            if len(accepted_months) >= int(config["monthly"]["min_active_months"])
            and max_zero_run <= int(config["monthly"]["max_zero_month_streak"])
            else "FALLA",
            (
                f"{len(accepted_months)}/{len(all_months)} meses con aceptados; "
                f"racha maxima sin trades={max_zero_run}; se exige >= {config['monthly']['min_active_months']} "
                f"meses y racha <= {config['monthly']['max_zero_month_streak']}."
            ),
            f">= {config['monthly']['min_active_months']} meses activos y racha cero <= {config['monthly']['max_zero_month_streak']}",
            {
                "active_months": len(accepted_months),
                "total_months": len(all_months),
                "max_zero_month_streak": max_zero_run,
                "zero_months": zero_months,
            },
        ),
        _gate(
            "P8_SHORTS",
            "P",
            "Cortos aceptados",
            "PASS"
            if acc_stats["shorts"] >= 5
            and (statistics.mean([float(t["r_multiple"]) for t in accepted if t["direction"] == "short"]) if acc_stats["shorts"] else 0) >= 0
            and sum(float(t["r_multiple"]) for t in accepted if t["direction"] == "short") >= 0
            else "FALLA",
            (
                f"{acc_stats['shorts']} cortos; media R "
                f"{statistics.mean([float(t['r_multiple']) for t in accepted if t['direction'] == 'short']):.4f}; "
                f"R total {sum(float(t['r_multiple']) for t in accepted if t['direction'] == 'short'):.4f}."
                if acc_stats["shorts"]
                else "0 cortos: no evaluable por la regla P8."
            ),
            ">= 5 cortos, media R >= 0 y R total >= 0",
            {
                "shorts": acc_stats["shorts"],
                "mean_r": round(statistics.mean([float(t["r_multiple"]) for t in accepted if t["direction"] == "short"]), 4)
                if acc_stats["shorts"]
                else None,
                "total_r": round(sum(float(t["r_multiple"]) for t in accepted if t["direction"] == "short"), 4),
            },
        ),
        _gate(
            "P9_TREATMENT",
            "P",
            "Brazo de tratamiento vs baseline",
            "PASS"
            if acc_stats["sum_r"] >= base_stats["sum_r"] and acc_stats["dd_usd"] <= base_stats["dd_usd"]
            else "FALLA",
            (
                f"R tratamiento {acc_stats['sum_r']:.4f} vs baseline {base_stats['sum_r']:.4f}; "
                f"DD tratamiento {acc_stats['dd_usd']:.2f} vs baseline {base_stats['dd_usd']:.2f}."
            ),
            "total_R_tratamiento >= baseline y DD_USD_tratamiento <= baseline",
            {
                "total_r_treatment": acc_stats["sum_r"],
                "total_r_baseline": base_stats["sum_r"],
                "dd_treatment": acc_stats["dd_usd"],
                "dd_baseline": base_stats["dd_usd"],
            },
        ),
    ]

    counts = Counter(g["state"] for g in gates)
    inconclusive_or_missing = [
        g["id"]
        for g in gates
        if g["state"] in {"INCONCLUSO", "NO_EVALUABLE"}
    ]
    failed = [g["id"] for g in gates if g["state"] == "FALLA"]
    global_state = "INCONCLUSO" if inconclusive_or_missing else ("FALLA" if failed else "PASS")
    global_reason = (
        f"INCONCLUSO: falta muestra/cobertura/evaluacion en {', '.join(inconclusive_or_missing)}. "
        f"Fallan: {', '.join(failed) or 'ninguna'}. No se promociona."
        if global_state == "INCONCLUSO"
        else f"FALLA: {', '.join(failed)}."
        if global_state == "FALLA"
        else "PASS: todas las puertas evaluables pasan."
    )

    quarterly = {
        "blocks": blocks,
        "active_quarters": active_quarters,
        "empty_blocks": empty_block_ids,
        "positive_active": len(positive_active),
        "positive_share": round(positive_share, 4),
        "worst_active_r": worst_active_r,
        "top2_share_pct": round(top2_share, 2) if top2_share is not None else None,
        "rejected_passing_quarters": rejected_passes,
        "rejected_empty_blocks": rejected_empty,
        "max_block_trades": max_block_trades,
        "old_block_min_trades": 15,
        "new_block_min_trades": block_pf_min,
        "old_block_min_reachable": old_min_reachable,
    }

    gate_by_id = {gate["id"]: gate for gate in gates}
    demo = {
        "old_G7": {
            "state": old_g7_state,
            "blocks_pf_above_1": old_g7_above,
            "total_blocks": len(blocks),
            "empty_blocks": empty_block_ids,
            "max_block_trades": max_block_trades,
            "old_min_trades": 15,
            "old_min_reachable": old_min_reachable,
            "meaning": "Pasa 4/6 con dos bloques vacios; la clausula de >=15 trades era inerte.",
        },
        "new_Q1_coverage": {
            "state": gate_by_id["Q1_QUARTER_COVERAGE"]["state"],
            "active_quarters": active_quarters,
            "empty_blocks": empty_block_ids,
        },
        "new_Q3_concentration": {
            "state": gate_by_id["Q3_QUARTER_CONCENTRATION"]["state"],
            "top2_share_pct": round(top2_share, 2) if top2_share is not None else None,
        },
        "new_Q4_rejected_consistency": {
            "state": gate_by_id["Q4_REJECTED_CONSISTENCY"]["state"],
            "passing_quarters": rejected_passes,
            "empty_blocks": rejected_empty,
        },
        "old_trivial_gate_now_fails": old_g7_state == "PASS"
        and any(
            gate_by_id[gate_id]["state"] == "FALLA"
            for gate_id in (
                "Q1_QUARTER_COVERAGE",
                "Q3_QUARTER_CONCENTRATION",
                "Q4_REJECTED_CONSISTENCY",
            )
        ),
    }

    report: dict[str, Any] = {
        "schema": "filter025-gates-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "historical_w1_w6_read_only",
        "backtest_executed": False,
        "holdout_read": False,
        "config": str(config_path.relative_to(ROOT)) if config_path.is_relative_to(ROOT) else str(config_path),
        "inputs": {
            str(filter_path.relative_to(ROOT)): {
                "sha256": _sha256(filter_path),
                "trades": len(baseline),
                "accepted": len(accepted),
                "rejected": len(rejected),
            },
            str(baseline_path.relative_to(ROOT)): {
                "sha256": _sha256(baseline_path),
                "baseline_trades": len(baseline),
            },
        },
        "aggregate": {
            "accepted": acc_stats,
            "baseline": base_stats,
            "rejected": rej_stats,
        },
        "quarterly": quarterly,
        "bootstrap": {
            "delta_sel": round(observed_delta, 4),
            "ci_lower": round(lower, 4) if lower is not None else None,
            "ci_upper": round(upper, 4) if upper is not None else None,
            "p_value": round(p_value, 5) if p_value is not None else None,
            "valid_resamples": len(deltas),
            "invalid_resamples": invalid,
            "seed": bootstrap_config["seed"],
            "resamples": bootstrap_config["resamples"],
        },
        "gates": gates,
        "summary": {
            "PASS": counts.get("PASS", 0),
            "FALLA": counts.get("FALLA", 0),
            "INCONCLUSO": counts.get("INCONCLUSO", 0),
            "NO_EVALUABLE": counts.get("NO_EVALUABLE", 0),
            "global": global_state,
            "inconclusive_or_missing": inconclusive_or_missing,
            "failed": failed,
        },
        "decision": {
            "global": global_state,
            "reason": global_reason,
            "promotion": "NO",
            "holdout": "sealed",
        },
        "recalibration_demo": demo,
    }
    report = _json_safe(report)
    if write:
        Path(output_path).write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--no-write", action="store_true", help="No escribir el JSON de salida")
    args = parser.parse_args(argv)
    report = evaluate(args.config, write=not args.no_write, output_path=args.out)
    print("GLOBAL", report["summary"]["global"])
    print("COUNTS", {key: report["summary"][key] for key in ("PASS", "FALLA", "INCONCLUSO", "NO_EVALUABLE")})
    for gate in report["gates"]:
        print(f"{gate['id']:30s} {gate['state']:13s} {gate['reason']}")
    print("OUT", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
