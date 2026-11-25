"""Re-ejecución limpia de candidato, base viva y original + concentración.

Corre W1-W6 en un solo proceso (prioridad idle), guarda los trades y calcula:
peso de las 5 mejores operaciones, neto por mes y por instrumento, ganadoras/
perdedoras, racha perdedora máxima, duración del drawdown máximo, expectancy y
peso del mejor mes / mejor instrumento.

No toca config, DB, 8765 ni holdout. Escribe solo en reports/autoloop/.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import shutil
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BT = ROOT / "reports" / "backtest"
for p in (ROOT, BT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _manual_common import (  # noqa: E402
    INITIAL_CAPITAL,
    MANUAL_PATH,
    load,
    load_original,
)
from _windows import WINDOWS  # noqa: E402
from server.backtest import _simulate, prepare_dataset  # noqa: E402
from server.config import apply_settings  # noqa: E402
from server.stats import compute_stats  # noqa: E402
from server.timeutil import et_date  # noqa: E402


CANDIDATE_PATCH = {
    "risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30"}
}
PUBLISHED = {
    "candidate": {"trades": 36, "net": 3203.82, "pf": 1.90, "dd": 1376.54, "rdd": 2.3274},
    "base": {"trades": 72, "net": 2022.94, "pf": 1.22, "dd": 2891.66, "rdd": 0.6996},
    "original": {"trades": 38, "net": 661.44, "pf": 1.13, "dd": 1967.82, "rdd": 0.3361},
}


def idle() -> None:
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x00000040)
    except Exception:
        pass


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def n(value, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def signed(value, digits: int = 2) -> str:
    return ("+" if float(value) > 0 else "") + n(value, digits)


def month_key(ts: int) -> str:
    d = et_date(ts)
    return f"{d.year:04d}-{d.month:02d}"


def analyze(name: str, trades: list[dict]) -> dict:
    ordered = sorted(trades, key=lambda t: int(t["exit_ts"]))
    pnls = [float(t["pnl"]) for t in ordered]
    total = sum(pnls)
    ops = len(pnls)
    wins = sum(1 for x in pnls if x > 0)
    losses = sum(1 for x in pnls if x < 0)
    breakeven = ops - wins - losses
    top5 = sum(sorted(pnls, reverse=True)[:5])
    net_ex_top5 = total - top5

    monthly: dict[str, float] = defaultdict(float)
    monthly_n: dict[str, int] = defaultdict(int)
    instruments: dict[str, float] = defaultdict(float)
    instrument_n: dict[str, int] = defaultdict(int)
    for trade, pnl in zip(ordered, pnls):
        key = month_key(int(trade["exit_ts"]))
        monthly[key] += pnl
        monthly_n[key] += 1
        symbol = str(trade.get("symbol") or trade.get("contract") or "n/d")
        instruments[symbol] += pnl
        instrument_n[symbol] += 1

    best_month = max(monthly.items(), key=lambda kv: kv[1]) if monthly else (None, 0.0)
    worst_month = min(monthly.items(), key=lambda kv: kv[1]) if monthly else (None, 0.0)
    best_instrument = (
        max(instruments.items(), key=lambda kv: kv[1]) if instruments else (None, 0.0)
    )

    streak = 0
    max_streak = 0
    for pnl in pnls:
        if pnl < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Curva de equity por cierre, capital inicial 25.000.
    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    first_ts = int(ordered[0]["entry_ts"]) if ordered else 0
    peak_ts = first_ts
    max_dd = 0.0
    max_dd_peak = INITIAL_CAPITAL
    max_dd_peak_ts = first_ts
    max_dd_trough_ts = first_ts
    points = [(first_ts, INITIAL_CAPITAL)]
    for trade, pnl in zip(ordered, pnls):
        equity += pnl
        ts = int(trade["exit_ts"])
        points.append((ts, equity))
        if equity > peak:
            peak = equity
            peak_ts = ts
        drawdown = peak - equity
        if drawdown > max_dd + 1e-9:
            max_dd = drawdown
            max_dd_peak = peak
            max_dd_peak_ts = peak_ts
            max_dd_trough_ts = ts

    recovery_ts = None
    if ordered:
        equity = INITIAL_CAPITAL
        for trade, pnl in zip(ordered, pnls):
            equity += pnl
            ts = int(trade["exit_ts"])
            if ts > max_dd_trough_ts and equity >= max_dd_peak - 1e-9:
                recovery_ts = ts
                break
    end_ts = int(ordered[-1]["exit_ts"]) if ordered else first_ts
    dd_end = recovery_ts if recovery_ts is not None else end_ts
    dd_days = (dd_end - max_dd_peak_ts) / 86400.0
    trough_days = (max_dd_trough_ts - max_dd_peak_ts) / 86400.0

    stats = compute_stats(ordered, INITIAL_CAPITAL)
    return {
        "name": name,
        "ops": ops,
        "net": round(total, 2),
        "expectancy_usd": round(total / ops, 2) if ops else None,
        "avg_r": stats.get("avg_r"),
        "win_rate": stats.get("win_rate"),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "top5_net": round(top5, 2),
        "top5_share_pct": round(top5 / total * 100, 2) if total else None,
        "net_ex_top5": round(net_ex_top5, 2),
        "best_month": best_month[0],
        "best_month_net": round(best_month[1], 2),
        "best_month_share_pct": round(best_month[1] / total * 100, 2) if total else None,
        "worst_month": worst_month[0],
        "worst_month_net": round(worst_month[1], 2),
        "best_instrument": best_instrument[0],
        "best_instrument_net": round(best_instrument[1], 2),
        "best_instrument_share_pct": (
            round(best_instrument[1] / total * 100, 2) if total else None
        ),
        "max_losing_streak": max_streak,
        "max_dd": round(max_dd, 2),
        "max_dd_stats": stats.get("max_drawdown"),
        "max_dd_peak_date": et_date(max_dd_peak_ts).isoformat() if ordered else None,
        "max_dd_trough_date": et_date(max_dd_trough_ts).isoformat() if ordered else None,
        "max_dd_recovered": recovery_ts is not None,
        "max_dd_duration_days": round(dd_days, 1),
        "max_dd_trough_days": round(trough_days, 1),
        "monthly": {k: round(v, 2) for k, v in sorted(monthly.items())},
        "monthly_trades": dict(sorted(monthly_n.items())),
        "instruments": {k: round(v, 2) for k, v in instruments.items()},
        "instrument_trades": dict(instrument_n),
        "first_trade": et_date(first_ts).isoformat() if ordered else None,
        "last_trade": et_date(end_ts).isoformat() if ordered else None,
        "fees": stats.get("fees"),
    }


def main() -> int:
    idle()
    started = time.perf_counter()
    base = load(MANUAL_PATH)
    candidate = apply_settings(base, CANDIDATE_PATCH)
    original = load_original()
    variants = {"candidate": candidate, "base": base, "original": original}
    trades: dict[str, list[dict]] = {name: [] for name in variants}
    windows: list[dict] = []

    for key, start_s, end_s, days in WINDOWS:
        sessions, source, dataset = prepare_dataset(
            base, days=days, start=date.fromisoformat(start_s)
        )
        block = {"window": key, "sessions": len(sessions), "variants": {}}
        for name, settings in variants.items():
            result = _simulate(
                settings, sessions, source, f"repro-{name}-{key}", dataset
            )
            trades[name].extend(result["trades"])
            metrics = result["metrics"]
            block["variants"][name] = {
                "trades": metrics.get("trades"),
                "net": metrics.get("net_profit"),
                "pf": metrics.get("profit_factor"),
                "dd": metrics.get("max_drawdown"),
            }
        windows.append(block)
        print(
            f"[{key}] {len(sessions)} sesiones | "
            + " | ".join(
                f"{name} {block['variants'][name]['trades']} ops "
                f"{block['variants'][name]['net']:.2f}"
                for name in variants
            ),
            flush=True,
        )

    headers = {}
    for name, rows in trades.items():
        stats = compute_stats(rows, INITIAL_CAPITAL)
        net = round(float(stats["net_profit"]), 2)
        dd = round(float(stats["max_drawdown"]), 2)
        header = {
            "trades": stats["trades"],
            "net": net,
            "pf": stats.get("profit_factor"),
            "dd": dd,
            "rdd": round(net / max(dd, 1.0), 4),
            "win_rate": stats.get("win_rate"),
            "avg_r": stats.get("avg_r"),
            "expectancy": stats.get("expectancy"),
            "fees": stats.get("fees"),
        }
        expected = PUBLISHED[name]
        checks = {
            "trades": header["trades"] == expected["trades"],
            "net": abs(header["net"] - expected["net"]) <= 0.01,
            "pf": abs(float(header["pf"] or 0) - expected["pf"]) <= 0.006,
            "dd": abs(header["dd"] - expected["dd"]) <= 0.01,
            "rdd": abs(header["rdd"] - expected["rdd"]) <= 0.002,
        }
        header["published"] = expected
        header["match"] = checks
        header["all_match"] = all(checks.values())
        headers[name] = header

    analyses = {name: analyze(name, rows) for name, rows in trades.items()}
    run_dir = ROOT / "reports" / "autoloop" / (
        "repro_concentracion_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    for name, rows in trades.items():
        (run_dir / f"trades_{name}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_dir": str(run_dir.relative_to(ROOT)).replace("\\", "/"),
        "seconds": round(time.perf_counter() - started, 1),
        "scope": "W1-W6, 362 sesiones, 2025-01-10..2026-06-30, capital 25000",
        "config_hashes": {
            "live": sha(MANUAL_PATH),
            "original": sha(ROOT / "profiles/backtest_real/config.json"),
        },
        "candidate_patch": CANDIDATE_PATCH,
        "headers": headers,
        "concentration": analyses,
        "windows": windows,
        "checks": {
            "all_match": all(h["all_match"] for h in headers.values()),
            "monthly_sum_match": {
                name: abs(sum(analyses[name]["monthly"].values()) - analyses[name]["net"]) <= 0.2
                for name in analyses
            },
            "dd_match_stats": {
                name: abs(analyses[name]["max_dd"] - float(analyses[name]["max_dd_stats"] or 0)) <= 0.02
                for name in analyses
            },
        },
    }
    (run_dir / "concentracion.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "reports" / "autoloop" / "concentracion.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Concentración y estabilidad temporal (W1-W6)",
        "",
        f"Generado: {payload['generated_at']} · run: `{payload['run_dir']}`",
        "",
        "| Métrica | Candidato | Base viva | Original |",
        "|---|---:|---:|---:|",
    ]
    keys = [
        ("Ops", "ops", 0),
        ("Neto USD", "net", 2),
        ("Expectancy USD/op", "expectancy_usd", 2),
        ("Ganadoras", "wins", 0),
        ("Perdedoras", "losses", 0),
        ("Top-5 % del neto", "top5_share_pct", 1),
        ("Neto sin top-5", "net_ex_top5", 2),
        ("Mejor mes", "best_month", None),
        ("Mejor mes %", "best_month_share_pct", 1),
        ("Mejor instrumento %", "best_instrument_share_pct", 1),
        ("Racha perdedora máx.", "max_losing_streak", 0),
        ("DD máx. USD", "max_dd", 2),
        ("Duración DD máx. (días)", "max_dd_duration_days", 1),
    ]
    for label, key, digits in keys:
        cells = []
        for name in ("candidate", "base", "original"):
            value = analyses[name].get(key)
            cells.append(str(value) if digits is None else n(value, digits))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Cifras de cabecera vs publicado",
        "",
        "| Variante | Ops | Neto | PF | DD | RDD | ¿Coincide? |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("candidate", "base", "original"):
        h = headers[name]
        lines.append(
            f"| {name} | {h['trades']} | {n(h['net'])} | {n(h['pf'])} | "
            f"{n(h['dd'])} | {n(h['rdd'], 4)} | "
            f"{'sí' if h['all_match'] else 'NO'} |"
        )
    lines += ["", "## Neto por mes", "", "| Mes | Candidato | Base | Original |", "|---|---:|---:|---:|"]
    months = sorted(
        set(analyses["candidate"]["monthly"])
        | set(analyses["base"]["monthly"])
        | set(analyses["original"]["monthly"])
    )
    for month in months:
        lines.append(
            f"| {month} | {n(analyses['candidate']['monthly'].get(month, 0.0))} | "
            f"{n(analyses['base']['monthly'].get(month, 0.0))} | "
            f"{n(analyses['original']['monthly'].get(month, 0.0))} |"
        )
    (run_dir / "concentracion.md").write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "reports" / "autoloop" / "concentracion.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print("\n".join(lines), flush=True)
    print(f"\nrun_dir={run_dir}", flush=True)
    print(f"all_match={payload['checks']['all_match']}", flush=True)
    return 0 if payload["checks"]["all_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
