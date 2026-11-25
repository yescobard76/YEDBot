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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "backtest"
OUT_JSON = REPORTS / "forward_validation.json"
OUT_MD = REPORTS / "FORWARD_VALIDATION.md"
OUT_HASH = REPORTS / "forward_validation.sha256"
PROTOCOL_LOCK = ROOT / "docs" / "protocolo_backtest.lock.json"
P2_FORWARD_LOCK = ROOT / "docs" / "p2_filtro_stop_or_forward.lock.json"
P2_CONFIRM = REPORTS / "p2_w1_w6_confirm.json"
BE_EXPERIMENT = REPORTS / "p2_be_1r_experiment.json"
LIVE_VS_ORIGINAL = REPORTS / "live_vs_original_mission.json"
P2_BE_FORWARD_LOCK = ROOT / "docs" / "p2_be_1r_forward.lock.json"
DATASET = ROOT / "data" / "real" / "bars_mnq_nq_es_1m.csv"
FORWARD_CSV = REPORTS / "p2_filtro_stop_or_forward" / "bars_forward.csv"
CURRENT_PROFILE = ROOT / "profiles" / "backtest_real" / "config.json"
P2_PROFILE = ROOT / "profiles" / "p2_freq" / "config.json"
MANUAL_PROFILE = ROOT / "data" / "config.json"
LIVE_PROFILE = ROOT / "profiles" / "live_8765" / "config.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha_or_none(path: Path) -> str | None:
    try:
        return sha(path)
    except OSError:
        return None


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _positive_int_or_none(value: Any) -> int | None:
    parsed = _int_or_none(value)
    return parsed if parsed is not None and parsed > 0 else None


def config_settings(path: Path) -> dict[str, Any] | None:
    """Lee los cuatro valores efectivos del perfil, o None si no es legible."""
    try:
        config = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict):
        return None
    risk = config.get("risk") if isinstance(config.get("risk"), dict) else {}
    strategy = config.get("strategy") if isinstance(config.get("strategy"), dict) else {}
    return {
        "max_contracts": _positive_int_or_none(risk.get("max_contracts")),
        "max_sl_ticks": _int_or_none(risk.get("max_sl_ticks")),
        "setup_validity_minutes": _int_or_none(strategy.get("setup_validity_minutes")),
        "retest_tolerance_ticks": _int_or_none(strategy.get("retest_tolerance_ticks")),
    }


def empty_settings() -> dict[str, Any]:
    return {
        "max_contracts": None,
        "max_sl_ticks": None,
        "setup_validity_minutes": None,
        "retest_tolerance_ticks": None,
    }


def effective_manual_config() -> tuple[dict[str, Any], Path | None]:
    """Usa data/config.json y, si no sirve, la copia efectiva del 8765."""
    for path in (MANUAL_PROFILE, LIVE_PROFILE):
        settings = config_settings(path)
        if settings is not None and settings.get("max_contracts") is not None:
            return settings, path
    return empty_settings(), None


def contract_limit_provenance(
    settings: dict[str, Any], source: Path | None
) -> dict[str, Any]:
    value = settings.get("max_contracts")
    if source is None or value is None:
        return {
            "value": None,
            "status": "not_recorded",
            "source": (
                f"{relative(MANUAL_PROFILE)}#risk.max_contracts; "
                f"{relative(LIVE_PROFILE)}#risk.max_contracts"
            ),
            "config_sha256": None,
            "note": (
                "No se encontró un max_contracts válido en la configuración efectiva; "
                "no se asume ningún valor fijo."
            ),
        }
    return {
        "value": value,
        "status": "configured",
        "source": f"{relative(source)}#risk.max_contracts",
        "config_sha256": sha_or_none(source),
        "note": (
            "Leído de la configuración efectiva usada por la instancia 8765; "
            "no es un valor fijo del generador."
        ),
    }


def settings_label(prefix: str, settings: dict[str, Any]) -> str:
    contracts = settings.get("max_contracts")
    contracts_text = (
        f"{contracts} contratos" if contracts is not None else "contratos no registrados"
    )
    sl = settings.get("max_sl_ticks")
    setup = settings.get("setup_validity_minutes")
    retest = settings.get("retest_tolerance_ticks")
    return (
        f"{prefix} · {contracts_text} · SL {sl if sl is not None else 'no registrado'} · "
        f"{setup if setup is not None else '—'}/{retest if retest is not None else '—'}"
    )


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


def development_source_metrics() -> tuple[dict, dict]:
    """Lee manual y original del JSON de la misión, no de un log de texto."""
    source = load_json(LIVE_VS_ORIGINAL)
    scope = source.get("scope") or {}
    constraints = source.get("constraints") or {}
    if scope.get("holdout_used") is not False or constraints.get("holdout_accessed") is not False:
        raise RuntimeError("La fuente histórica no garantiza que el holdout siga sellado")
    aggregate = source.get("aggregate")
    if not isinstance(aggregate, dict):
        raise RuntimeError("La fuente histórica no contiene aggregate")
    try:
        return dev_metrics(aggregate["live"]), dev_metrics(aggregate["original"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Métricas históricas incompletas en live_vs_original_mission.json") from exc


def main() -> int:
    protocol = load_json(PROTOCOL_LOCK)
    p2_forward = load_json(P2_FORWARD_LOCK)
    p2_be_forward = load_json(P2_BE_FORWARD_LOCK)
    p2_stats = load_json(P2_CONFIRM)["aggregate"]["p2"]["stats"]
    be_stats = load_json(BE_EXPERIMENT)["be_1r"]
    baseline, original_reference = development_source_metrics()
    bounds = dataset_bounds()
    manual_settings, manual_source = effective_manual_config()
    manual_contract = contract_limit_provenance(manual_settings, manual_source)
    p2_settings = config_settings(P2_PROFILE) or empty_settings()
    other_8766_settings = config_settings(CURRENT_PROFILE) or empty_settings()

    if bounds["last_session"] >= protocol["holdout"]["start"]:
        raise RuntimeError("El dataset de desarrollo alcanza el holdout; abortar")
    if FORWARD_CSV.exists():
        raise RuntimeError(
            "Existe un CSV forward; este informe de insuficiencia ya no aplica. "
            "Hay que ejecutar el protocolo correspondiente."
        )

    protocol_hashes = {
        "protocol_v1_2_lock": sha(PROTOCOL_LOCK),
        "p2_filter_forward_lock": sha(P2_FORWARD_LOCK),
        "dataset_development": sha(DATASET),
        "data_config_manual": sha_or_none(MANUAL_PROFILE),
        "profiles_backtest_real": sha(CURRENT_PROFILE),
        "profiles_p2_freq": sha(P2_PROFILE),
        "profiles_live_8765": sha_or_none(LIVE_PROFILE),
        "p2_confirm_source": sha(P2_CONFIRM),
        "p2_be_experiment": sha(BE_EXPERIMENT),
        "live_vs_original_source": sha(LIVE_VS_ORIGINAL),
        "p2_be_forward_lock": sha(P2_BE_FORWARD_LOCK),
    }

    candidates = [
        {
            "id": "baseline_manual",
            "label": settings_label("Manual 8765", manual_settings),
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
            "label": settings_label("P2", p2_settings),
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
            "current_profile_sha256": protocol_hashes["data_config_manual"] or "",
            "summary": (
                "No hay muestra forward independiente para P2 ni para P2+BE. "
                "El holdout sigue sellado y la ventana forward empieza después "
                "de la fecha de esta evaluación. Se mantiene la configuración manual viva."
            ),
            "reasons": [
                "El dataset de desarrollo termina el 2026-06-30; no contiene la ventana H1 ni barras posteriores.",
                "El holdout H1 2026-07-01→2026-10-30 está sellado y no se ejecutó; usarlo violaría el protocolo v1.2.",
                "El protocolo forward de P2, P2+BE y manual está pre-registrado en docs/p2_be_1r_forward.lock.json, pero no se ha ejecutado; el lock del filtro 0,25 sigue siendo otra hipótesis.",
                "Las únicas métricas disponibles de P2 y P2+BE son in-sample sobre W1-W6 y no sirven para promover.",
                "P2+BE usa FullManagementExecution de un script de investigación, no el motor de producción.",
                f"La instancia 8766 ({settings_label('P1', other_8766_settings)}) es una referencia separada y no se modificó.",
            ],
        },
        "development": {
            "window": "W1-W6",
            "start": protocol["windows"][0]["start"],
            "end": protocol["windows"][-1]["end"],
            "sessions": sum(int(window["sessions"]) for window in protocol["windows"]),
            "status": "in_sample",
            "role": "context_only_not_validation",
            "source": "; ".join(
                relative(path) for path in (LIVE_VS_ORIGINAL, P2_CONFIRM, BE_EXPERIMENT)
            ),
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
                "start": p2_be_forward["sample"]["start"],
                "end": p2_be_forward["sample"]["end"],
                "source": "docs/p2_be_1r_forward.lock.json",
                "hypothesis": p2_be_forward["hypothesis_id"],
                "applicable_to_candidates": True,
            },
            "candidate_forward_protocol": p2_be_forward["hypothesis_id"],
            "summary": (
                "0 sesiones forward disponibles. El dataset termina el "
                f"{bounds['last_session']}; el protocolo P2/P2+BE/manual está "
                "pre-registrado desde el 2026-12-01, pero no se ha ejecutado."
            ),
            "reasons": [
                "No hay csv forward en reports/backtest/p2_be_manual_forward/.",
                "El protocolo P2/P2+BE/manual está pre-registrado, pero no ejecutado.",
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
            "p2_be_manual_forward": {
                "path": "docs/P2_BE_1R_FORWARD.md",
                "lock": "docs/p2_be_1r_forward.lock.json",
                "sha256": protocol_hashes["p2_be_forward_lock"],
                "status": p2_be_forward.get("status"),
                "can_execute": p2_be_forward.get("execution_gate", {}).get("can_execute"),
                "hypothesis_id": p2_be_forward.get("hypothesis_id"),
                "applicable_to_candidates": True,
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
            "config_path": relative(MANUAL_PROFILE),
            "config_sha256": protocol_hashes["data_config_manual"],
            "profile_copy": relative(LIVE_PROFILE),
            "data_dir": "profiles/live_8765/",
            "settings": manual_settings,
            "contract_limit": manual_contract,
            "role": "current_live_instance",
            "note": (
                "8765 se levantó con una copia de data/config.json y SQLite propio; "
                "data/config.json permanece intacto. El límite de contratos se lee "
                "de la configuración efectiva, no de una constante del generador."
            ),
        },
        "other_instances": [
            {
                "port": 8766,
                "role": "preexisting_reference_not_modified",
                "profile": relative(CURRENT_PROFILE),
                "profile_sha256": protocol_hashes["profiles_backtest_real"],
                "settings": other_8766_settings,
            }
        ],
        "historical_reference": {
            "label": "Original 5/200/150/12",
            "role": "historical_context_not_current_baseline",
            "basis": "fixed_historical_reference",
            "source": "docs/protocolo_backtest.lock.json; reports/backtest/_manual_common.py#ORIGINAL_FREQUENCY_PATCH",
            "dev_metrics": original_reference,
        },
    }

    OUT_JSON.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
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
    manual = report["manual_8765"]
    manual_settings = manual["settings"]
    manual_contract = manual["contract_limit"]
    manual_value = manual_contract["value"]
    manual_summary = "/".join(
        str(value) if value is not None else "no registrado"
        for value in (
            manual_value,
            manual_settings.get("max_sl_ticks"),
            manual_settings.get("setup_validity_minutes"),
            manual_settings.get("retest_tolerance_ticks"),
        )
    )
    md = f"""# Validación fuera de muestra — P2 y P2 + BE 1R

**Estado:** `INSUFICIENTE` · **Decisión:** mantener la configuración manual viva (`8765 {manual_summary}`).<br>
**Generado:** {report['generated_at']}<br>
**Holdout:** `{report['holdout']['id']}` {report['holdout']['start']} → {report['holdout']['end']}, **sellado y no ejecutado**.<br>
**Hash del lock:** `{report['holdout']['lock_sha256']}`<br>
**Dataset de desarrollo:** termina en `{bounds['last_session']}`; no contiene barras del holdout ni forward.

## Por qué no hay una decisión de promoción

{report['decision']['summary']}

- No hay CSV forward ni sesiones posteriores al {bounds['last_session']}.
- El único lock forward existente (`H-P2-FILTER-STOP-OR-025`) prueba el filtro 0,25, no P2 ni P2+BE.
- No se ejecutó ningún backtest nuevo sobre validación; no se abrió el holdout.
- Las métricas de desarrollo son **in-sample** y se muestran solo como contexto.

## Límite de contratos del manual

- **Valor:** `{manual_value if manual_value is not None else 'no registrado'}` · **fuente:** `{manual_contract['source']}` · **estado:** `{manual_contract['status']}`.
- {manual_contract['note']}

## Comparación histórica vs forward

| Candidato | Ops hist. | Neto hist. USD | PF hist. | DD hist. USD | R medio hist. | Forward | Estado |
|---|---:|---:|---:|---:|---:|---|---|
{chr(10).join(rows)}

**Forward:** 0 sesiones disponibles. No se inventan métricas ni se usa el holdout como sustituto.

## Integridad

- Protocolo v1.2: `{protocol_hashes['protocol_v1_2_lock']}`
- Lock forward P2/filtro: `{protocol_hashes['p2_filter_forward_lock']}`
- Lock forward P2/BE/manual: `{protocol_hashes['p2_be_forward_lock']}`
- `data/config.json`: `{protocol_hashes['data_config_manual'] or 'no disponible'}`
- `profiles/backtest_real/config.json`: `{protocol_hashes['profiles_backtest_real']}`
- `profiles/p2_freq/config.json`: `{protocol_hashes['profiles_p2_freq']}`
- Dataset de desarrollo: `{protocol_hashes['dataset_development']}`

No se modificó `data/config.json`, el perfil P2, el protocolo ni el holdout. El informe es reproducible con `python reports/backtest/build_forward_validation.py`.
"""
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")
    print(f"JSON: {OUT_JSON}")
    print(f"MD:   {OUT_MD}")
    print(f"SHA:  {OUT_HASH.read_text(encoding='utf-8').strip()}")
    print(f"Decisión: {report['decision']['kind']} | forward: {report['forward']['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
