#!/usr/bin/env python3
"""Compara raw vs adjusted en W4-W6 con la configuración congelada.

Solo cambia feed.series_mode en memoria. No escribe configuración, no usa la
copia pre-ajustada y no permite sesiones del holdout.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.backtest as bt  # noqa: E402
from _windows import WINDOW_IDS as CANONICAL_WINDOW_IDS  # noqa: E402
from server.config import Settings  # noqa: E402
from server.confirmatory import compute_code_hash, settings_sha256, sha256_file  # noqa: E402

LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
RAW_PATH = ROOT / "data/real/bars_mnq_nq_es_1m.csv"
ADJUSTED_COPY = ROOT / "data/real/bars_mnq_nq_es_1m_roll_adjusted.csv"
OUT_JSON = ROOT / "reports/backtest/raw_vs_adjusted_w4_w6.json"
OUT_MD = ROOT / "reports/backtest/RAW_VS_ADJUSTED_W4_W6.md"
# Subconjunto W4-W6 de la definición única en _windows.py.
WINDOW_IDS = CANONICAL_WINDOW_IDS[-3:]
HOLDOUT_START = "2026-07-01"
CONFIG_PATHS = (
    ROOT / "data/config.json",
    ROOT / "profiles/backtest_real/config.json",
    LOCK_PATH,
)
OP_FIELDS = ("entry_ts", "exit_ts", "direction", "qty", "exit_reason")
METRIC_KEYS = (
    "trades",
    "wins",
    "losses",
    "win_rate",
    "profit_factor",
    "net_profit",
    "max_drawdown",
    "max_drawdown_pct",
    "avg_r",
    "total_r",
    "stop_losses",
    "take_profits",
    "session_closes",
)


def sha(path: Path) -> str:
    return sha256_file(path)


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def load_lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def config_hashes() -> dict[str, str | None]:
    return {rel(path): (sha(path) if path.exists() else None) for path in CONFIG_PATHS}


def window_map(lock: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {window["id"]: window for window in lock["windows"]}


def _compact_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    selected = dataset.get("selected_range") or {}
    sessions = dataset.get("sessions") or {}
    window_contracts: dict[str, set[str]] = {}
    window_days = set(sessions.get("dates") or [])
    for day, mapping in (dataset.get("contracts_by_session") or {}).items():
        if day not in window_days:
            continue
        for symbol, code in mapping.items():
            window_contracts.setdefault(symbol, set()).add(code)
    return {
        "id": dataset.get("id"),
        "series_id": dataset.get("series_id"),
        "selected_id": dataset.get("selected_id"),
        "series_mode": dataset.get("series_mode"),
        "file_hash": dataset.get("file_hash"),
        "file_name": dataset.get("file_name"),
        "path": dataset.get("path"),
        "sessions_count": sessions.get("count"),
        "session_dates": sessions.get("dates") or [],
        "selected_range": selected,
        "roll_sessions": dataset.get("roll_sessions") or [],
        "excluded_sessions": dataset.get("excluded_sessions") or [],
        "contracts": dataset.get("contracts") or {},
        "window_contracts": {
            symbol: sorted(codes) for symbol, codes in sorted(window_contracts.items())
        },
    }


def run_one(task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    lock = load_lock()
    window = window_map(lock)[task["window"]]
    settings = Settings.model_validate(lock["settings"]).model_copy(deep=True)
    settings.feed.provider = "csv"
    settings.feed.csv_path = task["csv_path"]
    settings.feed.series_mode = task["mode"]
    settings.feed.exclude_roll_sessions = True
    result = bt.run_backtest(
        settings,
        days=int(window["sessions"]),
        start=date.fromisoformat(window["start"]),
        label=f"{task['window']}-{task['mode']}",
        allow_holdout=False,
    )
    dataset = result["dataset"]
    selected = dataset.get("selected_range") or {}
    first = (selected.get("first_et") or "")[:10]
    last = (selected.get("last_et") or "")[:10]
    if dataset.get("series_mode") != task["mode"]:
        raise RuntimeError(f"{task['window']} {task['mode']}: modo {dataset.get('series_mode')}")
    if dataset["sessions"]["count"] != int(window["sessions"]):
        raise RuntimeError(
            f"{task['window']} {task['mode']}: {dataset['sessions']['count']} sesiones, "
            f"se esperaban {window['sessions']}"
        )
    if not (window["start"] <= first <= last <= window["end"]):
        raise RuntimeError(f"{task['window']}: rango {first}..{last} fuera de la ventana")
    if last >= HOLDOUT_START:
        raise RuntimeError(f"{task['window']}: se alcanzó el holdout ({last})")
    roll_dates = {
        "W4": "2025-12-11",
        "W5": "2026-03-12",
        "W6": "2026-06-10",
    }
    if roll_dates[task["window"]] not in (dataset.get("roll_sessions") or []):
        raise RuntimeError(
            f"{task['window']}: falta el roll {roll_dates[task['window']]} en la serie"
        )
    return {
        "window": task["window"],
        "mode": task["mode"],
        "csv_path": task["csv_path"],
        "trades": result["trades"],
        "metrics": result["metrics"],
        "dataset": _compact_dataset(dataset),
        "experiment": {
            "config_sha256": (result.get("experiment") or {}).get("config_sha256"),
            "dataset_sha256": (result.get("experiment") or {}).get("dataset_sha256"),
            "selected_id": (result.get("experiment") or {}).get("selected_id"),
        },
        "feed": settings.feed.model_dump(),
        "elapsed_s": round(time.perf_counter() - started, 1),
    }


def _trade_sig(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        "signal_id": (trade.get("meta") or {}).get("signal_id"),
        **{field: trade.get(field) for field in OP_FIELDS},
    }


def _metric_value(metrics: dict[str, Any], key: str) -> Any:
    value = metrics.get(key)
    if isinstance(value, float):
        return round(value, 6)
    return value


def compare_window(raw: dict[str, Any], adjusted: dict[str, Any]) -> dict[str, Any]:
    raw_trades = raw["trades"]
    adj_trades = adjusted["trades"]
    operation_differences = []
    pnl_differences = []
    qty_differences = []
    r_differences = []
    for index, (left, right) in enumerate(zip(raw_trades, adj_trades)):
        left_sig = _trade_sig(left)
        right_sig = _trade_sig(right)
        differing = [field for field in ("signal_id", *OP_FIELDS) if left_sig[field] != right_sig[field]]
        if differing:
            operation_differences.append(
                {
                    "index": index,
                    "signal_id": left_sig["signal_id"],
                    "fields": differing,
                    "raw": left_sig,
                    "adjusted": right_sig,
                }
            )
        if round(float(left["pnl"]), 2) != round(float(right["pnl"]), 2):
            pnl_differences.append(
                {
                    "index": index,
                    "signal_id": left_sig["signal_id"],
                    "raw_pnl": left["pnl"],
                    "adjusted_pnl": right["pnl"],
                    "raw_entry": left.get("entry_price"),
                    "adjusted_entry": right.get("entry_price"),
                    "raw_exit": left.get("exit_price"),
                    "adjusted_exit": right.get("exit_price"),
                    "raw_r": left.get("r_multiple"),
                    "adjusted_r": right.get("r_multiple"),
                }
            )
        if left.get("qty") != right.get("qty"):
            qty_differences.append(
                {
                    "index": index,
                    "signal_id": left_sig["signal_id"],
                    "raw_qty": left.get("qty"),
                    "adjusted_qty": right.get("qty"),
                }
            )
        if round(float(left.get("r_multiple") or 0.0), 6) != round(
            float(right.get("r_multiple") or 0.0), 6
        ):
            r_differences.append(
                {
                    "index": index,
                    "signal_id": left_sig["signal_id"],
                    "raw_r": left.get("r_multiple"),
                    "adjusted_r": right.get("r_multiple"),
                }
            )

    metrics = {}
    same_metrics = True
    for key in METRIC_KEYS:
        left = _metric_value(raw["metrics"], key)
        right = _metric_value(adjusted["metrics"], key)
        if left != right:
            same_metrics = False
        metrics[key] = {
            "raw": left,
            "adjusted": right,
            "delta": (
                round(float(right) - float(left), 6)
                if isinstance(left, (int, float)) and isinstance(right, (int, float))
                else None
            ),
        }

    raw_net = round(sum(float(t["pnl"]) for t in raw_trades), 2)
    adj_net = round(sum(float(t["pnl"]) for t in adj_trades), 2)
    same_operations = len(raw_trades) == len(adj_trades) and not operation_differences
    return {
        "window": raw["window"],
        "sessions": raw["dataset"]["sessions_count"],
        "raw_trades": len(raw_trades),
        "adjusted_trades": len(adj_trades),
        "raw_net": raw_net,
        "adjusted_net": adj_net,
        "net_delta": round(adj_net - raw_net, 2),
        "same_operations": same_operations,
        "same_pnl": not pnl_differences,
        "same_qty": not qty_differences,
        "same_r": not r_differences,
        "same_metrics": same_metrics,
        "identical": (
            same_operations
            and not pnl_differences
            and not qty_differences
            and not r_differences
            and same_metrics
        ),
        "operation_differences": operation_differences,
        "pnl_differences": pnl_differences,
        "qty_differences": qty_differences,
        "r_differences": r_differences,
        "metrics": metrics,
        "raw_selected_id": raw["dataset"]["selected_id"],
        "adjusted_selected_id": adjusted["dataset"]["selected_id"],
        "raw_series_id": raw["dataset"]["series_id"],
        "adjusted_series_id": adjusted["dataset"]["series_id"],
        "raw_first": (raw["dataset"]["selected_range"].get("first_et") or "")[:10],
        "raw_last": (raw["dataset"]["selected_range"].get("last_et") or "")[:10],
    }


def fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def fmt_pf(value: Any) -> str:
    return "—" if value is None else fmt_num(value, 2)


def write_markdown(payload: dict[str, Any]) -> None:
    c = payload["comparison"]
    windows = payload["runs"]
    lines = [
        "# Comparación raw vs adjusted — W4–W6",
        "",
        "**Código:** actual, configuración congelada de `docs/protocolo_backtest.lock.json`.  ",
        "**Datos:** mismo CSV crudo; solo cambia `feed.series_mode` en memoria.  ",
        "**Holdout:** no abierto; todas las sesiones terminan el 2026-06-30.  ",
        "**Configuración:** sin cambios; hashes antes/después idénticos.",
        "",
        "## Resultado",
        "",
        "| Ventana | Sesiones | Ops raw | Ops adj | Neto raw | Neto adj | Δ neto | PF raw | PF adj | DD raw | DD adj | Ops idénticas | P&L idéntico |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|",
    ]
    for window_id in WINDOW_IDS:
        item = c["by_window"][window_id]
        raw_metrics = windows[window_id]["raw"]["metrics"]
        adj_metrics = windows[window_id]["adjusted"]["metrics"]
        lines.append(
            f"| {window_id} | {item['sessions']} | {item['raw_trades']} | "
            f"{item['adjusted_trades']} | {fmt_num(item['raw_net'])} | "
            f"{fmt_num(item['adjusted_net'])} | {fmt_num(item['net_delta'])} | "
            f"{fmt_pf(raw_metrics.get('profit_factor'))} | "
            f"{fmt_pf(adj_metrics.get('profit_factor'))} | "
            f"{fmt_num(raw_metrics.get('max_drawdown'))} | "
            f"{fmt_num(adj_metrics.get('max_drawdown'))} | "
            f"{'Sí' if item['same_operations'] else 'No'} | "
            f"{'Sí' if item['same_pnl'] else 'No'} |"
        )
    total = c["total"]
    lines.extend(
        [
            f"| **W4–W6** | **{total['sessions']}** | **{total['raw_trades']}** | "
            f"**{total['adjusted_trades']}** | **{fmt_num(total['raw_net'])}** | "
            f"**{fmt_num(total['adjusted_net'])}** | **{fmt_num(total['net_delta'])}** | "
            "— | — | — | — | "
            f"**{'Sí' if total['same_operations'] else 'No'}** | "
            f"**{'Sí' if total['same_pnl'] else 'No'}** |",
            "",
            "El neto W4–W6 es la suma de los tres bloques; cada bloque se ejecuta con capital",
            "reiniciado, por lo que no se interpreta como una curva continua.",
            "",
            "## Operaciones y P&L",
            "",
        ]
    )
    if total["same_operations"]:
        lines.append(
            f"- **Operaciones idénticas:** sí. {total['raw_trades']} operaciones en ambos modos, "
            "con la misma señal, entrada, salida, dirección, cantidad y `exit_reason`."
        )
    else:
        lines.append(
            f"- **Operaciones idénticas:** no. {len(total['operation_differences'])} "
            "diferencias de firma de operación."
        )
    if total["same_pnl"]:
        lines.append(
            f"- **P&L idéntico:** sí. Neto raw {fmt_num(total['raw_net'])} USD; "
            f"neto adjusted {fmt_num(total['adjusted_net'])} USD; delta 0,00 USD."
        )
    else:
        lines.append(
            f"- **P&L idéntico:** no. {len(total['pnl_differences'])} operaciones con P&L distinto; "
            f"delta neto {fmt_num(total['net_delta'])} USD."
        )
    if total["same_metrics"]:
        lines.append("- **Métricas principales:** idénticas (trades, win rate, PF, neto, DD, R).")
    else:
        lines.append("- **Métricas principales:** hay diferencias; se detallan en el JSON.")
    if not total["operation_differences"]:
        lines.append("- **Diferencias de operación:** ninguna.")
    if not total["pnl_differences"]:
        lines.append("- **Diferencias de P&L:** ninguna.")
    if total["r_differences"]:
        lines.append(f"- **Diferencias de R:** {len(total['r_differences'])}.")

    lines.extend(
        [
            "",
            "## Contexto de rolls",
            "",
            "| Ventana | Sesión de roll excluida | Contratos activos en la ventana |",
            "|---|---|---|",
        ]
    )
    for window_id in WINDOW_IDS:
        dataset = windows[window_id]["adjusted"]["dataset"]
        roll_dates = [d for d in dataset["roll_sessions"] if window_id == "W4" and d.startswith("2025-12") or window_id == "W5" and d.startswith("2026-03") or window_id == "W6" and d.startswith("2026-06")]
        contracts = dataset.get("window_contracts") or {}
        contract_text = "; ".join(
            f"{symbol}: {', '.join(codes)}" for symbol, codes in contracts.items()
        )
        lines.append(
            f"| {window_id} | {', '.join(roll_dates) if roll_dates else '—'} | {contract_text} |"
        )

    lines.extend(
        [
            "",
            "Las tres ventanas contienen un roll (2025-12-11, 2026-03-12 y 2026-06-10).",
            "La sesión de roll se excluye en ambos modos. El modo `adjusted` desplaza el",
            "histórico del contrato saliente con la convención del motor; el modo `raw` no.",
            "",
            "## Datos y hashes",
            "",
            f"- **CSV crudo:** `{payload['data']['raw_path']}`",
            f"  - SHA-256: `{payload['data']['raw_sha256']}`",
            f"- **CSV ajustado de referencia:** `{payload['data']['adjusted_copy_path']}`",
            f"  - SHA-256: `{payload['data']['adjusted_copy_sha256']}`",
            f"- **Lock:** `{payload['config']['lock_path']}`",
            f"  - SHA-256: `{payload['config']['lock_sha256']}`",
            f"- **Código del motor:** `{payload['code']['sha256']}` ({payload['code']['files']} archivos)",
            "",
            "La comparación usa el modo `adjusted` del cargador sobre el CSV crudo, no la",
            "copia pre-ajustada. La copia queda como artefacto de referencia.",
            "",
            "## Configuración y holdout",
            "",
            "Hashes de configuración antes/después:",
            "",
            "| Archivo | Antes | Después | Igual |",
            "|---|---|---|---|",
        ]
    )
    for path, before in payload["config"]["hashes_before"].items():
        after = payload["config"]["hashes_after"].get(path)
        lines.append(
            f"| `{path}` | `{before or '—'}` | `{after or '—'}` | "
            f"{'Sí' if before == after else 'No'} |"
        )
    lines.extend(
        [
            "",
            f"- `allow_holdout=False` en todas las ejecuciones.",
            f"- Última sesión usada: **{payload['comparison']['total']['last_et']}**.",
            f"- Holdout: **no abierto** (ventana sellada {payload['config']['holdout_window']}).",
            "",
            "## Lectura",
            "",
            (
                "La coherencia raw/adjusted se cumple en W4–W6: las decisiones intradía, "
                "las operaciones y el P&L son idénticos. Los precios absolutos no son "
                "idénticos porque el modo ajustado desplaza el histórico de los contratos "
                "antiguos; esa diferencia de niveles no altera la operación."
                if total["identical"]
                else
                "La coherencia raw/adjusted **no** se cumple en W4–W6. Hay diferencias "
                "que deben investigarse antes de usar el ajuste como control de rolls."
            ),
            "",
            "Esto es un control de coherencia de datos, no una validación de rentabilidad.",
            "W4–W6 son desarrollo y ya se usaron para diseñar; el holdout sigue sellado.",
            "",
            f"JSON: `{rel(OUT_JSON)}`",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    lock = load_lock()
    windows = window_map(lock)
    missing = [window_id for window_id in WINDOW_IDS if window_id not in windows]
    if missing:
        raise SystemExit(f"Faltan ventanas en el lock: {missing}")
    if not RAW_PATH.exists():
        raise SystemExit(f"No existe el CSV crudo: {RAW_PATH}")
    if not ADJUSTED_COPY.exists():
        raise SystemExit(f"No existe la copia ajustada: {ADJUSTED_COPY}")

    before = config_hashes()
    code_hash, code_files = compute_code_hash(ROOT, [ROOT / "server"])
    raw_sha = sha(RAW_PATH)
    adjusted_sha = sha(ADJUSTED_COPY)
    print(f"Código {code_hash} ({code_files} archivos)", flush=True)
    print(f"Raw {raw_sha}", flush=True)
    print(f"Adjusted copy {adjusted_sha}", flush=True)

    tasks = [
        {
            "window": window_id,
            "mode": mode,
            "csv_path": str(RAW_PATH),
        }
        for window_id in WINDOW_IDS
        for mode in ("raw", "adjusted")
    ]
    runs: dict[str, dict[str, dict[str, Any]]] = {}
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run_one, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception:
                print(f"[{task['window']} {task['mode']}] FALLÓ", flush=True)
                traceback.print_exc()
                return 1
            runs.setdefault(task["window"], {})[task["mode"]] = result
            metrics = result["metrics"]
            print(
                f"[{task['window']} {task['mode']}] "
                f"{result['dataset']['selected_range'].get('first_et')}.."
                f"{result['dataset']['selected_range'].get('last_et')} | "
                f"{metrics.get('trades')} ops | net {metrics.get('net_profit')} | "
                f"PF {metrics.get('profit_factor')} | {result['elapsed_s']}s",
                flush=True,
            )

    missing_runs = [
        f"{window_id}/{mode}"
        for window_id in WINDOW_IDS
        for mode in ("raw", "adjusted")
        if mode not in runs.get(window_id, {})
    ]
    if missing_runs:
        raise SystemExit(f"Faltan ejecuciones: {missing_runs}")

    comparisons = {
        window_id: compare_window(runs[window_id]["raw"], runs[window_id]["adjusted"])
        for window_id in WINDOW_IDS
    }
    total = {
        "sessions": sum(comparisons[w]["sessions"] for w in WINDOW_IDS),
        "raw_trades": sum(comparisons[w]["raw_trades"] for w in WINDOW_IDS),
        "adjusted_trades": sum(comparisons[w]["adjusted_trades"] for w in WINDOW_IDS),
        "raw_net": round(sum(comparisons[w]["raw_net"] for w in WINDOW_IDS), 2),
        "adjusted_net": round(sum(comparisons[w]["adjusted_net"] for w in WINDOW_IDS), 2),
        "net_delta": 0.0,
        "same_operations": all(comparisons[w]["same_operations"] for w in WINDOW_IDS),
        "same_pnl": all(comparisons[w]["same_pnl"] for w in WINDOW_IDS),
        "same_metrics": all(comparisons[w]["same_metrics"] for w in WINDOW_IDS),
        "same_qty": all(comparisons[w]["same_qty"] for w in WINDOW_IDS),
        "same_r": all(comparisons[w]["same_r"] for w in WINDOW_IDS),
        "identical": all(comparisons[w]["identical"] for w in WINDOW_IDS),
        "operation_differences": [
            diff
            for w in WINDOW_IDS
            for diff in comparisons[w]["operation_differences"]
        ],
        "pnl_differences": [
            diff
            for w in WINDOW_IDS
            for diff in comparisons[w]["pnl_differences"]
        ],
        "qty_differences": [
            diff
            for w in WINDOW_IDS
            for diff in comparisons[w]["qty_differences"]
        ],
        "r_differences": [
            diff
            for w in WINDOW_IDS
            for diff in comparisons[w]["r_differences"]
        ],
        "last_et": max(
            runs[w]["raw"]["dataset"]["selected_range"].get("last_et") or ""
            for w in WINDOW_IDS
        ),
        "first_et": min(
            runs[w]["raw"]["dataset"]["selected_range"].get("first_et") or ""
            for w in WINDOW_IDS
        ),
    }
    total["net_delta"] = round(total["adjusted_net"] - total["raw_net"], 2)
    if total["last_et"][:10] >= HOLDOUT_START:
        raise SystemExit(f"La comparación alcanzó el holdout: {total['last_et']}")

    after = config_hashes()
    if before != after:
        raise SystemExit("La configuración cambió durante la comparación")
    if sha(RAW_PATH) != raw_sha:
        raise SystemExit("El CSV crudo cambió durante la comparación")

    payload = {
        "schema": "raw-vs-adjusted-w4-w6-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "windows": list(WINDOW_IDS),
            "start": total["first_et"][:10],
            "end": total["last_et"][:10],
            "sessions": total["sessions"],
            "holdout_start": HOLDOUT_START,
            "holdout_used": False,
            "allow_holdout": False,
            "adjusted_definition": (
                "feed.series_mode=adjusted sobre el CSV crudo, con la convención actual "
                "de offsets NQ/MNQ y ES; no se usó la copia pre-ajustada."
            ),
        },
        "code": {
            "sha256": code_hash,
            "files": code_files,
            "roots": ["server"],
        },
        "config": {
            "lock_path": rel(LOCK_PATH),
            "lock_sha256": sha(LOCK_PATH),
            "settings_sha256": settings_sha256(lock["settings"]),
            "base_feed": Settings.model_validate(lock["settings"]).feed.model_dump(),
            "hashes_before": before,
            "hashes_after": after,
            "unchanged": before == after,
            "holdout_window": f"{HOLDOUT_START} → 2026-10-30",
        },
        "data": {
            "raw_path": rel(RAW_PATH),
            "raw_sha256": raw_sha,
            "adjusted_copy_path": rel(ADJUSTED_COPY),
            "adjusted_copy_sha256": adjusted_sha,
            "adjusted_copy_used": False,
        },
        "runs": runs,
        "comparison": {
            "by_window": comparisons,
            "total": total,
        },
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    write_markdown(payload)

    print()
    print("RAW vs ADJUSTED W4-W6")
    for window_id in WINDOW_IDS:
        item = comparisons[window_id]
        print(
            f"{window_id}: {item['raw_trades']}/{item['adjusted_trades']} ops | "
            f"net {item['raw_net']} / {item['adjusted_net']} | "
            f"same_ops={item['same_operations']} same_pnl={item['same_pnl']} "
            f"identical={item['identical']}"
        )
    print(
        f"TOTAL: {total['raw_trades']}/{total['adjusted_trades']} ops | "
        f"net {total['raw_net']} / {total['adjusted_net']} | "
        f"same_ops={total['same_operations']} same_pnl={total['same_pnl']} "
        f"identical={total['identical']}"
    )
    print(f"JSON: {rel(OUT_JSON)}")
    print(f"MD:   {rel(OUT_MD)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
