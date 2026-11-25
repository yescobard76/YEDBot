"""Reality Check (White) con N=25 y bootstrap por sesión sobre las 25 variantes.

Lee exclusivamente artefactos ya generados:

- ``reports/autoloop/progreso.json``: operaciones completas de las 25 variantes.
- ``reports/autoloop/resultados.jsonl``: agregados publicados.
- ``reports/autoloop/_delta_calendar.json``: calendario W1-W6 de 362 sesiones.

No re-ejecuta backtests, no abre la DB del 8765, no llama a su API, no lee el
holdout y no modifica configuración. Escribe JSON/CSV en ``reports/autoloop``.

Método:
- Unidad: sesión ET (fecha de salida), con cero en sesiones sin operaciones.
- Bootstrap: bloques móviles circulares, longitud ceil(sqrt(362)) = 20,
  10.000 remuestras, semilla 20250102; los mismos bloques para las 25 variantes.
- Reality Check: estadístico max_k sqrt(T) * mean(f_k) con f_k = variante - base
  (manual 10/300/210/24), recentrado sobre la media muestral; p = (1 + #{V* >= V})/(B+1).
- N=25 incluye la base como estrategia de exceso cero (conservador). Se reportan
  también N=24 (sin base) y N=22 (sin las tres variantes de coste x2).
- RDD = neto / max(DD, 1). IC percentil 95 % del RDD y del delta de RDD.
- Neto sin top-3: se eliminan hasta las 3 mayores ganancias de cada variante.

Uso:
    python research/reality_check_25.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.timeutil import et_date  # noqa: E402

OUT_DIR = ROOT / "reports" / "autoloop"
PROGRESO = OUT_DIR / "progreso.json"
RESULTADOS = OUT_DIR / "resultados.jsonl"
CALENDAR = OUT_DIR / "_delta_calendar.json"
CONFIG = ROOT / "data" / "config.json"
BARS = ROOT / "data" / "bars.csv"

BASE_ID = "manual_base"
CAPITAL = 25_000.0
RESAMPLES = 10_000
SEED = 20250102
CONFIDENCE = 0.95
ALPHA = (1.0 - CONFIDENCE) / 2.0
EXPECTED_VARIANTS = 25
EXPECTED_SESSIONS = 362
HOLDOUT_START = "2026-07-01"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q * 100.0))


def max_drawdown(pnls: np.ndarray) -> float:
    if pnls.size == 0:
        return 0.0
    equity = np.concatenate(([0.0], np.cumsum(pnls)))
    peak = np.maximum.accumulate(equity)
    return float(np.max(peak - equity))


def rdd_of(pnls: np.ndarray) -> tuple[float, float, float]:
    net = float(pnls.sum())
    dd = max_drawdown(pnls)
    return net, dd, net / max(dd, 1.0)


def ordered_pnls(trades: list[dict]) -> np.ndarray:
    ordered = sorted(
        trades, key=lambda t: (int(t["entry_ts"]), int(t["exit_ts"]), str(t.get("id")))
    )
    return np.array([float(t["pnl"]) for t in ordered], dtype=float)


def net_without_top3(trades: list[dict]) -> tuple[float, float, int]:
    pnls = sorted((float(t["pnl"]) for t in trades), reverse=True)
    removed = [p for p in pnls if p > 0.0][:3]
    return float(sum(pnls) - sum(removed)), float(sum(removed)), len(removed)


def block_indices(sessions: int, resamples: int, block_length: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n_blocks = int(math.ceil(sessions / block_length))
    offsets = np.arange(block_length, dtype=np.int64)
    out = np.empty((resamples, sessions), dtype=np.int32)
    for b in range(resamples):
        starts = rng.integers(0, sessions, n_blocks, dtype=np.int64)
        idx = ((starts[:, None] + offsets[None, :]) % sessions).ravel()[:sessions]
        out[b] = idx
    return out


def reality_check(
    series: np.ndarray,
    ids: list[str],
    base_row: int,
    indices: np.ndarray,
    keep: list[int] | None,
    benchmark: bool = True,
) -> dict:
    """White Reality Check recienteado; devuelve p de familia y mejor variante."""
    rows = list(range(len(ids))) if keep is None else list(keep)
    if benchmark:
        f = series[rows] - series[base_row]
    else:
        f = series[rows].copy()
    t = f.shape[1]
    means = f.mean(axis=1)
    observed = math.sqrt(t) * float(means.max())
    boot = np.empty(indices.shape[0], dtype=float)
    for b, idx in enumerate(indices):
        boot[b] = math.sqrt(t) * float((f[:, idx].mean(axis=1) - means).max())
    p_value = (1.0 + float((boot >= observed).sum())) / (indices.shape[0] + 1.0)
    best_pos = int(np.argmax(means))
    return {
        "n_strategies": len(rows),
        "benchmark": BASE_ID if benchmark else "zero",
        "statistic": round(observed, 4),
        "p_value": round(p_value, 4),
        "best_id": ids[rows[best_pos]],
        "best_mean_session_delta": round(float(means[best_pos]), 4),
        "resamples": int(indices.shape[0]),
        "seed": SEED,
    }


def load_inputs() -> tuple[dict, dict, list[str], np.ndarray]:
    progress = json.loads(PROGRESO.read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in RESULTADOS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    published = {row["id"]: row for row in rows}
    calendar = json.loads(CALENDAR.read_text(encoding="utf-8"))

    if len(progress) != EXPECTED_VARIANTS:
        raise SystemExit(f"ERROR: {len(progress)} variantes, se esperaban {EXPECTED_VARIANTS}")
    if set(progress) != set(published):
        raise SystemExit("ERROR: progreso.json y resultados.jsonl no tienen los mismos ids")
    sessions = list(calendar["all"])
    if len(sessions) != EXPECTED_SESSIONS:
        raise SystemExit(f"ERROR: {len(sessions)} sesiones, se esperaban {EXPECTED_SESSIONS}")
    if max(sessions) >= HOLDOUT_START:
        raise SystemExit("ERROR: el calendario entra en el holdout")

    config_sha = sha256_file(CONFIG)
    if calendar.get("config_sha256") != config_sha:
        raise SystemExit("ERROR: el calendario se generó con otra configuración")
    if sha256_file(ROOT / "profiles" / "live_8765" / "config.json") != config_sha:
        raise SystemExit("ERROR: la config viva no coincide con data/config.json")

    return progress, published, sessions, calendar


def main() -> int:
    progress, published, sessions, calendar = load_inputs()
    ids = list(progress)
    base_row = ids.index(BASE_ID)
    sessions_index = {day: i for i, day in enumerate(sessions)}
    t = len(sessions)

    series = np.zeros((len(ids), t), dtype=float)
    trades_by_session: dict[str, list[np.ndarray]] = {}
    for row, vid in enumerate(ids):
        trades = progress[vid]["trades"]
        by_day: dict[str, list[float]] = {}
        for trade in trades:
            day = et_date(int(trade["exit_ts"])).isoformat()
            if day not in sessions_index:
                raise SystemExit(f"ERROR: {vid} tiene una sesión fuera del calendario: {day}")
            pnl = float(trade["pnl"])
            series[row, sessions_index[day]] += pnl
            by_day.setdefault(day, []).append(pnl)
        trades_by_session[vid] = [
            np.array(by_day.get(day, []), dtype=float) for day in sessions
        ]
        expected = float(published[vid]["net"])
        if abs(float(series[row].sum()) - expected) > 0.01:
            raise SystemExit(
                f"ERROR: {vid} suma {series[row].sum():.2f}, publicado {expected:.2f}"
            )
        if len(trades) != int(published[vid]["trades"]):
            raise SystemExit(f"ERROR: {vid} tiene {len(trades)} ops, publicado {published[vid]['trades']}")

    block_length = int(math.ceil(math.sqrt(t)))
    indices = block_indices(t, RESAMPLES, block_length, SEED)

    challengers = [i for i in range(len(ids)) if i != base_row]
    base_cost_ids = [
        i
        for i in range(len(ids))
        if not ids[i].startswith("cost_x2") and "cost_x2" not in ids[i]
    ]

    rc_n25 = reality_check(series, ids, base_row, indices, None, benchmark=True)
    rc_n24 = reality_check(series, ids, base_row, indices, challengers, benchmark=True)
    rc_n22 = reality_check(series, ids, base_row, indices, base_cost_ids, benchmark=True)
    rc_abs = reality_check(series, ids, base_row, indices, None, benchmark=False)

    # RDD bootstrap: se concatenan las operaciones de las sesiones remuestreadas
    # en el orden de los bloques, preservando el orden intra-sesión.
    rdd_boot = np.empty((len(ids), RESAMPLES), dtype=float)
    for row, vid in enumerate(ids):
        arrays = trades_by_session[vid]
        for b, idx in enumerate(indices):
            parts = [arrays[i] for i in idx if arrays[i].size]
            seq = np.concatenate(parts) if parts else np.empty(0, dtype=float)
            _, _, rdd = rdd_of(seq)
            rdd_boot[row, b] = rdd

    results: list[dict] = []
    base_no_top3, base_removed, base_n_removed = net_without_top3(progress[BASE_ID]["trades"])
    for row, vid in enumerate(ids):
        trades = progress[vid]["trades"]
        pnls = ordered_pnls(trades)
        net, dd, rdd = rdd_of(pnls)
        published_row = published[vid]
        if abs(net - float(published_row["net"])) > 0.01:
            raise SystemExit(f"ERROR: DD/net de {vid} no coincide con el publicado")
        if abs(dd - float(published_row["dd"])) > 0.01:
            raise SystemExit(
                f"ERROR: DD de {vid} {dd:.2f} != publicado {published_row['dd']:.2f}"
            )
        no_top3, removed, n_removed = net_without_top3(trades)
        delta_series = series[row] - series[base_row]
        observed_delta = float(delta_series.sum())
        boot_delta_totals = delta_series[indices].sum(axis=1)
        # p individual recienteado: distribución nula con media 0 y dos colas.
        centered = boot_delta_totals - observed_delta
        individual_p = (
            1.0 + float((np.abs(centered) >= abs(observed_delta)).sum())
        ) / (indices.shape[0] + 1.0)
        rdd_samples = rdd_boot[row]
        rdd_low = percentile(rdd_samples, ALPHA)
        rdd_high = percentile(rdd_samples, 1.0 - ALPHA)
        delta_rdd = rdd_samples - rdd_boot[base_row]
        delta_low = percentile(delta_rdd, ALPHA)
        delta_high = percentile(delta_rdd, 1.0 - ALPHA)
        windows = published_row.get("windows", {})
        positive_windows = sum(1 for w in windows.values() if float(w.get("net") or 0) > 0)
        best_window = max(
            windows.items(), key=lambda kv: float(kv[1].get("net") or 0), default=(None, {})
        )[0]
        results.append(
            {
                "id": vid,
                "patch": published_row.get("patch", progress[vid].get("patch", {})),
                "ops": int(published_row["trades"]),
                "net": round(net, 2),
                "pf": published_row.get("pf"),
                "dd": round(dd, 2),
                "rdd": round(rdd, 4),
                "net_no_top3": round(no_top3, 2),
                "top3_removed_sum": round(removed, 2),
                "top3_removed_n": n_removed,
                "delta_net_vs_base": round(net - float(published[BASE_ID]["net"]), 2),
                "delta_net_pct_vs_base": round(
                    100.0 * (net - float(published[BASE_ID]["net"]))
                    / float(published[BASE_ID]["net"]),
                    2,
                ),
                "delta_no_top3_vs_base": round(no_top3 - base_no_top3, 2),
                "delta_rdd_point": round(rdd - float(published[BASE_ID]["rdd"]), 4),
                "individual_p_two_sided": round(individual_p, 4),
                "bonferroni_p_n25": round(min(1.0, individual_p * len(ids)), 4),
                "rdd_ci95": {
                    "low": round(rdd_low, 4),
                    "high": round(rdd_high, 4),
                    "contains_zero": bool(rdd_low <= 0.0 <= rdd_high),
                },
                "delta_rdd_ci95": {
                    "low": round(delta_low, 4),
                    "high": round(delta_high, 4),
                    "contains_zero": bool(delta_low <= 0.0 <= delta_high),
                },
                "rdd_boot_median": round(float(np.median(rdd_samples)), 4),
                "share_rdd_le_zero": round(float((rdd_samples <= 0.0).mean()), 4),
                "positive_windows": positive_windows,
                "best_window": best_window,
            }
        )

    results.sort(key=lambda r: r["delta_net_vs_base"], reverse=True)
    for rank, row in enumerate(results, 1):
        row["rank_delta"] = rank
    rdd_order = {row["id"]: rank for rank, row in enumerate(
        sorted(results, key=lambda r: r["rdd"], reverse=True), 1
    )}
    for row in results:
        row["rank_rdd"] = rdd_order[row["id"]]
        row["h1_gate_pass"] = bool(
            row["id"] != BASE_ID
            and rc_n25["p_value"] < 0.05
            and row["rdd_ci95"]["low"] > 0.0
            and row["delta_rdd_ci95"]["low"] > 0.0
            and row["delta_no_top3_vs_base"] > 0.0
            and row["net_no_top3"] > 0.0
        )

    candidates = [r["id"] for r in results if r["h1_gate_pass"]]
    best = results[0]

    payload = {
        "schema": "reality-check-25-v1",
        "generated_at": date.today().isoformat(),
        "scope": {
            "window": "W1-W6",
            "sessions": t,
            "start": sessions[0],
            "end": sessions[-1],
            "capital": CAPITAL,
            "holdout_used": False,
            "config_sha256": sha256_file(CONFIG),
        },
        "sources": {
            "progreso": {"path": str(PROGRESO.relative_to(ROOT)), "sha256": sha256_file(PROGRESO)},
            "resultados": {
                "path": str(RESULTADOS.relative_to(ROOT)),
                "sha256": sha256_file(RESULTADOS),
            },
            "calendar": {"path": str(CALENDAR.relative_to(ROOT)), "sha256": sha256_file(CALENDAR)},
            "bars": {"path": str(BARS.relative_to(ROOT)), "sha256": sha256_file(BARS)},
            "live_config": {
                "path": "profiles/live_8765/config.json",
                "sha256": sha256_file(ROOT / "profiles" / "live_8765" / "config.json"),
            },
        },
        "method": {
            "unit": "sesión ET (fecha de salida); las sesiones sin operaciones valen 0",
            "bootstrap": "bloques móviles circulares",
            "block_length": block_length,
            "block_length_rule": "ceil(sqrt(sesiones))",
            "resamples": RESAMPLES,
            "seed": SEED,
            "confidence": CONFIDENCE,
            "reality_check": "White (2000), estadístico max recentrado, remuestreo conjunto",
            "benchmark": BASE_ID,
            "n_variants_total": len(ids),
            "n_challengers": len(challengers),
            "net_no_top3": "se eliminan hasta las 3 mayores ganancias de cada variante",
            "rdd": "neto / max(DD absoluto, 1)",
            "dd": "drawdown máximo de la curva de PnL cerrado, orden entry_ts",
            "individual_p": "bootstrap recienteado de dos colas sobre el delta total",
            "h1_gate": [
                "RC p (N=25) < 0,05",
                "IC 95 % del RDD absoluto con límite inferior > 0",
                "IC 95 % del delta de RDD con límite inferior > 0",
                "delta de neto sin top-3 > 0",
                "neto sin top-3 > 0",
            ],
        },
        "reality_check": {
            "n25_including_base": rc_n25,
            "n24_challengers": rc_n24,
            "n22_base_cost_including_base": rc_n22,
            "absolute_vs_zero_n25": rc_abs,
        },
        "base": {
            "id": BASE_ID,
            "ops": int(published[BASE_ID]["trades"]),
            "net": round(float(published[BASE_ID]["net"]), 2),
            "dd": round(float(published[BASE_ID]["dd"]), 2),
            "rdd": round(float(published[BASE_ID]["rdd"]), 4),
            "net_no_top3": round(base_no_top3, 2),
            "top3_removed_sum": round(base_removed, 2),
            "top3_removed_n": base_n_removed,
        },
        "variants": results,
        "h1_candidates": candidates,
        "conclusion": (
            "Ninguna variante supera la puerta completa: no se gasta H1."
            if not candidates
            else "Hay candidata(s) que superan la puerta; solo entonces se pre-registra H1: "
            + ", ".join(candidates)
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "reality_check_25.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = OUT_DIR / "reality_check_25.csv"
    fields = [
        "rank_delta",
        "rank_rdd",
        "id",
        "ops",
        "net",
        "delta_net_vs_base",
        "net_no_top3",
        "delta_no_top3_vs_base",
        "top3_removed_sum",
        "dd",
        "rdd",
        "rdd_ci_low",
        "rdd_ci_high",
        "delta_rdd_ci_low",
        "delta_rdd_ci_high",
        "individual_p_two_sided",
        "bonferroni_p_n25",
        "positive_windows",
        "best_window",
        "h1_gate_pass",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in results:
            writer.writerow(
                {
                    "rank_delta": row["rank_delta"],
                    "rank_rdd": row["rank_rdd"],
                    "id": row["id"],
                    "ops": row["ops"],
                    "net": row["net"],
                    "delta_net_vs_base": row["delta_net_vs_base"],
                    "net_no_top3": row["net_no_top3"],
                    "delta_no_top3_vs_base": row["delta_no_top3_vs_base"],
                    "top3_removed_sum": row["top3_removed_sum"],
                    "dd": row["dd"],
                    "rdd": row["rdd"],
                    "rdd_ci_low": row["rdd_ci95"]["low"],
                    "rdd_ci_high": row["rdd_ci95"]["high"],
                    "delta_rdd_ci_low": row["delta_rdd_ci95"]["low"],
                    "delta_rdd_ci_high": row["delta_rdd_ci95"]["high"],
                    "individual_p_two_sided": row["individual_p_two_sided"],
                    "bonferroni_p_n25": row["bonferroni_p_n25"],
                    "positive_windows": row["positive_windows"],
                    "best_window": row["best_window"],
                    "h1_gate_pass": row["h1_gate_pass"],
                }
            )

    print(json.dumps(
        {
            "variants": len(ids),
            "sessions": t,
            "block_length": block_length,
            "rc_n25": rc_n25,
            "rc_n24": rc_n24,
            "rc_n22": rc_n22,
            "rc_absolute": rc_abs,
            "base": payload["base"],
            "best": best,
            "h1_candidates": candidates,
            "conclusion": payload["conclusion"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
