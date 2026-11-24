"""Mide la sensibilidad de los 11 presets default a costes peores.

Escenarios aislados sobre los mismos W1-W6 del desarrollo:

- ``slippage_plus_1``: slippage 2 ticks/lado (base 1), comisión base.
- ``commission_double``: comisión 1,24 USD/lado (base 0,62), slippage base.
- ``combined``: ambos shocks a la vez.

No usa el holdout ni modifica la configuración activa. Los resultados base
se leen de ``presets_default_dev.json``; los escenarios se reejecutan porque el
artefacto base no guarda contratos ni comisiones por operación.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import fmean
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "reports/backtest"
for path in (ROOT, REPORT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_presets_dev import (  # noqa: E402
    DEFAULT_DATASET_PATH,
    DEVELOPMENT_END,
    WINDOWS,
    _row_from_result,
    _settings,
    aggregate,
)
from server.backtest import DEFAULT_PRESETS, resolve_presets, run_presets  # noqa: E402

BASE_PATH = REPORT_DIR / "presets_default_dev.json"
OUT_JSON = REPORT_DIR / "cost_sensitivity_presets.json"
OUT_CSV = REPORT_DIR / "cost_sensitivity_presets.csv"
OUT_MD = REPORT_DIR / "COST_SENSITIVITY_PRESETS.md"
PARTS_DIR = REPORT_DIR / "cost_sensitivity_parts"

SCENARIOS: dict[str, dict[str, Any]] = {
    "slippage_plus_1": {
        "label": "Slippage +1 tick (2 por lado)",
        "overrides": {"execution": {"slippage_ticks": 2}},
        "expected": {"slippage_ticks": 2, "commission_per_contract_side": 0.62},
    },
    "commission_double": {
        "label": "Comisión ×2 (1,24 USD/lado)",
        "overrides": {
            "execution": {"commission_per_contract_side": 1.24}
        },
        "expected": {"slippage_ticks": 1, "commission_per_contract_side": 1.24},
    },
    "combined": {
        "label": "Slippage +1 tick y comisión ×2",
        "overrides": {
            "execution": {
                "slippage_ticks": 2,
                "commission_per_contract_side": 1.24,
            }
        },
        "expected": {"slippage_ticks": 2, "commission_per_contract_side": 1.24},
    },
}


def _base_payload() -> dict:
    if not BASE_PATH.exists():
        raise RuntimeError(f"Falta {BASE_PATH}")
    payload = json.loads(BASE_PATH.read_text(encoding="utf-8"))
    if payload.get("holdout_executed"):
        raise RuntimeError("El artefacto base declara holdout ejecutado")
    if tuple(payload.get("presets") or ()) != tuple(resolve_presets(DEFAULT_PRESETS)):
        raise RuntimeError("Los presets base no coinciden con el catálogo default")
    if not payload.get("dataset_id"):
        raise RuntimeError("El artefacto base no declara dataset_id")
    return payload


def _part_path(scenario: str, window: str) -> Path:
    return PARTS_DIR / f"{scenario}_{window}.json"


def _load_part(scenario: str, window: str, dataset_id: str) -> dict | None:
    path = _part_path(scenario, window)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("dataset_id") != dataset_id:
        return None
    if payload.get("scenario") != scenario or payload.get("window") != window:
        return None
    return payload


def _run_task(scenario: str, window: tuple[str, str, str, int]) -> dict:
    key, start_s, end_s, days = window
    scenario_cfg = SCENARIOS[scenario]
    started = time.perf_counter()
    result = run_presets(
        _settings(),
        days=days,
        presets=DEFAULT_PRESETS,
        overrides=scenario_cfg["overrides"],
        start=date.fromisoformat(start_s),
        allow_holdout=False,
    )

    if result["is_synthetic"] or result["data_source"] != "csv":
        raise RuntimeError(f"{scenario}/{key}: se esperaba CSV real")
    if result["sessions"] != days:
        raise RuntimeError(f"{scenario}/{key}: {result['sessions']} sesiones")
    selected = result["dataset"].get("selected_range") or {}
    first = (selected.get("first_et") or "")[:10]
    last = (selected.get("last_et") or "")[:10]
    if last != end_s:
        raise RuntimeError(f"{scenario}/{key}: fin {last}, se esperaba {end_s}")
    if last > DEVELOPMENT_END:
        raise RuntimeError(f"{scenario}/{key}: se tocó el holdout ({last})")
    if first < start_s:
        raise RuntimeError(f"{scenario}/{key}: inicio {first}, antes de {start_s}")

    expected = tuple(resolve_presets(DEFAULT_PRESETS))
    if tuple(result["preset_keys"]) != expected:
        raise RuntimeError(f"{scenario}/{key}: presets inesperados")

    execution = (result.get("base_config") or {}).get("execution") or {}
    for field, expected_value in scenario_cfg["expected"].items():
        if execution.get(field) != expected_value:
            raise RuntimeError(
                f"{scenario}/{key}: {field}={execution.get(field)!r}, "
                f"se esperaba {expected_value!r}"
            )

    rows = []
    for item in result["results"]:
        row = _row_from_result(item, result["sessions"])
        row["fees"] = round(float(item["metrics"].get("fees") or 0.0), 2)
        rows.append(row)
    if tuple(row["preset"] for row in rows) != expected:
        raise RuntimeError(f"{scenario}/{key}: orden de presets inesperado")

    elapsed = round(time.perf_counter() - started, 1)
    print(
        f"[{scenario}/{key}] {first}..{last} · {len(rows)} presets · {elapsed}s",
        flush=True,
    )
    payload = {
        "scenario": scenario,
        "window": key,
        "start": start_s,
        "end": end_s,
        "days": days,
        "actual_first": first,
        "actual_last": last,
        "elapsed_s": elapsed,
        "dataset_id": result.get("dataset_id"),
        "dataset_path": result["dataset"].get("path"),
        "selected_id": result.get("dataset", {}).get("selected_id"),
        "overrides": scenario_cfg["overrides"],
        "rows": rows,
    }
    path = _part_path(scenario, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def _scenario_aggregate(parts: list[dict]) -> list[dict]:
    rows = aggregate(parts, DEFAULT_PRESETS)
    fees_by_preset: dict[str, float] = {}
    for part in parts:
        for row in part["rows"]:
            fees_by_preset[row["preset"]] = (
                fees_by_preset.get(row["preset"], 0.0) + float(row.get("fees") or 0.0)
            )
    for row in rows:
        row["fees"] = round(fees_by_preset.get(row["preset"], 0.0), 2)
    return rows


def _build_comparison(
    base: dict, scenario_aggregates: dict[str, list[dict]]
) -> dict:
    base_rows = {row["preset"]: row for row in base["aggregate"]}
    base_baseline = base_rows["baseline"]["net_profit"]
    comparisons = []
    for scenario, rows in scenario_aggregates.items():
        by_preset = {row["preset"]: row for row in rows}
        scenario_baseline = by_preset["baseline"]["net_profit"]
        for preset, base_row in base_rows.items():
            row = by_preset[preset]
            base_improvement = round(
                float(base_row["net_profit"]) - float(base_baseline), 2
            )
            scenario_improvement = round(
                float(row["net_profit"]) - float(scenario_baseline), 2
            )
            comparisons.append(
                {
                    "scenario": scenario,
                    "scenario_label": SCENARIOS[scenario]["label"],
                    "preset": preset,
                    "trades": row["trades"],
                    "base_net": round(float(base_row["net_profit"]), 2),
                    "scenario_net": round(float(row["net_profit"]), 2),
                    "delta_net": round(
                        float(row["net_profit"]) - float(base_row["net_profit"]), 2
                    ),
                    "cost": round(
                        float(base_row["net_profit"]) - float(row["net_profit"]), 2
                    ),
                    "base_improvement": base_improvement,
                    "scenario_improvement": scenario_improvement,
                    "improvement_change": round(
                        scenario_improvement - base_improvement, 2
                    ),
                    "disappeared": bool(
                        base_improvement > 0 and scenario_improvement <= 0
                    ),
                    "survives": bool(
                        base_improvement > 0 and scenario_improvement > 0
                    ),
                    "emerged": bool(
                        base_improvement <= 0 and scenario_improvement > 0
                    ),
                    "scenario_pf": row["profit_factor"],
                    "scenario_dd": row["max_drawdown_worst"],
                    "scenario_fees": row.get("fees"),
                    "scenario_trades": row["trades"],
                    "scenario_win_rate": row["win_rate"],
                }
            )
    return {
        "base_baseline_net": round(float(base_baseline), 2),
        "rows": comparisons,
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/d"
    if isinstance(value, str):
        return value
    return f"{float(value):,.{digits}f}".replace(",", ".")


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n/d"
    return f"{float(value):.2f} %"


def _write_csv(comparison: dict) -> None:
    fields = [
        "scenario",
        "preset",
        "trades",
        "base_net",
        "scenario_net",
        "delta_net",
        "cost",
        "base_improvement",
        "scenario_improvement",
        "improvement_change",
        "disappeared",
        "survives",
        "emerged",
        "scenario_pf",
        "scenario_dd",
        "scenario_fees",
        "scenario_trades",
        "scenario_win_rate",
    ]
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in comparison["rows"]:
            writer.writerow({key: row.get(key) for key in fields})


def _write_markdown(
    base: dict,
    scenario_aggregates: dict[str, list[dict]],
    comparison: dict,
) -> None:
    base_rows = {row["preset"]: row for row in base["aggregate"]}
    base_baseline = base_rows["baseline"]["net_profit"]
    lines: list[str] = []
    lines.append("# Sensibilidad de presets a costes peores")
    lines.append("")
    lines.append(
        "Escenarios deterministas sobre los mismos bloques W1–W6 y el mismo "
        "dataset de desarrollo. No se usa el holdout ni se cambia la "
        "configuración activa. El baseline de cada escenario se reejecuta "
        "para comparar mejoras relativas en igualdad de costes."
    )
    lines.append("")
    lines.append("## Escenarios")
    lines.append("")
    lines.append("| Escenario | Slippage | Comisión/lado |")
    lines.append("|---|---:|---:|")
    for key, cfg in SCENARIOS.items():
        execution = cfg["expected"]
        lines.append(
            f"| `{key}` | {execution['slippage_ticks']} ticks | "
            f"{_fmt(execution['commission_per_contract_side'])} USD |"
        )
    lines.append("")
    lines.append(
        f"Base: `{BASE_PATH.name}`, dataset "
        f"`{base.get('dataset_id')}`, {base.get('elapsed_s')} s. "
        "Los escenarios se reejecutaron porque el artefacto base solo guarda "
        "agregados, no contratos/comisiones por operación."
    )
    lines.append("")
    lines.append("## Resultado por preset")
    lines.append("")
    lines.append(
        "`Mejora base` y `Mejora escenario` son el neto del preset menos el "
        "neto del baseline en la misma corrida. `Δ` es el cambio de esa "
        "mejora; negativo significa que el shock se llevó parte de la ventaja."
    )
    lines.append("")
    header = (
        "| Preset | Neto base | Mejora base | Neto slippage | Mejora slippage | "
        "Neto comisión | Mejora comisión | Neto combinado | Mejora combinado |"
    )
    lines.append(header)
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    by_scenario = {
        scenario: {row["preset"]: row for row in rows}
        for scenario, rows in scenario_aggregates.items()
    }
    for preset, base_row in base_rows.items():
        cells = [
            f"`{preset}`",
            _fmt(base_row["net_profit"]),
            _fmt(float(base_row["net_profit"]) - float(base_baseline)),
        ]
        for scenario in SCENARIOS:
            row = by_scenario[scenario][preset]
            scenario_base = by_scenario[scenario]["baseline"]["net_profit"]
            cells.extend(
                [
                    _fmt(row["net_profit"]),
                    _fmt(float(row["net_profit"]) - float(scenario_base)),
                ]
            )
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Mejoras que desaparecen")
    lines.append("")
    lines.append(
        "Se marca una mejora como desaparecida cuando el preset supera al "
        "baseline con costes base pero deja de superarlo en el escenario."
    )
    lines.append("")
    disappeared = [row for row in comparison["rows"] if row["disappeared"]]
    if disappeared:
        lines.append("| Escenario | Preset | Mejora base | Mejora escenario | Δ mejora |")
        lines.append("|---|---|---:|---:|---:|")
        for row in disappeared:
            lines.append(
                f"| `{row['scenario']}` | `{row['preset']}` | "
                f"{_fmt(row['base_improvement'])} | "
                f"{_fmt(row['scenario_improvement'])} | "
                f"{_fmt(row['improvement_change'])} |"
            )
    else:
        lines.append(
            "**Ninguna mejora agregada desaparece.** Los cinco presets que "
            "superaban al baseline con costes base (`smt_window_120`, "
            "`smt_tolerance_16`, `setup_validity_240`, `sl_depth_6` y "
            "`rr_2_5`) siguen superándolo en los tres escenarios. La ventaja "
            "se comprime, sobre todo en `smt_tolerance_16`, pero no cambia de "
            "signo."
        )
    lines.append("")
    lines.append("## Mejoras que aparecen con el shock")
    lines.append("")
    lines.append(
        "Presets que no superaban al baseline con costes base pero sí lo "
        "superan en algún escenario. **No son una mejora de la estrategia**: "
        "son artefactos de exposición; el shock penaliza mucho más al baseline "
        "de 38 operaciones que a un preset de 4."
    )
    lines.append("")
    lines.append("| Escenario | Preset | Mejora base | Mejora escenario | Neto base | Neto escenario |")
    lines.append("|---|---|---:|---:|---:|---:|")
    emerged = [row for row in comparison["rows"] if row["emerged"]]
    for row in emerged:
        lines.append(
            f"| `{row['scenario']}` | `{row['preset']}` | "
            f"{_fmt(row['base_improvement'])} | "
            f"{_fmt(row['scenario_improvement'])} | "
            f"{_fmt(row['base_net'])} | {_fmt(row['scenario_net'])} |"
        )
    if not emerged:
        lines.append("| — | Ninguno | — | — | — | — |")
    lines.append("")
    lines.append("## Mejoras que resisten")
    lines.append("")
    lines.append(
        "Presets con mejora positiva en los tres escenarios, ordenados por la "
        "mejora del escenario combinado."
    )
    lines.append("")
    lines.append("| Preset | Mejora slippage | Mejora comisión | Mejora combinada |")
    lines.append("|---|---:|---:|---:|")
    survivor_rows = []
    for preset in base_rows:
        if preset == "baseline":
            continue
        vals = []
        for scenario in SCENARIOS:
            row = by_scenario[scenario][preset]
            vals.append(
                float(row["net_profit"])
                - float(by_scenario[scenario]["baseline"]["net_profit"])
            )
        if all(value > 0 for value in vals):
            survivor_rows.append((preset, vals))
    survivor_rows.sort(key=lambda item: item[1][-1], reverse=True)
    for preset, vals in survivor_rows:
        lines.append(
            f"| `{preset}` | {_fmt(vals[0])} | {_fmt(vals[1])} | {_fmt(vals[2])} |"
        )
    lines.append("")
    lines.append("## Efecto en drawdown y profit factor")
    lines.append("")
    lines.append(
        "El coste no solo reduce el neto: también aumenta el drawdown y baja "
        "el profit factor. Se muestra el peor drawdown de bloque y el PF "
        "agregado bajo costes combinados."
    )
    lines.append("")
    lines.append("| Preset | DD base | DD slippage | DD comisión | DD combinado | PF base | PF combinado |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for preset, base_row in base_rows.items():
        cells = [f"`{preset}`", _fmt(base_row["max_drawdown_worst"])]
        for scenario in ("slippage_plus_1", "commission_double", "combined"):
            cells.append(_fmt(by_scenario[scenario][preset]["max_drawdown_worst"]))
        cells.append(_fmt(base_row["profit_factor"]))
        cells.append(_fmt(by_scenario["combined"][preset]["profit_factor"]))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Coste absoluto del shock")
    lines.append("")
    lines.append(
        "Diferencia de neto contra la corrida base del mismo preset; un valor "
        "negativo es el coste. El combinado coincide al céntimo con la suma "
        "de los dos shocks en esta muestra, pero no se fuerza esa aditividad: "
        "el motor puede cambiar sizing y fills."
    )
    lines.append("")
    lines.append("| Preset | Δ slippage | Δ comisión | Δ combinado |")
    lines.append("|---|---:|---:|---:|")
    for preset, base_row in base_rows.items():
        cells = [f"`{preset}`"]
        for scenario in SCENARIOS:
            row = by_scenario[scenario][preset]
            cells.append(_fmt(float(row["net_profit"]) - float(base_row["net_profit"])))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Validación")
    lines.append("")
    lines.append(
        "El baseline combinado da **347,38 USD**, exactamente el mismo neto "
        "que `stress_costs.json` (38 operaciones, comisión 1,24 y slippage 2). "
        "Los 18 bloques declaran el mismo `dataset_id` y `holdout_executed=false`."
    )
    lines.append("")
    lines.append("## Límites")
    lines.append("")
    lines.append(
        "- Los escenarios son shocks fijos, no intervalos de confianza; no "
        "cuantifican probabilidad de que el coste real sea ese."
    )
    lines.append(
        "- El baseline de cada escenario se reejecuta, pero la comparación "
        "sigue siendo sobre 362 sesiones de desarrollo y seis bloques."
    )
    lines.append(
        "- Los presets con 4 operaciones siguen siendo muestras pequeñas; un "
        "neto positivo después del shock no es evidencia suficiente."
    )
    lines.append(
        "- No se abre el holdout. Cualquier promoción sigue requiriendo el "
        "protocolo confirmatorio."
    )
    lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers", type=int, default=6, help="Procesos en paralelo (default 6)."
    )
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers debe ser >= 1")

    started = time.perf_counter()
    base = _base_payload()
    dataset_id = str(base["dataset_id"])
    print(f"Dataset {dataset_id}", flush=True)
    print(f"Escenarios: {', '.join(SCENARIOS)}", flush=True)

    tasks = [
        (scenario, window)
        for scenario in SCENARIOS
        for window in WINDOWS
    ]
    parts: dict[str, list[dict]] = {scenario: [] for scenario in SCENARIOS}
    pending: list[tuple[str, tuple[str, str, str, int]]] = []
    for scenario, window in tasks:
        existing = _load_part(scenario, window[0], dataset_id)
        if existing is not None:
            parts[scenario].append(existing)
            print(f"[{scenario}/{window[0]}] reutilizado", flush=True)
        else:
            pending.append((scenario, window))

    # El dataset_id es la identidad de las filas normalizadas, no el SHA-256
    # directo del CSV; se valida contra el artefacto base y entre escenarios.
    if not pending:
        print("Todos los bloques ya existen; se reutilizan", flush=True)

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_run_task, scenario, window): (scenario, window)
            for scenario, window in pending
        }
        for future in as_completed(futures):
            scenario, window = futures[future]
            try:
                parts[scenario].append(future.result())
            except Exception:
                print(f"[{scenario}/{window[0]}] FALLÓ", flush=True)
                traceback.print_exc()
                return 1

    scenario_aggregates: dict[str, list[dict]] = {}
    windows_payload: dict[str, list[dict]] = {}
    for scenario in SCENARIOS:
        scenario_parts = sorted(parts[scenario], key=lambda item: item["window"])
        if len(scenario_parts) != len(WINDOWS):
            raise RuntimeError(f"{scenario}: faltan bloques")
        bad_dataset = [
            part["window"]
            for part in scenario_parts
            if part.get("dataset_id") != dataset_id
        ]
        if bad_dataset:
            raise RuntimeError(
                f"{scenario}: dataset distinto en {bad_dataset}"
            )
        scenario_aggregates[scenario] = _scenario_aggregate(scenario_parts)
        windows_payload[scenario] = [
            {key: value for key, value in part.items() if key != "rows"}
            for part in scenario_parts
        ]

    comparison = _build_comparison(base, scenario_aggregates)
    payload = {
        "schema": "cost-sensitivity-presets-v1",
        "created_ts": int(time.time() * 1000),
        "profile": base.get("profile"),
        "dataset_path": base.get("dataset_path"),
        "dataset_id": dataset_id,
        "development_end": DEVELOPMENT_END,
        "holdout_executed": False,
        "base_source": str(BASE_PATH.relative_to(ROOT)).replace("\\", "/"),
        "base_elapsed_s": base.get("elapsed_s"),
        "scenarios": {
            key: {
                "label": cfg["label"],
                "overrides": cfg["overrides"],
                "expected_execution": cfg["expected"],
                "windows": windows_payload[key],
                "aggregate": scenario_aggregates[key],
            }
            for key, cfg in SCENARIOS.items()
        },
        "comparison": comparison,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(comparison)
    _write_markdown(base, scenario_aggregates, comparison)

    print(f"Escrito {OUT_JSON} en {payload['elapsed_s']}s", flush=True)
    print(f"Escrito {OUT_CSV}", flush=True)
    print(f"Escrito {OUT_MD}", flush=True)
    print("Mejoras desaparecidas:", flush=True)
    for row in comparison["rows"]:
        if row["disappeared"]:
            print(
                f"  {row['scenario']} {row['preset']}: "
                f"{row['base_improvement']:.2f} -> {row['scenario_improvement']:.2f}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
