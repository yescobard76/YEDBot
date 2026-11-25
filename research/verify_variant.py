"""Re-ejecuta una variante del bucle y comprueba que las cifras se reproducen.

Uso:
    python research/verify_variant.py --id sl_200

Lee el patch de `reports/autoloop/queue.json`, corre W1-W6 en un solo proceso
(prioridad idle) y compara contra el registro de `resultados.jsonl`.
No toca configuración, DB, holdout ni el 8765.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "reports" / "backtest"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _windows import WINDOWS  # noqa: E402

from server.backtest import _simulate, prepare_dataset  # noqa: E402
from server.config import Settings, apply_settings  # noqa: E402
from server.stats import compute_stats  # noqa: E402

OUT = ROOT / "reports" / "autoloop"
CAPITAL = 25_000.0


def idle() -> None:
    try:
        h = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(h, 0x00000040)
    except Exception:
        pass


def load_queue() -> list[dict]:
    return json.loads((OUT / "queue.json").read_text(encoding="utf-8"))


def load_result(vid: str) -> dict | None:
    path = OUT / "resultados.jsonl"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if row.get("id") == vid:
            return row
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    args = ap.parse_args()
    idle()

    item = next((i for i in load_queue() if i.get("id") == args.id), None)
    if item is None:
        print(f"ERROR: {args.id} no está en queue.json")
        return 2
    base = Settings.model_validate_json(
        (ROOT / "data" / "config.json").read_text(encoding="utf-8")
    )
    cfg = apply_settings(base, item.get("patch") or {})

    started = time.perf_counter()
    trades: list[dict] = []
    per_window = {}
    for key, start, end, days in WINDOWS:
        sessions, source, dataset = prepare_dataset(
            base, days=days, start=date.fromisoformat(start)
        )
        result = _simulate(cfg, sessions, source, f"verify-{args.id}-{key}", dataset)
        trades.extend(result["trades"])
        m = result["metrics"]
        per_window[key] = {
            "sessions": len(sessions),
            "trades": m.get("trades"),
            "net": m.get("net_profit"),
            "pf": m.get("profit_factor"),
            "dd": m.get("max_drawdown"),
        }
        print(f"[{key}] {len(sessions)} sesiones, {m.get('trades')} ops, "
              f"net {m.get('net_profit'):.2f}", flush=True)

    stats = compute_stats(trades, CAPITAL)
    loop_row = load_result(args.id)
    if loop_row is None:
        print(f"ERROR: {args.id} no está en resultados.jsonl; no hay referencia")
        return 2
    payload = {
        "id": args.id,
        "patch": item.get("patch") or {},
        "trades": stats.get("trades"),
        "net": stats.get("net_profit"),
        "pf": stats.get("profit_factor"),
        "dd": stats.get("max_drawdown"),
        "dd_pct": stats.get("max_drawdown_pct"),
        "avg_r": stats.get("avg_r"),
        "win_rate": stats.get("win_rate"),
        "rdd": round(float(stats.get("net_profit") or 0.0)
                     / max(float(stats.get("max_drawdown") or 0.0), 1.0), 4),
        "windows": per_window,
        "seconds": round(time.perf_counter() - started, 1),
    }
    payload["loop"] = {
        "trades": loop_row.get("trades"),
        "net": loop_row.get("net"),
        "pf": loop_row.get("pf"),
        "dd": loop_row.get("dd"),
        "rdd": loop_row.get("rdd"),
    }
    payload["match"] = {
        "trades": payload["trades"] == loop_row.get("trades"),
        "net": abs(float(payload["net"]) - float(loop_row.get("net") or 0)) < 0.01,
        "pf": abs(float(payload["pf"] or 0) - float(loop_row.get("pf") or 0)) < 0.01,
        "dd": abs(float(payload["dd"]) - float(loop_row.get("dd") or 0)) < 0.01,
    }
    payload["delta_net"] = round(
        float(payload["net"]) - float(loop_row.get("net") or 0), 2
    )

    (OUT / "verificacion.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: payload[k] for k in
                      ("id", "trades", "net", "pf", "dd", "rdd", "match")},
                     ensure_ascii=False))
    return 0 if all(payload["match"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
