"""Construye el informe de decisión forward para P2 y P2+BE.

Este script NO ejecuta backtests, NO abre el holdout y NO modifica perfiles.
Solo reúne la evidencia ya existente, comprueba hashes y límites del dataset,
y deja constancia de que no hay una muestra forward independiente disponible.

Uso:
    python reports/backtest/build_forward_validation.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "backtest"
OUT_JSON = REPORTS / "forward_validation.json"
OUT_MD = REPORTS / "FORWARD_VALIDATION.md"
OUT_HASH = REPORTS / "forward_validation.sha256"
PROTOCOL_LOCK = ROOT / "docs" / "protocolo_backtest.lock.json"
P2_FORWARD_LOCK = ROOT / "docs" / "p2_filtro_stop_or_forward.lock.json"
P2_CONFIRM = REPORTS / "p2_w1_w6_confirm.json"
BE_EXPERIMENT = REPORTS / "p2_be_1r_experiment.json"
BASELINE_LOG = REPORTS / "_manual_w1_w6_analysis.log"
DATASET = ROOT / "data" / "real" / "bars_mnq_nq_es_1m.csv"
FORWARD_CSV = REPORTS / "p2_filtro_stop_or_forward" / "bars_forward.csv"
CURRENT_PROFILE = ROOT / "profiles" / "backtest_real" / "config.json"
P2_PROFILE = ROOT / "profiles" / "p2_freq" / "config.json"
MANUAL_PROFILE = ROOT / "data" / "config.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dataset_bounds() -> dict:
    first = last = None
    rows = 0
    with DATASET.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            stamp = row.get("timestamp") or ""
            if first is None:
                first = stamp
            last = stamp
            rows += 1
    if not first or not last:
        raise RuntimeError("El dataset de desarrollo está vacío")
    return {
        "path": str(DATASET.relative_to(ROOT)),
        "rows": rows,
        "first_bar_et": first,
        "last_bar_et": last,
        "last_session": last[:10],
    }


def log_variant(name: str) -> dict:
    text = BASELINE_LOG.read_text(encoding="utf-8")
    match = re.search(rf"^{name},([^\\n]+)$", text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"No se encontró la fila {name} en el log de referencia")
    fields = match.group(1).split(",")
    # variante,trades,net,pf,expectancy,win_rate,max_dd,max_dd_pct,avg_r,total_r,...
    return {
        "ops": int(fields[0]),
        "net_usd": float(fields[1]),
        "profit_factor": float(fields[2]),
        "expectancy_usd": float(fields[3]),
        "max_drawdown_usd": float(fields[5]),
        "max_drawdown_pct": float(fields[6]),
        "expectancy_r": float(fields[7]),
        "total_r": float(fields[8]),
    }


def dev_metrics(stats: dict) -> dict:
    return {
        "ops": int(stats["trades"]),
        "net_usd": round(float(stats["net_profit"]), 2),
        "profit_factor": round(float(stats["profit_factor"]), 2),
        "max_drawdown_usd": round(float(stats["max_drawdown"]), 2),
        "max_drawdown_pct": round(float(stats["max_drawdown_pct"]), 3),
        "expectancy_usd": round(float(stats["expectancy"]), 2),
        "expectancy_r": round(float(stats["avg_r"]), 2),
        "total_r": round(float(stats["total_r"]), 2),
    }


def main() -> int:
    protocol = load_json(PROTOCOL_LOCK)
    p2_forward = load_json(P2_FORWARD_LOCK)
    p2_stats = load_json(P2_CONFIRM)["aggregate"]["p2"]["stats"]
    be_stats = load_json(BE_EXPERIMENT)["be_1r"]
    baseline = log_variant("manual")
    original_reference = log_variant("original")
    bounds = dataset_bounds()

    if bounds["last_session"] >= protocol["holdout"]["start"]:
        raise RuntimeError("El dataset de desarrollo alcanza el holdout; abortar")
    if FORWARD_CSV.exists():
        raise RuntimeError(
            "Existe un CSV forward; este informe de insuficiencia ya no aplica. "
            "Hay que ejecutar el protocolo correspondiente."
        )

    p2_forward_start = p2_forward["sample"]["start"]
    p2_forward_end = p2_forward["sample"]["end"]
    protocol_hashes = {
        "protocol_v1_2_lock": sha(PROTOCOL_LOCK),
        "p2_filter_forward_lock": sha(P2_FORWARD_LOCK),
        "dataset_development": sha(DATASET),
        "data_config_manual": sha(MANUAL_PROFILE),
        "profiles_backtest_real": sha(CURRENT_PROFILE),
        "profiles_p2_freq": sha(P2_PROFILE),
        "profiles_live_8765": sha(ROOT / "profiles" / "live_8765" / "config.json")
        if (ROOT / "profiles" / "live_8765" / "config.json").exists()
        else None,
        "p2_confirm_source": sha(P2_CONFIRM),
        "p2_be_experiment": sha(BE_EXPERIMENT),
        "baseline_log": sha(BASELINE_LOG),
    }

    candidates = [
        {
            "id": "baseline_manual",
            "label": "Manual 8765 · 10 contratos · SL 300 · 210/24",
            "short_label": "Manual 8765",
            "role": "baseline",
            "profile": "data/config.json",
            "profile_sha256": protocol_hashes["data_config_manual"],
            "implementation": "server.backtest (perfil manual)",
            "dev_metrics": baseline,
            "forward_metrics": None,
            "forward_status": "reference",
            "forward_note": "La base manual viva no se cambia sin una validación forward independiente.",
        },
        {
            "id": "p2",
            "label": "P2 · 10 contratos · SL 200 · 210/24",
            "short_label": "P2",
            "role": "candidate",
            "profile": "profiles/p2_freq/config.json",
            "profile_sha256": protocol_hashes["profiles_p2_freq"],
            "implementation": "server.backtest (perfil P2)",
            "dev_metrics": dev_metrics(p2_stats),
            "forward_metrics": None,
            "forward_status": "insufficient_data",
            "forward_note": "Sin muestra forward: no se puede aprobar ni rechazar por rendimiento.",
        },
        {
            "id": "p2_be_1r",
            "label": "P2 + break-even 1R",
            "short_label": "P2 + BE 1R",
            "role": "candidate",
            "profile": None,
            "profile_sha256": None,
            "implementation": "reports/backtest/run_partial_exit_1r_full.py::FullManagementExecution (experimental, no producción)",
            "production_available": False,
            "dev_metrics": dev_metrics(be_stats),
            "forward_metrics": None,
            "forward_status": "insufficient_data",
            "forward_note": "Además de faltar forward, la gestión BE vive en un motor experimental.",
        },
    ]

    report = {
        "schema": "forward-validation-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_by": "reports/backtest/build_forward_validation.py",
        "status": "insufficient_data",
        "decision": {
            "kind": "keep_current",
            "label": "Mantener manual 8765",
            "adopted_candidate": None,
            "live_config_updated": False,
            "current_profile": "data/config.json",
            "current_profile_sha256": protocol_hashes["data_config_manual"],
            "summary": (
                "No hay muestra forward independiente para P2 ni para P2+BE. "
                "El holdout sigue sellado y la ventana forward empieza después "
                "de la fecha de esta evaluación. Se mantiene la configuración manual viva."
            ),
            "reasons": [
                "El dataset de desarrollo termina el 2026-06-30; no contiene la ventana H1 ni barras posteriores.",
                "El holdout H1 2026-07-01→2026-10-30 está sellado y no se ejecutó; usarlo violaría el protocolo v1.2.",
                "No existe un protocolo forward pre-registrado para P2 ni para P2+BE. El lock forward existente prueba el filtro stop/ORB 0,25, una hipótesis distinta.",
                "Las únicas métricas disponibles de P2 y P2+BE son in-sample sobre W1-W6 y no sirven para promover.",
                "P2+BE usa FullManagementExecution de un script de investigación, no el motor de producción.",
                "La instancia 8766 (P1 5/200/210/24) es una referencia separada y no se modificó.",
            ],
        },
        "development": {
            "window": "W1-W6",
            "start": protocol["windows"][0]["start"],
            "end": protocol["windows"][-1]["end"],
            "sessions": sum(int(window["sessions"]) for window in protocol["windows"]),
            "status": "in_sample",
            "role": "context_only_not_validation",
            "source": "reports/backtest/_manual_w1_w6_analysis.log; p2_w1_w6_confirm.json; p2_be_1r_experiment.json",
            "note": "Métricas de desarrollo. Se muestran para comparar, no para decidir.",
        },
        "forward": {
            "status": "insufficient_data",
            "evaluated": False,
            "attempts": 0,
            "available_sessions": 0,
            "available_bars": 0,
            "dataset_last_session": bounds["last_session"],
            "dataset_last_bar_et": bounds["last_bar_et"],
            "earliest_preregistered_window": {
                "start": p2_forward_start,
                "end": p2_forward_end,
                "source": "docs/p2_filtro_stop_or_forward.lock.json",
                "hypothesis": p2_forward["hypothesis_id"],
                "applicable_to_candidates": False,
            },
            "candidate_forward_protocol": None,
            "summary": (
                "0 sesiones forward disponibles. El dataset termina el "
                f"{bounds['last_session']}; la primera ventana forward pre-registrada "
                f"empieza el {p2_forward_start} y pertenece a otra hipótesis."
            ),
            "reasons": [
                "No hay csv forward en reports/backtest/p2_filtro_stop_or_forward/.",
                "La ventana forward pre-registrada no cubre P2 ni P2+BE.",
                "No se ejecutó ninguna simulación nueva sobre datos de validación.",
            ],
        },
        "holdout": {
            "id": protocol["holdout"]["id"],
            "start": protocol["holdout"]["start"],
            "end": protocol["holdout"]["end"],
            "sessions": protocol["holdout"]["sessions"],
            "status": "sealed_not_executed",
            "executed": False,
            "used_for_decision": False,
            "lock_path": "docs/protocolo_backtest.lock.json",
            "lock_sha256": protocol_hashes["protocol_v1_2_lock"],
            "protocol_status": protocol.get("status"),
        },
        "protocols": {
            "protocol_v1_2": {
                "path": "docs/PROTOCOLO_BACKTEST.md",
                "lock": "docs/protocolo_backtest.lock.json",
                "sha256": protocol_hashes["protocol_v1_2_lock"],
                "walk_forward": "W1-W6; development only",
                "holdout": "H1; sealed",
            },
            "p2_filter_forward": {
                "path": "docs/P2_FILTRO_STOP_OR_FORWARD.md",
                "lock": "docs/p2_filtro_stop_or_forward.lock.json",
                "sha256": protocol_hashes["p2_filter_forward_lock"],
                "status": p2_forward.get("status"),
                "can_execute": p2_forward.get("execution_gate", {}).get("can_execute"),
                "hypothesis_id": p2_forward.get("hypothesis_id"),
                "applicable_to_candidates": False,
            },
        },
        "candidates": candidates,
        "integrity": {
            **protocol_hashes,
            "dataset": bounds,
            "forward_csv_exists": False,
            "holdout_bars_read": False,
            "forward_bars_read": False,
            "config_changed": False,
        },
        "manual_8765": {
            "config_path": "data/config.json",
            "config_sha256": protocol_hashes["data_config_manual"],
            "profile_copy": "profiles/live_8765/config.json",
            "data_dir": "profiles/live_8765/",
            "settings": {
                "max_contracts": 10,
                "max_sl_ticks": 300,
                "setup_validity_minutes": 210,
                "retest_tolerance_ticks": 24,
            },
            "role": "current_live_instance",
            "note": "8765 se levantó con una copia de data/config.json y SQLite propio; data/config.json permanece intacto.",
        },
        "other_instances": [
            {
                "port": 8766,
                "role": "preexisting_reference_not_modified",
                "profile": "profiles/backtest_real/config.json",
                "profile_sha256": protocol_hashes["profiles_backtest_real"],
                "settings": {
                    "max_contracts": 5,
                    "max_sl_ticks": 200,
                    "setup_validity_minutes": 210,
                    "retest_tolerance_ticks": 24,
                },
            }
        ],
        "historical_reference": {
            "label": "Original 5/200/150/12",
            "role": "historical_context_not_current_baseline",
            "dev_metrics": original_reference,
        },
    }

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_HASH.write_text(
        f"{sha(OUT_JSON)}  {OUT_JSON.name}\n", encoding="utf-8", newline="\n"
    )

    rows = []
    for item in candidates:
        metrics = item["dev_metrics"]
        rows.append(
            "| {label} | {ops} | {net:+.2f} | {pf:.2f} | {dd:.2f} | {r:+.2f} | — | {status} |".format(
                label=item["label"],
                ops=metrics["ops"],
                net=metrics["net_usd"],
                pf=metrics["profit_factor"],
                dd=metrics["max_drawdown_usd"],
                r=metrics["expectancy_r"],
                status=(
                    "Referencia"
                    if item["forward_status"] == "reference"
                    else "Sin datos forward"
                ),
            )
        )
    md = f"""# Validación fuera de muestra — P2 y P2 + BE 1R

**Estado:** `INSUFICIENTE` · **Decisión:** mantener la configuración manual viva (`8765 10/300/210/24`).  
**Generado:** {report['generated_at']}  
**Holdout:** `{report['holdout']['id']}` {report['holdout']['start']} → {report['holdout']['end']}, **sellado y no ejecutado**.  
**Hash del lock:** `{report['holdout']['lock_sha256']}`  
**Dataset de desarrollo:** termina en `{bounds['last_session']}`; no contiene barras del holdout ni forward.

## Por qué no hay una decisión de promoción

{report['decision']['summary']}

- No hay CSV forward ni sesiones posteriores al {bounds['last_session']}.
- El único lock forward existente (`H-P2-FILTER-STOP-OR-025`) prueba el filtro 0,25, no P2 ni P2+BE.
- No se ejecutó ningún backtest nuevo sobre validación; no se abrió el holdout.
- Las métricas de desarrollo son **in-sample** y se muestran solo como contexto.

## Comparación desarrollo vs forward

| Candidato | Ops dev | Neto dev USD | PF dev | DD dev USD | R medio dev | Forward | Estado |
|---|---:|---:|---:|---:|---:|---|---|
{chr(10).join(rows)}

**Forward:** 0 sesiones disponibles. No se inventan métricas ni se usa el holdout como sustituto.

## Integridad

- Protocolo v1.2: `{protocol_hashes['protocol_v1_2_lock']}`
- Lock forward P2/filtro: `{protocol_hashes['p2_filter_forward_lock']}`
- `data/config.json`: `{protocol_hashes['data_config_manual']}`
- `profiles/backtest_real/config.json`: `{protocol_hashes['profiles_backtest_real']}`
- `profiles/p2_freq/config.json`: `{protocol_hashes['profiles_p2_freq']}`
- Dataset de desarrollo: `{protocol_hashes['dataset_development']}`

No se modificó `data/config.json`, el perfil P2, el protocolo ni el holdout. El informe es reproducible con `python reports/backtest/build_forward_validation.py`.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"JSON: {OUT_JSON.relative_to(ROOT)}")
    print(f"MD:   {OUT_MD.relative_to(ROOT)}")
    print(f"SHA:  {OUT_HASH.read_text(encoding='utf-8').strip()}")
    print(f"Decisión: {report['decision']['kind']} | forward: {report['forward']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
