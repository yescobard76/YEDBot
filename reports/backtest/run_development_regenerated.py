"""Reejecuta W1-W6 con el código actual y guarda un contraste aislado.

No escribe sobre los artefactos actuales del informe. Usa exactamente la
configuración del lock y las ventanas de desarrollo; nunca pasa por el holdout.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.backtest import run_variants  # noqa: E402
from server.config import Settings  # noqa: E402
from server.confirmatory import compute_code_hash, settings_sha256, sha256_file  # noqa: E402
from server.stats import compute_stats  # noqa: E402

OUT = ROOT / "reports/backtest/regenerated"
LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
DATASET_PATH = ROOT / "data/real/bars_mnq_nq_es_1m.csv"
HOLDOUT_PATHS = (
    ROOT / "reports/backtest/holdout.json",
    ROOT / "reports/backtest/holdout.seal.json",
    ROOT / "reports/backtest/holdout.ledger.jsonl",
    ROOT / "reports/backtest/holdout.receipt.json",
)


def _settings() -> Settings:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return Settings.model_validate(lock["settings"])


def _holdout_snapshot() -> dict:
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): (
            sha256_file(path) if path.exists() else None
        )
        for path in HOLDOUT_PATHS
    }


def _run_one(task: dict) -> dict:
    started = time.perf_counter()
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    settings = Settings.model_validate(lock["settings"])
    if task["mode"] == "adjusted":
        settings = settings.model_copy(deep=True)
        settings.feed.series_mode = "adjusted"
    results = run_variants(
        settings,
        days=task["sessions"],
        start=date.fromisoformat(task["start"]),
        allow_holdout=False,
    )
    full = next(r for r in results if r["variant"] == "full")
    selected = full["dataset"].get("selected_range") or {}
    last_et = (selected.get("last_et") or "")[:10]
    first_et = (selected.get("first_et") or "")[:10]
    if full["dataset"].get("series_mode") != task["mode"]:
        raise RuntimeError(f"{task['name']}: modo {full['dataset'].get('series_mode')}")
    if full["dataset"]["sessions"]["count"] != task["sessions"]:
        raise RuntimeError(
            f"{task['name']}: {full['dataset']['sessions']['count']} sesiones, "
            f"se esperaban {task['sessions']}"
        )
    # El lock marca el inicio de calendario; el primer día hábil puede ser
    # posterior (p. ej. W5 empieza el 1 de enero y la primera sesión es el 2).
    if not (task["start"] <= first_et <= task["end"]):
        raise RuntimeError(
            f"{task['name']}: inicio {first_et}, fuera de "
            f"{task['start']}..{task['end']}"
        )
    if last_et > lock["holdout"]["start"] or last_et > "2026-06-30":
        raise RuntimeError(f"{task['name']}: se tocó el holdout ({last_et})")
    if last_et != task["end"]:
        raise RuntimeError(f"{task['name']}: fin {last_et}, se esperaba {task['end']}")
    for result in results:
        result["regenerated"] = {
            "task": task["name"],
            "mode": task["mode"],
            "window": task["window"],
            "source": "run_development_regenerated.py",
        }
    return {
        "task": task,
        "results": results,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }


def _target(task: dict) -> Path:
    if task["name"] == "W1_repeat":
        return OUT / "W1_repeat.json"
    if task["name"] == "W1_adjusted":
        return OUT / "W1_adjusted.json"
    return OUT / f"{task['name']}.json"


def _load_existing(task: dict, code_hash: str) -> list[dict] | None:
    target = _target(task)
    if not target.exists():
        return None
    try:
        results = json.loads(target.read_text(encoding="utf-8"))
        full = next(r for r in results if r["variant"] == "full")
    except Exception:
        return None
    if full.get("dataset", {}).get("code", {}).get("sha256") != code_hash:
        return None
    if full.get("dataset", {}).get("series_mode") != task["mode"]:
        return None
    if full.get("dataset", {}).get("sessions", {}).get("count") != task["sessions"]:
        return None
    return results


def _aggregate(results_by_name: dict[str, list[dict]]) -> dict:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    settings = Settings.model_validate(lock["settings"])
    blocks = []
    variant_trades: dict[str, list[dict]] = {}
    for window in lock["windows"]:
        results = results_by_name[window["id"]]
        full = next(r for r in results if r["variant"] == "full")
        metrics = full["metrics"]
        blocks.append(
            {
                "id": window["id"],
                "start": window["start"],
                "end": window["end"],
                "sessions": full["dataset"]["sessions"]["count"],
                "first_et": full["dataset"]["selected_range"]["first_et"],
                "last_et": full["dataset"]["selected_range"]["last_et"],
                "trades": metrics["trades"],
                "profit_factor": metrics["profit_factor"],
                "expectancy_r": metrics["avg_r"],
                "net_profit": metrics["net_profit"],
                "max_drawdown": metrics["max_drawdown"],
                "worst_loss_streak": metrics["worst_loss_streak"],
                "by_direction": metrics["by_direction"],
            }
        )
        for result in results:
            variant_trades.setdefault(result["variant"], []).extend(result["trades"])

    full_trades = variant_trades["full"]
    aggregate = compute_stats(full_trades, settings.risk.initial_capital)
    variant_aggregate = {}
    for variant in ("orb", "orb_smt", "orb_retest", "full"):
        stats = compute_stats(variant_trades[variant], settings.risk.initial_capital)
        variant_aggregate[variant] = {
            "trades": stats["trades"],
            "profit_factor": stats["profit_factor"],
            "expectancy_r": stats["avg_r"],
            "net_profit": stats["net_profit"],
            "max_drawdown": stats["max_drawdown"],
        }
    return {
        "blocks": blocks,
        "aggregate": aggregate,
        "variant_aggregate": variant_aggregate,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    settings = _settings()
    # El lock v1.2 guarda or_retracement_pct=null (campo añadido después); el
    # modelo actual lo resuelve al default 0.382. No participa con entry_reference=or_mid.
    expected = json.loads(json.dumps(lock["settings"]))
    # Campos añadidos después de congelar el lock: si no están declarados, el
    # default actual es el valor histórico. No se reescribe el lock.
    for key in ("or_retracement_pct", "retest_depth"):
        if expected["strategy"].get(key) is None:
            expected["strategy"][key] = getattr(settings.strategy, key)
    for key in ("entry_exclusion_start", "entry_exclusion_end"):
        if expected["risk"].get(key) is None:
            expected["risk"][key] = getattr(settings.risk, key)
    assert settings.model_dump() == expected, "Configuración distinta del lock"
    assert settings.feed.series_mode == "raw"
    assert settings.feed.csv_path.endswith("bars_mnq_nq_es_1m.csv")
    assert lock["holdout"]["start"] == "2026-07-01"

    dataset_before = sha256_file(DATASET_PATH)
    holdout_before = _holdout_snapshot()
    code_hash, code_files = compute_code_hash(ROOT, [ROOT / "server", ROOT / "tests"])
    print(f"Código {code_hash} ({code_files} archivos)", flush=True)
    print(f"Dataset {dataset_before}", flush=True)
    print(f"Holdout ausente/previo: {holdout_before}", flush=True)

    tasks = []
    for window in lock["windows"]:
        tasks.append(
            {
                "name": window["id"],
                "window": window["id"],
                "mode": "raw",
                "start": window["start"],
                "end": window["end"],
                "sessions": window["sessions"],
            }
        )
    w1 = lock["windows"][0]
    tasks.extend(
        [
            {
                "name": "W1_repeat",
                "window": "W1",
                "mode": "raw",
                "start": w1["start"],
                "end": w1["end"],
                "sessions": w1["sessions"],
            },
            {
                "name": "W1_adjusted",
                "window": "W1",
                "mode": "adjusted",
                "start": w1["start"],
                "end": w1["end"],
                "sessions": w1["sessions"],
            },
        ]
    )

    started = time.perf_counter()
    results_by_name: dict[str, list[dict]] = {}
    pending = []
    for task in tasks:
        existing = _load_existing(task, code_hash)
        if existing is not None:
            results_by_name[task["name"]] = existing
            print(f"[{task['name']}] ya existe con este código; se reutiliza", flush=True)
        else:
            pending.append(task)

    with ProcessPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_run_one, task): task for task in pending}
        for future in as_completed(futures):
            task = futures[future]
            try:
                payload = future.result()
            except Exception:
                print(f"[{task['name']}] FALLÓ", flush=True)
                traceback.print_exc()
                return 1
            _target(task).write_text(
                json.dumps(payload["results"], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            results_by_name[task["name"]] = payload["results"]
            full = next(r for r in payload["results"] if r["variant"] == "full")
            print(
                f"[{task['name']}] {full['dataset']['selected_range']['first_et']}.."
                f"{full['dataset']['selected_range']['last_et']} "
                f"{full['metrics']['trades']} ops, PF {full['metrics']['profit_factor']}, "
                f"net {full['metrics']['net_profit']} ({payload['elapsed_s']}s)",
                flush=True,
            )

    missing = [task["name"] for task in tasks if task["name"] not in results_by_name]
    if missing:
        raise RuntimeError(f"Faltan bloques: {', '.join(missing)}")

    aggregated = _aggregate(results_by_name)
    (OUT / "development_aggregate.json").write_text(
        json.dumps(aggregated["aggregate"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUT / "blocks_summary.json").write_text(
        json.dumps(aggregated["blocks"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (OUT / "variant_aggregate.json").write_text(
        json.dumps(aggregated["variant_aggregate"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    dataset_after = sha256_file(DATASET_PATH)
    holdout_after = _holdout_snapshot()
    if dataset_before != dataset_after:
        raise RuntimeError("El dataset cambió durante la reejecución")
    if holdout_before != holdout_after:
        raise RuntimeError("Apareció o cambió un artefacto de holdout")
    if any(path.exists() for path in HOLDOUT_PATHS):
        raise RuntimeError("Se creó un artefacto de holdout durante la reejecución")

    metadata = {
        "schema": "development-regenerated-v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "code_sha256": code_hash,
        "code_files": code_files,
        "dataset_sha256": dataset_before,
        "settings_sha256": settings_sha256(lock["settings"]),
        "protocol_sha256": sha256_file(ROOT / "docs/PROTOCOLO_BACKTEST.md"),
        "lock_sha256": sha256_file(LOCK_PATH),
        "holdout": {
            "status": "sealed",
            "inspected": False,
            "before": holdout_before,
            "after": holdout_after,
        },
        "tasks": tasks,
        "windows": [
            {
                "id": block["id"],
                "sessions": block["sessions"],
                "first_et": block["first_et"],
                "last_et": block["last_et"],
            }
            for block in aggregated["blocks"]
        ],
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    (OUT / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("AGREGADO", json.dumps(aggregated["aggregate"], ensure_ascii=False), flush=True)
    print("VARIANTES", json.dumps(aggregated["variant_aggregate"], ensure_ascii=False), flush=True)
    print(f"Escrito en {OUT} en {metadata['elapsed_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
