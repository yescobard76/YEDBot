"""Bootstrap por bloques y comparación múltiple de presets.

Fuente: reports/backtest/equity_continuous_dev.json (solo desarrollo).
Remuestrea bloques móviles de sesiones, no operaciones, para conservar la
dependencia temporal. Calcula intervalos de confianza para neto, PF y DD y
contrasta cada preset contra baseline con corrección de Holm-Bonferroni.

No ejecuta backtests, no usa el holdout y no modifica la configuración activa.

Método:
- 362 sesiones de desarrollo, bloques móviles circulares de 20 sesiones
  (ceil(sqrt(362))), 10.000 remuestras, semilla 20250102.
- Se conserva el orden dentro del bloque; las sesiones sin trades aportan P&L 0.
- Neto: suma de P&L de las sesiones remuestreadas.
- PF: beneficio bruto / pérdida bruta de las operaciones de esas sesiones.
- DD: máximo drawdown de la curva de equity diaria remuestreada.
- Los mismos bloques se usan para todos los presets (bootstrap pareado).
- IC95 individuales y IC95 simultáneos por Bonferroni (33 intervalos:
  11 presets x 3 métricas).
- Contrastes preset - baseline para 10 presets x 3 métricas = 30 pruebas;
  p-valores bootstrap de dos colas corregidos con Holm-Bonferroni.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "reports/backtest/equity_continuous_dev.json"
DEFAULT_JSON = ROOT / "reports/backtest/block_bootstrap.json"
DEFAULT_PRESET_CSV = ROOT / "reports/backtest/block_bootstrap_presets.csv"
DEFAULT_COMPARISON_CSV = ROOT / "reports/backtest/block_bootstrap_comparisons.csv"
SCHEMA = "preset-block-bootstrap-v1"
METRICS = ("net", "pf", "dd")
METRIC_LABELS = {"net": "neto", "pf": "PF", "dd": "DD"}
DEFAULT_SEED = 20250102
DEFAULT_RESAMPLES = 10_000
DEFAULT_BLOCK_LENGTH = 20
ALPHA = 0.05


def _json_number(value: float | None) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return round(float(value), 4)


def _percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    pos = (len(ordered) - 1) * q / 100.0
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    if math.isinf(ordered[low]) or math.isinf(ordered[high]):
        # La interpolacion 0 * inf produce NaN; en la cola infinita el
        # percentil tambien es infinito (no se inventa un limite finito).
        return ordered[low] if math.isinf(ordered[low]) else ordered[high]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _ci(values: list[float], low_q: float = 2.5, high_q: float = 97.5) -> dict[str, Any]:
    return {
        "low": _json_number(_percentile(values, low_q)),
        "high": _json_number(_percentile(values, high_q)),
    }


def _profit_factor(pnls: Iterable[float]) -> float | None:
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = -sum(pnl for pnl in pnls if pnl < 0)
    if gross_loss > 0:
        return gross_profit / gross_loss
    if gross_profit > 0:
        return math.inf
    return None


def _drawdown(pnls: Iterable[float], initial: float) -> float:
    equity = initial
    peak = initial
    worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _metrics(sessions: list[dict[str, Any]], indices: list[int], initial: float) -> dict[str, float | None]:
    net = 0.0
    daily: list[float] = []
    trades: list[float] = []
    for index in indices:
        session = sessions[index]
        net += float(session["net"])
        daily.append(float(session["net"]))
        trades.extend(float(pnl) for pnl in session["pnls"])
    return {
        "net": net,
        "pf": _profit_factor(trades),
        "dd": _drawdown(daily, initial),
    }


def _block_indices(
    rng: random.Random, sessions: int, block_length: int, blocks_needed: int
) -> list[int]:
    """Un bloque móvil circular; se recorta a las sesiones necesarias."""
    indices: list[int] = []
    for _ in range(blocks_needed):
        start = rng.randrange(sessions)
        indices.extend((start + offset) % sessions for offset in range(block_length))
    return indices[:sessions]


def _load_sessions(result: dict[str, Any], initial: float) -> tuple[list[dict[str, Any]], list[str]]:
    """Convierte la curva continua en sesiones con sus P&L por operación."""
    trade_points = result["trade_equity"]
    if not trade_points or trade_points[0].get("ts") is not None:
        raise ValueError(f"{result['preset']}: primer punto de trade_equity no es inicial")
    if len(trade_points) - 1 != int(result["aggregate"]["trades"]):
        raise ValueError(f"{result['preset']}: trade_equity no coincide con el número de trades")

    by_date: dict[str, list[float]] = {}
    pnls: list[float] = []
    for index in range(1, len(trade_points)):
        pnl = round(float(trade_points[index]["equity"]) - float(trade_points[index - 1]["equity"]), 2)
        date = str(trade_points[index]["date"])
        by_date.setdefault(date, []).append(pnl)
        pnls.append(pnl)

    daily = sorted(result["daily_equity"], key=lambda point: point["date"])
    if len(daily) != 362:
        raise ValueError(f"{result['preset']}: se esperaban 362 sesiones, hay {len(daily)}")
    sessions: list[dict[str, Any]] = []
    previous = initial
    for point in daily:
        date = str(point["date"])
        equity = float(point["equity"])
        net = round(equity - previous, 2)
        previous = equity
        session_pnls = by_date.get(date, [])
        if abs(sum(session_pnls) - net) > 0.01:
            raise ValueError(
                f"{result['preset']} {date}: P&L de trades {sum(session_pnls)} != diario {net}"
            )
        sessions.append({"date": date, "net": net, "pnls": session_pnls})

    if abs(sum(pnls) - float(result["aggregate"]["net_profit"])) > 0.01:
        raise ValueError(f"{result['preset']}: los trades no suman el neto")
    if abs(sum(session["net"] for session in sessions) - float(result["aggregate"]["net_profit"])) > 0.01:
        raise ValueError(f"{result['preset']}: las sesiones no suman el neto")
    if abs(float(daily[-1]["equity"]) - float(result["aggregate"]["final_equity"])) > 0.01:
        raise ValueError(f"{result['preset']}: la equity final no coincide")

    blocks = [str(block["window"]) for block in result["blocks"]]
    active = sorted(
        {
            str(point["block"])
            for point in trade_points[1:]
            if point.get("block") in blocks
        }
    )
    return sessions, active


def _point_metrics(sessions: list[dict[str, Any]], initial: float) -> dict[str, Any]:
    all_pnls = [pnl for session in sessions for pnl in session["pnls"]]
    return {
        "net": round(sum(session["net"] for session in sessions), 2),
        "pf": _profit_factor(all_pnls),
        "dd": round(_drawdown([session["net"] for session in sessions], initial), 2),
        "trades": len(all_pnls),
    }


def _bootstrap_p(diffs: list[float]) -> float | None:
    if len(diffs) < 2:
        return None
    n = len(diffs)
    at_or_below = sum(1 for diff in diffs if diff <= 0)
    at_or_above = sum(1 for diff in diffs if diff >= 0)
    # Corrección +1 para no producir p=0 con un bootstrap finito.
    p = 2.0 * min((at_or_below + 1) / (n + 1), (at_or_above + 1) / (n + 1))
    return min(1.0, p)


def _holm(tests: list[dict[str, Any]], family_size: int) -> list[dict[str, Any]]:
    """Holm-Bonferroni con p=None contado como 1 (no testeable)."""
    ordered = sorted(tests, key=lambda test: (test["p_raw"] is None, test["p_raw"] or 1.0))
    previous = 0.0
    for rank, test in enumerate(ordered, start=1):
        p = 1.0 if test["p_raw"] is None else float(test["p_raw"])
        adjusted = min(1.0, max(previous, (family_size - rank + 1) * p))
        test["p_holm"] = round(adjusted, 6)
        test["significant"] = bool(test["p_holm"] < ALPHA and test["p_raw"] is not None)
        previous = adjusted
    return tests


def build_payload(
    source: dict[str, Any],
    resamples: int,
    seed: int,
    block_length: int,
) -> dict[str, Any]:
    if source.get("holdout_executed"):
        raise ValueError("La fuente contiene holdout ejecutado; no se procesa")
    initial = float(source["initial_capital"])
    sessions_by_preset: dict[str, list[dict[str, Any]]] = {}
    active_by_preset: dict[str, list[str]] = {}
    points: dict[str, dict[str, Any]] = {}
    for preset, result in source["results"].items():
        sessions, active = _load_sessions(result, initial)
        sessions_by_preset[preset] = sessions
        active_by_preset[preset] = active
        points[preset] = _point_metrics(sessions, initial)
        if abs(points[preset]["dd"] - float(result["aggregate"]["max_drawdown"])) > 0.01:
            raise ValueError(f"{preset}: DD de sesiones no coincide con el agregado")
        agg_pf = result["aggregate"].get("profit_factor")
        point_pf = points[preset]["pf"]
        if (
            agg_pf is not None
            and isinstance(agg_pf, (int, float))
            and point_pf is not None
            and not (isinstance(point_pf, float) and math.isinf(point_pf))
            and abs(float(point_pf) - float(agg_pf)) > 0.011
        ):
            raise ValueError(f"{preset}: PF de trades no coincide con el agregado")

    n_sessions = len(next(iter(sessions_by_preset.values())))
    blocks_needed = math.ceil(n_sessions / block_length)
    rng = random.Random(seed)
    draws: dict[str, dict[str, list[float | None]]] = {
        preset: {metric: [] for metric in METRICS} for preset in sessions_by_preset
    }

    for _ in range(resamples):
        indices = _block_indices(rng, n_sessions, block_length, blocks_needed)
        for preset, sessions in sessions_by_preset.items():
            metrics = _metrics(sessions, indices, initial)
            for metric in METRICS:
                draws[preset][metric].append(metrics[metric])

    family_estimates = len(sessions_by_preset) * len(METRICS)
    estimate_low_q = 100 * (ALPHA / (2 * family_estimates))
    estimate_high_q = 100 - estimate_low_q
    results: dict[str, Any] = {}
    for preset in sessions_by_preset:
        metrics: dict[str, Any] = {}
        for metric in METRICS:
            values = [value for value in draws[preset][metric] if value is not None]
            defined = len(values)
            inf_values = sum(1 for value in values if isinstance(value, float) and math.isinf(value))
            metrics[metric] = {
                "point": _json_number(points[preset][metric]),
                "ci95": _ci(values),
                "ci95_simultaneous": _ci(values, estimate_low_q, estimate_high_q),
                "defined": defined,
                "undefined": resamples - defined,
                "inf": inf_values,
            }
        results[preset] = {
            "trades": points[preset]["trades"],
            "active_blocks": active_by_preset[preset],
            "metrics": metrics,
        }

    comparison_tests: list[dict[str, Any]] = []
    family_size = (len(sessions_by_preset) - 1) * len(METRICS)
    for preset in sessions_by_preset:
        if preset == "baseline":
            continue
        for metric in METRICS:
            diffs: list[float] = []
            undefined = 0
            for left, right in zip(draws[preset][metric], draws["baseline"][metric]):
                if left is None or right is None:
                    undefined += 1
                    continue
                if isinstance(left, float) and math.isinf(left):
                    undefined += 1
                    continue
                if isinstance(right, float) and math.isinf(right):
                    undefined += 1
                    continue
                diffs.append(float(left) - float(right))
            point_diff = None
            if points[preset][metric] is not None and points["baseline"][metric] is not None:
                if not (isinstance(points[preset][metric], float) and math.isinf(points[preset][metric])):
                    if not (isinstance(points["baseline"][metric], float) and math.isinf(points["baseline"][metric])):
                        point_diff = float(points[preset][metric]) - float(points["baseline"][metric])
            test = {
                "preset": preset,
                "metric": metric,
                "point_diff": _json_number(point_diff),
                "ci95": _ci(diffs) if diffs else {"low": None, "high": None},
                "ci95_simultaneous": (
                    _ci(
                        diffs,
                        100 * (ALPHA / (2 * family_size)),
                        100 - 100 * (ALPHA / (2 * family_size)),
                    )
                    if diffs
                    else {"low": None, "high": None}
                ),
                "n_defined": len(diffs),
                "n_undefined": undefined,
                "p_raw": _bootstrap_p(diffs),
            }
            comparison_tests.append(test)

    # La familia planificada es 10 presets x 3 métricas = 30 contrastes.
    comparison_tests = _holm(comparison_tests, family_size=family_size)
    for test in comparison_tests:
        test["favorable"] = None
        if test["significant"]:
            diff = test["point_diff"]
            if isinstance(diff, (int, float)):
                if test["metric"] == "dd":
                    test["favorable"] = diff < 0
                else:
                    test["favorable"] = diff > 0

    comparisons = {
        "family_size": family_size,
        "method": "Holm-Bonferroni",
        "alpha": ALPHA,
        "tests": comparison_tests,
        "significant": sum(1 for test in comparison_tests if test["significant"]),
    }
    return {
        "schema": SCHEMA,
        "source": "reports/backtest/equity_continuous_dev.json",
        "holdout_executed": bool(source.get("holdout_executed")),
        "sessions": n_sessions,
        "initial_capital": initial,
        "method": {
            "type": "moving-block bootstrap (circular)",
            "unit": "session",
            "block_length": block_length,
            "block_length_rule": "ceil(sqrt(sessions))",
            "resamples": resamples,
            "seed": seed,
            "paired": True,
            "confidence": 0.95,
            "estimate_family_size": family_estimates,
            "estimate_ci_method": "Bonferroni percentile",
        },
        "results": results,
        "comparisons": comparisons,
    }


def _flatten_preset(preset: str, row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "preset": preset,
        "trades": row["trades"],
        "active_blocks": "|".join(row["active_blocks"]),
    }
    for metric in METRICS:
        data = row["metrics"][metric]
        out[f"{metric}_point"] = data["point"]
        out[f"{metric}_ci_low"] = data["ci95"]["low"]
        out[f"{metric}_ci_high"] = data["ci95"]["high"]
        out[f"{metric}_sim_low"] = data["ci95_simultaneous"]["low"]
        out[f"{metric}_sim_high"] = data["ci95_simultaneous"]["high"]
        out[f"{metric}_inf"] = data["inf"]
        out[f"{metric}_undefined"] = data["undefined"]
    return out


def _flatten_comparison(test: dict[str, Any]) -> dict[str, Any]:
    return {
        "preset": test["preset"],
        "metric": test["metric"],
        "point_diff": test["point_diff"],
        "ci_low": test["ci95"]["low"],
        "ci_high": test["ci95"]["high"],
        "sim_low": test["ci95_simultaneous"]["low"],
        "sim_high": test["ci95_simultaneous"]["high"],
        "n_defined": test["n_defined"],
        "n_undefined": test["n_undefined"],
        "p_raw": test["p_raw"],
        "p_holm": test["p_holm"],
        "significant": test["significant"],
        "favorable": test["favorable"],
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--preset-csv", type=Path, default=DEFAULT_PRESET_CSV)
    parser.add_argument("--comparison-csv", type=Path, default=DEFAULT_COMPARISON_CSV)
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--block-length", type=int, default=DEFAULT_BLOCK_LENGTH)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    payload = build_payload(source, args.resamples, args.seed, args.block_length)
    args.json_out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    _write_csv(
        args.preset_csv,
        [_flatten_preset(preset, row) for preset, row in payload["results"].items()],
    )
    _write_csv(
        args.comparison_csv,
        [_flatten_comparison(test) for test in payload["comparisons"]["tests"]],
    )

    print("preset,trades,active,net_point,net_ci,net_sim,pf_point,pf_ci,dd_point,dd_ci")
    for preset, row in payload["results"].items():
        metrics = row["metrics"]
        print(
            f"{preset},{row['trades']},{len(row['active_blocks'])},"
            f"{metrics['net']['point']},{metrics['net']['ci95']},{metrics['net']['ci95_simultaneous']},"
            f"{metrics['pf']['point']},{metrics['pf']['ci95']},"
            f"{metrics['dd']['point']},{metrics['dd']['ci95']}"
        )
    print(
        "comparisons",
        payload["comparisons"]["significant"],
        "/",
        payload["comparisons"]["family_size"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
