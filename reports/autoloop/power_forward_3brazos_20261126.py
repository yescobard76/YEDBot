#!/usr/bin/env python3
"""Regenera la tabla de potencia del pre-registro forward de tres brazos.

Lee series diarias ya persistidas (no ejecuta backtest, captura ni replay):

- C y L: reports/autoloop/improvement_proposals_20261126_1x.json
  (variantes original_next_open y live_next_open; `pnl` ya neto de fees).
- P1: reports/backtest/live_vs_original_mission.json
  (aggregate.p1.daily; 46 fechas con operaciones, suma 1.992,26).
- Calendario: reports/autoloop/_delta_dump_p1_5_200.json
  (362 sesiones W1-W6).

Calcula, por contraste y por sesion (cero si no hay operacion):
  Delta total, mu/dia, sigma/dia, N80, MDE a 742, IC95% bootstrap y p unilateral.

Uso:
  python reports/autoloop/power_forward_3brazos_20261126.py
  python reports/autoloop/power_forward_3brazos_20261126.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "autoloop" / "power_forward_3brazos_20261126.json"
DOC = ROOT / "reports" / "autoloop" / "PRE_REGISTRO_FORWARD_3BRAZOS_20261126.md"

SERIES = ROOT / "reports" / "autoloop" / "improvement_proposals_20261126_1x.json"
MISSION = ROOT / "reports" / "backtest" / "live_vs_original_mission.json"
CALENDAR = ROOT / "reports" / "autoloop" / "_delta_dump_p1_5_200.json"

SEED = 20261201
RESAMPLES = 10000
TARGET_SESSIONS = 742
SESSIONS_PER_YEAR = 247.3
Z_ALPHA = 1.959964  # alpha 0.05, dos colas
Z_BETA = 0.841621   # potencia 0.80
Z_TOTAL = Z_ALPHA + Z_BETA
MARK_START = "<!-- POWER_TABLE_START -->"
MARK_END = "<!-- POWER_TABLE_END -->"


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def daily_from_trades(payload: dict, name: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for trade in payload["variants"][name]["trades"]:
        session = str(trade["session"])[:10]
        out[session] = out.get(session, 0.0) + float(trade["pnl"])
    return out


def daily_from_aggregate(payload: dict, name: str) -> dict[str, float]:
    return {
        str(row["key"])[:10]: float(row["pnl"])
        for row in payload["aggregate"][name]["daily"]
    }


def fmt(value: float, digits: int) -> str:
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def signed(value: float, digits: int) -> str:
    return ("+" if value > 0 else "") + fmt(value, digits)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def series_stats(delta: list[float]) -> dict:
    total = sum(delta)
    mean = statistics.mean(delta)
    sd = statistics.stdev(delta)
    n80 = (Z_TOTAL * sd / abs(mean)) ** 2
    mde = Z_TOTAL * sd * math.sqrt(TARGET_SESSIONS)

    rng = random.Random(SEED)
    n = len(delta)
    draws = []
    for _ in range(RESAMPLES):
        draws.append(sum(delta[rng.randrange(n)] for _ in range(n)))
    draws.sort()
    lo = draws[int(0.025 * RESAMPLES)]
    hi = draws[int(0.975 * RESAMPLES) - 1]
    se = statistics.stdev(draws)
    p_le0 = sum(1 for value in draws if value <= 0) / RESAMPLES
    p_ge0 = sum(1 for value in draws if value >= 0) / RESAMPLES

    return {
        "delta_total_usd": round(total, 2),
        "mean_per_session_usd": round(mean, 6),
        "sd_per_session_usd": round(sd, 6),
        "n80_sessions": round(n80, 1),
        "n80_years": round(n80 / SESSIONS_PER_YEAR, 2),
        "mde_total_usd_at_742": round(mde, 2),
        "mde_per_session_usd_at_742": round(mde / TARGET_SESSIONS, 4),
        "ci95_total_usd": [round(lo, 2), round(hi, 2)],
        "bootstrap_se_total_usd": round(se, 2),
        "p_one_sided_le0": round(p_le0, 4),
        "p_one_sided_ge0": round(p_ge0, 4),
    }


def build() -> dict:
    series = load_json(SERIES)
    mission = load_json(MISSION)
    calendar_payload = load_json(CALENDAR)

    calendar: list[str] = []
    for window in calendar_payload["windows"].values():
        calendar.extend(str(day)[:10] for day in window["sessions"])
    if len(calendar) != 362 or len(set(calendar)) != 362:
        raise AssertionError("calendario W1-W6 no tiene 362 sesiones únicas")

    c = daily_from_trades(series, "original_next_open")
    l = daily_from_trades(series, "live_next_open")
    p1 = daily_from_aggregate(mission, "p1")

    checks = {
        "calendar_sessions": len(calendar),
        "calendar_unique": len(set(calendar)),
        "c_trades_days": len(c),
        "l_trades_days": len(l),
        "p1_trades_days": len(p1),
        "c_sum_usd": round(sum(c.values()), 2),
        "l_sum_usd": round(sum(l.values()), 2),
        "p1_sum_usd": round(sum(p1.values()), 2),
    }
    expected = {
        "c_sum_usd": 661.44,
        "l_sum_usd": 1481.62,
        "p1_sum_usd": 1992.26,
    }
    for key, value in expected.items():
        if abs(checks[key] - value) > 0.005:
            raise AssertionError(f"{key}: {checks[key]} != {value}")

    expected_by_window = {w["window"]: round(float(w["net"]["p1"]), 2) for w in mission["windows"]}
    p1_blocks = []
    expected_blocks = []
    for window_id, window in calendar_payload["windows"].items():
        days = [str(day)[:10] for day in window["sessions"]]
        p1_blocks.append(round(sum(p1.get(day, 0.0) for day in days), 2))
        expected_blocks.append(expected_by_window[window_id])
    checks["p1_block_sums_usd"] = p1_blocks
    checks["p1_block_sums_expected_usd"] = expected_blocks
    checks["p1_block_sums_match"] = all(
        abs(got - want) <= 0.005 for got, want in zip(p1_blocks, expected_blocks)
    )
    if not checks["p1_block_sums_match"]:
        raise AssertionError(f"P1 block sums: {p1_blocks} != {expected_blocks}")

    cal_set = set(calendar)
    for name, daily in (("C", c), ("L", l), ("P1", p1)):
        stray = sorted(set(daily) - cal_set)
        if stray:
            raise AssertionError(f"{name} tiene fechas fuera del calendario: {stray[:5]}")

    c_series = [c.get(day, 0.0) for day in calendar]
    l_series = [l.get(day, 0.0) for day in calendar]
    p1_series = [p1.get(day, 0.0) for day in calendar]

    contrasts = {
        "L_minus_C": series_stats([b - a for a, b in zip(c_series, l_series)]),
        "P1_minus_C": series_stats([b - a for a, b in zip(c_series, p1_series)]),
        "L_minus_P1": series_stats([b - a for a, b in zip(p1_series, l_series)]),
    }
    for item in contrasts.values():
        mean6 = round(item["mean_per_session_usd"], 6)
        sd6 = round(item["sd_per_session_usd"], 6)
        n80_6 = (Z_TOTAL * sd6 / abs(mean6)) ** 2
        mde_6 = Z_TOTAL * sd6 * math.sqrt(TARGET_SESSIONS)
        item["published_6dp_check"] = {
            "n80_sessions": round(n80_6, 1),
            "mde_total_usd_at_742": round(mde_6, 2),
            "matches": (
                abs(round(n80_6, 1) - item["n80_sessions"]) <= 0.05
                and abs(round(mde_6, 2) - item["mde_total_usd_at_742"]) <= 0.005
            ),
        }

    payload = {
        "schema": "forward-3arm-power-20261126-v2",
        "generated_by": "reports/autoloop/power_forward_3brazos_20261126.py",
        "sources": {
            "series": str(SERIES.relative_to(ROOT)),
            "series_sha256": sha256(SERIES),
            "mission": str(MISSION.relative_to(ROOT)),
            "mission_sha256": sha256(MISSION),
            "calendar": str(CALENDAR.relative_to(ROOT)),
            "calendar_sha256": sha256(CALENDAR),
        },
        "method": {
            "unit": "session",
            "zero_if_no_trade": True,
            "paired_by_session": True,
            "sessions": 362,
            "target_sessions": TARGET_SESSIONS,
            "sessions_per_year": SESSIONS_PER_YEAR,
            "alpha_two_sided": 0.05,
            "power": 0.80,
            "z_alpha": Z_ALPHA,
            "z_beta": Z_BETA,
            "n80_formula": "((z_alpha + z_beta) * sigma_d / abs(mean_delta))^2",
            "mde_formula": "(z_alpha + z_beta) * sigma_d * sqrt(742)",
            "bootstrap": {
                "method": "session_cluster_percentile",
                "resamples": RESAMPLES,
                "seed": SEED,
                "confidence": 0.95,
                "one_sided": "direction of the historical effect",
            },
            "published_precision": "mean and sd shown with 6 decimals; N80 and MDE recomputed from those values",
        },
        "validation": {**checks, "published_6dp_all_match": all(item["published_6dp_check"]["matches"] for item in contrasts.values())},
        "contrasts": contrasts,
        "notes": [
            "Las tres series son exactas a nivel de sesion: 362 sesiones, cero si no hay operacion.",
            "C y L usan pnl ya neto de fees de improvement_proposals_20261126_1x.json.",
            "P1 usa aggregate.p1.daily de live_vs_original_mission.json: 46 fechas, suma 1992.26; sus seis sumas por bloque coinciden exactamente con W1-W6.",
            "El N80 de L-P1 es para detectar |delta| con dos colas; NO es potencia de superioridad de L, cuyo signo historico es negativo.",
            "El IC y el p usan bootstrap por sesion con semilla 20261201; no se usa el IC antiguo de la auditoria de fills.",
        ],
    }
    return payload


def table(payload: dict) -> str:
    rows = []
    for key, label in (
        ("L_minus_C", "L − C"),
        ("P1_minus_C", "P1 − C"),
        ("L_minus_P1", "L − P1"),
    ):
        item = payload["contrasts"][key]
        if key == "L_minus_P1":
            n80 = fmt(item["n80_sessions"], 1) + "*"
            years = fmt(item["n80_years"], 2)
            p = f"{fmt(item['p_one_sided_ge0'], 4)} (≥0)"
        else:
            n80 = fmt(item["n80_sessions"], 1)
            years = fmt(item["n80_years"], 2)
            p = f"{fmt(item['p_one_sided_le0'], 4)} (≤0)"
        ci = f"[{fmt(item['ci95_total_usd'][0], 2)}; {fmt(item['ci95_total_usd'][1], 2)}]"
        rows.append(
            "| {label} | {delta} | {mean} | {sd} | {n80} | {years} | {mde} | {ci} | {p} |".format(
                label=label,
                delta=signed(item["delta_total_usd"], 2),
                mean=signed(item["mean_per_session_usd"], 6),
                sd=fmt(item["sd_per_session_usd"], 6),
                n80=n80,
                years=years,
                mde=fmt(item["mde_total_usd_at_742"], 2),
                ci=ci,
                p=p,
            )
        )
    return "\n".join(
        [
            MARK_START,
            "| Contraste | Δ total (USD) | μ/día (USD) | σ/día (USD) | N80 (sesiones) | Años | MDE a 742 (USD) | IC95 % | p unilateral |",
            "|---|---:|---:|---:|---:|---:|---:|---|---:|",
            *rows,
            "",
            "\\* N80 de L − P1 es para detectar |Δ| con dos colas; no es potencia de superioridad de L, cuyo signo histórico es negativo.",
            MARK_END,
        ]
    )


def ci_rows(payload: dict) -> list[str]:
    rows = []
    for key, label in (
        ("L_minus_C", "L − C"),
        ("P1_minus_C", "P1 − C"),
        ("L_minus_P1", "L − P1"),
    ):
        item = payload["contrasts"][key]
        lo, hi = item["ci95_total_usd"]
        p = item["p_one_sided_ge0"] if key == "L_minus_P1" else item["p_one_sided_le0"]
        direction = "≥0" if key == "L_minus_P1" else "≤0"
        rows.append(
            f"| {label} | `[{fmt(lo, 2)}; {fmt(hi, 2)}]` | {fmt(item['bootstrap_se_total_usd'], 2)} | {fmt(p, 4)} ({direction}) |"
        )
    return rows


def check_doc(payload: dict) -> int:
    text = DOC.read_text(encoding="utf-8").replace("\r\n", "\n")
    if MARK_START not in text or MARK_END not in text:
        print(f"FALTA: marcadores {MARK_START} / {MARK_END} en {DOC}", file=sys.stderr)
        return 1
    start = text.index(MARK_START)
    end = text.index(MARK_END) + len(MARK_END)
    found = text[start:end]
    expected = table(payload)
    if found != expected:
        print("MISMATCH: la tabla del documento no coincide con el script.", file=sys.stderr)
        print("--- documento ---", file=sys.stderr)
        print(found, file=sys.stderr)
        print("--- esperado ---", file=sys.stderr)
        print(expected, file=sys.stderr)
        return 1
    missing = [row for row in ci_rows(payload) if row not in text]
    if missing:
        print("MISMATCH: la tabla de IC/p del documento no coincide con el script.", file=sys.stderr)
        for row in missing:
            print(row, file=sys.stderr)
        return 1
    print("OK: tabla principal y tabla IC/p == salida del script")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="compara la tabla del documento")
    args = parser.parse_args()

    payload = build()
    OUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(table(payload))
    print(f"\nJSON: {OUT.relative_to(ROOT)}")
    if args.check:
        return check_doc(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
