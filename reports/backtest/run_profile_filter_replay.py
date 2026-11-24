"""Replay del perfil backtest_real con min_stop_or_ratio=0.25 en memoria.

No escribe configuración: carga data/config.json y profiles/backtest_real/config.json,
calcula sus hashes, ejecuta el replay y vuelve a comprobar que los archivos no
cambiaron. La exclusión 12:01-12:59 del perfil se conserva.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.backtest as bt
from server.config import Settings, apply_settings
from server.market.csv_data import CsvDataset, REQUIRED_SYMBOLS
from server.stats import compute_stats
from server.timeutil import et_date

ACTIVE = ROOT / "data" / "config.json"
PROFILE = ROOT / "profiles" / "backtest_real" / "config.json"
OUT = ROOT / "reports" / "backtest" / "profile_filter_replay.json"
START = date(2025, 1, 10)
SESSIONS = 362
FILTER = 0.25
HOLDOUT = date(2026, 7, 1)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(trade: dict, window: str = "") -> dict:
    meta = trade.get("meta") or {}
    width = (
        (float(meta["orb_high"]) - float(meta["orb_low"])) / 0.25
        if meta.get("orb_high") is not None and meta.get("orb_low") is not None
        else 0.0
    )
    ratio = float(meta.get("stop_ticks") or 0.0) / width if width else None
    return {
        "signal_id": meta.get("signal_id"),
        "window": window,
        "direction": trade.get("direction"),
        "qty": trade.get("qty"),
        "entry_ts": trade.get("entry_ts"),
        "exit_ts": trade.get("exit_ts"),
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("exit_price"),
        "exit_reason": trade.get("exit_reason"),
        "pnl": trade.get("pnl"),
        "r_multiple": trade.get("r_multiple"),
        "stop_or_ratio": round(ratio, 6) if ratio is not None else None,
    }


def summary(trades: list[dict], capital: float) -> dict:
    stats = compute_stats(trades, capital)
    return {
        k: stats.get(k)
        for k in (
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
    }


def main() -> None:
    before = {
        "active_sha256": digest(ACTIVE),
        "profile_sha256": digest(PROFILE),
    }
    active = json.loads(ACTIVE.read_text(encoding="utf-8"))
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    excl_before = {
        "active_start": active.get("risk", {}).get("entry_exclusion_start"),
        "active_end": active.get("risk", {}).get("entry_exclusion_end"),
        "profile_start": profile.get("risk", {}).get("entry_exclusion_start"),
        "profile_end": profile.get("risk", {}).get("entry_exclusion_end"),
    }
    if excl_before["profile_start"] != "12:01" or excl_before["profile_end"] != "12:59":
        raise RuntimeError(f"Exclusión inesperada en el perfil: {excl_before}")

    base = Settings.model_validate(profile)
    if base.risk.entry_exclusion_start != "12:01" or base.risk.entry_exclusion_end != "12:59":
        raise RuntimeError("La exclusión no llegó al Settings base")
    if base.risk.min_stop_or_ratio != 0.0:
        raise RuntimeError("El perfil base no debe tener el filtro activo")

    path = Path(base.feed.csv_path)
    if not path.is_absolute():
        path = ROOT / path
    csv_dataset = CsvDataset.load(
        path,
        REQUIRED_SYMBOLS,
        series_mode=base.feed.series_mode,
        exclude_roll_sessions=base.feed.exclude_roll_sessions,
        allow_holdout=False,
    )
    by_day: dict[date, dict[str, list]] = {}
    for tick in csv_dataset.bars:
        day = et_date(tick["NQ"].ts)
        bucket = by_day.setdefault(day, {s: [] for s in REQUIRED_SYMBOLS})
        for symbol in REQUIRED_SYMBOLS:
            bucket[symbol].append(tick[symbol])
    all_sessions = [(day, data) for day, data in sorted(by_day.items()) if data["NQ"]]
    sessions = [(day, data) for day, data in all_sessions if day >= START][:SESSIONS]
    source = "csv"
    manifest = csv_dataset.manifest
    dataset = {
        "kind": "csv",
        "source": "csv",
        "path": manifest["path"],
        "file_hash": manifest["file_hash"],
        "dataset_id": manifest["dataset_id"],
        "series_id": csv_dataset.series_id,
        "series_mode": csv_dataset.series_mode,
        "contracts_by_session": manifest["contracts_by_session"],
        "expiry_by_session": manifest["expiry_by_session"],
        "all_sessions": manifest["all_sessions"],
        "roll_sessions": manifest["roll_sessions"],
        "excluded_sessions": manifest["excluded_sessions"],
        "manifest": manifest,
    }
    if len(sessions) != SESSIONS:
        raise RuntimeError(f"Se esperaban {SESSIONS} sesiones, hay {len(sessions)}")
    if sessions[-1][0] >= HOLDOUT:
        raise RuntimeError("El dataset toca el holdout")

    arms = {}
    for name, ratio in (("baseline", 0.0), ("filter", FILTER)):
        cfg = apply_settings(base, {"risk": {"min_stop_or_ratio": ratio}})
        started = time.perf_counter()
        result = bt._simulate(cfg, sessions, source, f"profile-{name}", dataset)
        trades = [dict(t) for t in result["trades"]]
        arms[name] = {
            "ratio": ratio,
            "elapsed_sec": round(time.perf_counter() - started, 1),
            "metrics": summary(trades, cfg.risk.initial_capital),
            "trades": [compact(t) for t in trades],
        }
        print(
            f"{name}: {len(trades)} ops, neto {result['metrics']['net_profit']}, "
            f"PF {result['metrics']['profit_factor']}, "
            f"DD {result['metrics']['max_drawdown']} "
            f"({time.perf_counter() - started:.1f}s)",
            flush=True,
        )

    baseline_ids = {t["signal_id"] for t in arms["baseline"]["trades"]}
    filter_ids = {t["signal_id"] for t in arms["filter"]["trades"]}
    removed = sorted(baseline_ids - filter_ids)
    added = sorted(filter_ids - baseline_ids)
    low = [
        t for t in arms["filter"]["trades"]
        if (t["stop_or_ratio"] or 0.0) < FILTER - 1e-9
    ]
    if low:
        raise RuntimeError(f"{len(low)} operaciones del filtro tienen ratio < {FILTER}")
    if added:
        raise RuntimeError(f"El filtro generó {len(added)} operaciones nuevas")

    after = {
        "active_sha256": digest(ACTIVE),
        "profile_sha256": digest(PROFILE),
    }
    excl_after = {
        "active_start": json.loads(ACTIVE.read_text(encoding="utf-8"))["risk"].get("entry_exclusion_start"),
        "active_end": json.loads(ACTIVE.read_text(encoding="utf-8"))["risk"].get("entry_exclusion_end"),
        "profile_start": json.loads(PROFILE.read_text(encoding="utf-8"))["risk"].get("entry_exclusion_start"),
        "profile_end": json.loads(PROFILE.read_text(encoding="utf-8"))["risk"].get("entry_exclusion_end"),
    }
    unchanged = before == after and excl_before == excl_after
    if not unchanged:
        raise RuntimeError("La configuración cambió durante el replay")

    report = {
        "schema": "profile-filter-replay-v1",
        "profile": str(PROFILE.relative_to(ROOT)),
        "active_config": str(ACTIVE.relative_to(ROOT)),
        "dataset": str(path),
        "selection": {
            "start": START.isoformat(),
            "sessions": len(sessions),
            "last": sessions[-1][0].isoformat(),
            "holdout_start": HOLDOUT.isoformat(),
            "holdout_used": False,
        },
        "filter": {"field": "risk.min_stop_or_ratio", "value": FILTER},
        "exclusion": {
            "before": excl_before,
            "after": excl_after,
            "preserved": excl_before == excl_after,
        },
        "config_hashes": {
            "before": before,
            "after": after,
            "unchanged": before == after,
        },
        "arms": arms,
        "comparison": {
            "baseline_ops": len(arms["baseline"]["trades"]),
            "filter_ops": len(arms["filter"]["trades"]),
            "removed_ops": len(removed),
            "added_ops": len(added),
            "removed_signal_ids": removed,
            "added_signal_ids": added,
            "delta_net_profit": round(
                arms["filter"]["metrics"]["net_profit"]
                - arms["baseline"]["metrics"]["net_profit"],
                2,
            ),
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== RESUMEN ===")
    print(f"baseline: {report['comparison']['baseline_ops']} ops, "
          f"{arms['baseline']['metrics']['net_profit']:+.2f} USD")
    print(f"filtro:   {report['comparison']['filter_ops']} ops, "
          f"{arms['filter']['metrics']['net_profit']:+.2f} USD")
    print(f"eliminadas: {len(removed)}, nuevas: {len(added)}")
    print(f"exclusión: {excl_after}")
    print(f"config sin cambios: {unchanged}")
    print(f"JSON: {OUT}")


if __name__ == "__main__":
    main()
