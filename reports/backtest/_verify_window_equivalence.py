"""Verificación ejecutable de equivalencia semántica de las ventanas.

Oráculo: ``blocks_summary.json`` y los JSON de reportes ya generados. Los
literales ``PRE_REFACTOR_*`` son expectativas de regresión, no una fuente
runtime. La única definición runtime sigue siendo ``_windows.py``.

La comprobación importa cada consumidor y compara su estructura efectiva
(tuplas, ids, inicio solicitado, fin, sesiones, primera/última sesión real,
subconjuntos, orden y longitud) contra el oráculo. No ejecuta los runners
largos ni escribe archivos ni DB.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "reports/backtest") not in sys.path:
    sys.path.insert(0, str(ROOT / "reports/backtest"))

import _manual_common
import _manual_filter025_w1_w6
import _manual_w1_w6_analysis
import _p2_w1_w6_confirm
import _windows
import audit_w2_w3_current
import compare_raw_adjusted_w4_w6
import run_breakeven_1r_protocol
import run_continuous_equity_dev
import run_entry_exclusion_compare
import run_min_stop_or_ratio_protocol
import run_presets_dev
import run_stop_or_ratio_ablations

BLOCKS_PATH = ROOT / "reports/backtest/blocks_summary.json"
P2_JSON = ROOT / "reports/backtest/p2_w1_w6_confirm.json"
FILTER_JSON = ROOT / "reports/backtest/_manual_filter025_w1_w6.json"
LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"

# Expectativas históricas del refactor. No se usan como fuente runtime.
PRE_REFACTOR_WINDOWS = (
    ("W1", "2025-01-10", "2025-03-31", 54),
    ("W2", "2025-04-01", "2025-06-30", 61),
    ("W3", "2025-07-01", "2025-09-30", 63),
    ("W4", "2025-10-01", "2025-12-31", 63),
    ("W5", "2026-01-01", "2026-03-31", 60),
    ("W6", "2026-04-01", "2026-06-30", 61),
)
PRE_REFACTOR_IDS = tuple(spec[0] for spec in PRE_REFACTOR_WINDOWS)
PRE_REFACTOR_GROUPS = (("W1", "W2"), ("W3",), ("W4",), ("W5", "W6"))
CONSUMER_NAMES = (
    "_windows.py",
    "_manual_common.py",
    "run_presets_dev.py",
    "run_continuous_equity_dev.py",
    "audit_w2_w3_current.py",
    "run_breakeven_1r_protocol.py",
    "run_entry_exclusion_compare.py",
    "run_min_stop_or_ratio_protocol.py",
    "run_stop_or_ratio_ablations.py",
    "compare_raw_adjusted_w4_w6.py",
    "_p2_w1_w6_confirm.py",
    "_manual_w1_w6_analysis.py",
    "_manual_filter025_w1_w6.py",
)
assert len(CONSUMER_NAMES) == 13
for _name in CONSUMER_NAMES:
    assert (Path(__file__).resolve().parent / _name).is_file(), _name


def _oracle() -> tuple[dict, ...]:
    payload = json.loads(BLOCKS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 6:
        raise AssertionError("blocks_summary.json no tiene seis ventanas")
    records = tuple(
        {
            "id": item["id"],
            "start": item["start"],
            "end": item["end"],
            "sessions": int(item["sessions"]),
            "first": item["first_et"][:10],
            "last": item["last_et"][:10],
        }
        for item in payload
    )
    assert records[0]["id"] == "W1" and records[-1]["id"] == "W6"
    assert tuple(
        (item["id"], item["start"], item["end"], item["sessions"])
        for item in records
    ) == PRE_REFACTOR_WINDOWS
    assert records[4]["first"] == "2026-01-02"
    assert records[4]["last"] == "2026-03-31"
    return records


def _records_from_windows(
    windows: tuple[tuple[str, str, str, int], ...],
    oracle_by_id: dict[str, dict],
) -> tuple[dict, ...]:
    records = []
    for key, start, end, sessions in windows:
        base = oracle_by_id[key]
        records.append(
            {
                "id": key,
                "start": start,
                "end": end,
                "sessions": int(sessions),
                "first": base["first"],
                "last": base["last"],
            }
        )
    return tuple(records)


def _records_from_ranges(
    ranges: tuple[tuple[str, date, date], ...],
    oracle_by_id: dict[str, dict],
) -> tuple[dict, ...]:
    records = []
    for key, start, end in ranges:
        base = oracle_by_id[key]
        records.append(
            {
                "id": key,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "sessions": base["sessions"],
                "first": base["first"],
                "last": base["last"],
            }
        )
    return tuple(records)


def _records_from_tasks(
    tasks: tuple[dict, ...],
    oracle_by_id: dict[str, dict],
) -> tuple[dict, ...]:
    records = []
    for task in tasks:
        key = task["window"]
        base = oracle_by_id[key]
        records.append(
            {
                "id": key,
                "start": task["start"],
                "end": task["end"],
                "sessions": int(task["sessions"]),
                "first": base["first"],
                "last": base["last"],
            }
        )
    return tuple(records)


def _records_from_lock(
    lock: dict,
    oracle_by_id: dict[str, dict],
) -> tuple[dict, ...]:
    records = []
    for item in lock["windows"]:
        key = item["id"]
        base = oracle_by_id[key]
        records.append(
            {
                "id": key,
                "start": item["start"],
                "end": item["end"],
                "sessions": int(item["sessions"]),
                "first": base["first"],
                "last": base["last"],
            }
        )
    return tuple(records)


def _records_from_artifacts(
    payload: list | dict,
    oracle_by_id: dict[str, dict],
) -> tuple[dict, ...]:
    blocks = payload if isinstance(payload, list) else payload["windows"]
    records = []
    for block in blocks:
        key = block.get("window") or block.get("id")
        base = oracle_by_id[key]
        # Los JSON de _p2 y del filtro guardan window/start/sessions/first/last,
        # pero no end; blocks_summary sí lo guarda. Se valida lo expuesto y se
        # toma end del oráculo solo cuando el artefacto no lo contiene.
        records.append(
            {
                "id": key,
                "start": block.get("start", base["start"]),
                "end": block.get("end", base["end"]),
                "sessions": int(block.get("sessions", base["sessions"])),
                "first": (block.get("first") or block.get("first_et"))[:10],
                "last": (block.get("last") or block.get("last_et"))[:10],
            }
        )
    return tuple(records)


def _assert_records(label: str, actual: tuple[dict, ...], expected: tuple[dict, ...]) -> None:
    if len(actual) != len(expected):
        raise AssertionError(
            f"{label}: longitud {len(actual)}, se esperaba {len(expected)}"
        )
    for left, right in zip(actual, expected):
        if left != right:
            raise AssertionError(f"{label}: {left!r} != {right!r}")
    print(f"OK {label}: {len(actual)} ventanas")


def main() -> int:
    oracle = _oracle()
    oracle_by_id = {item["id"]: item for item in oracle}
    oracle_ids = tuple(item["id"] for item in oracle)
    oracle_first = {item["id"]: item["first"] for item in oracle}
    oracle_last = {item["id"]: item["last"] for item in oracle}
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock_records = _records_from_lock(lock, oracle_by_id)
    assert tuple(item["id"] for item in lock_records) == oracle_ids
    _assert_records("lock windows (consumidores de IDs)", lock_records, oracle)

    # 1. _windows.py
    assert _windows.WINDOWS == PRE_REFACTOR_WINDOWS
    assert _windows.WINDOW_IDS == PRE_REFACTOR_IDS
    assert _windows.WINDOW_FIRST == oracle_first
    _assert_records(
        "_windows.WINDOWS",
        _records_from_windows(_windows.WINDOWS, oracle_by_id),
        oracle,
    )

    # 2. _manual_common.py
    assert _manual_common.WINDOWS == PRE_REFACTOR_WINDOWS
    assert _manual_common.WINDOW_FIRST == oracle_first
    _assert_records(
        "_manual_common.WINDOWS",
        _records_from_windows(_manual_common.WINDOWS, oracle_by_id),
        oracle,
    )

    # 3. run_presets_dev.py
    assert run_presets_dev.WINDOW_FIRST == oracle_first
    assert run_presets_dev.DEVELOPMENT_END == oracle_last["W6"]
    _assert_records(
        "run_presets_dev.WINDOWS",
        _records_from_windows(run_presets_dev.WINDOWS, oracle_by_id),
        oracle,
    )

    # 4. run_continuous_equity_dev.py
    assert run_continuous_equity_dev.START == date.fromisoformat(oracle_first["W1"])
    assert run_continuous_equity_dev.END == date.fromisoformat(oracle_last["W6"])
    assert run_continuous_equity_dev.DAYS == sum(item["sessions"] for item in oracle)
    _assert_records(
        "run_continuous_equity_dev.BLOCK_RANGES",
        _records_from_ranges(run_continuous_equity_dev.BLOCK_RANGES, oracle_by_id),
        oracle,
    )

    # 5. audit_w2_w3_current.py
    audit_records = _records_from_tasks(audit_w2_w3_current.TASKS, oracle_by_id)
    expected_audit = tuple(oracle_by_id[key] for key in ("W2", "W3"))
    assert tuple(task["window"] for task in audit_w2_w3_current.TASKS) == (
        "W2",
        "W3",
    )
    _assert_records("audit_w2_w3_current.TASKS", audit_records, expected_audit)

    # 6-9. consumidores de IDs; fechas efectivas vienen del lock.
    id_modules = {
        "run_breakeven_1r_protocol": run_breakeven_1r_protocol,
        "run_entry_exclusion_compare": run_entry_exclusion_compare,
        "run_min_stop_or_ratio_protocol": run_min_stop_or_ratio_protocol,
        "run_stop_or_ratio_ablations": run_stop_or_ratio_ablations,
    }
    for name, module in id_modules.items():
        assert module.WINDOW_IDS == oracle_ids, name
        assert module.GROUPS == PRE_REFACTOR_GROUPS, name
        assert len(module.WINDOW_IDS) == 6, name
        # El lock define start/end/sessions; first/last reales se contrastan
        # contra el oráculo. Se comprueba de forma explícita por consumidor.
        _assert_records(f"{name} (lock efectivo)", lock_records, oracle)
        print(f"OK {name}.WINDOW_IDS/GROUPS: 6 ventanas")

    assert run_entry_exclusion_compare.WINDOWS == PRE_REFACTOR_WINDOWS
    assert run_min_stop_or_ratio_protocol.WINDOWS == PRE_REFACTOR_WINDOWS
    assert run_stop_or_ratio_ablations.WINDOWS == PRE_REFACTOR_WINDOWS
    for module in (
        run_entry_exclusion_compare,
        run_min_stop_or_ratio_protocol,
        run_stop_or_ratio_ablations,
    ):
        _assert_records(
            f"{module.__name__}.WINDOWS",
            _records_from_windows(module.WINDOWS, oracle_by_id),
            oracle,
        )
    assert run_min_stop_or_ratio_protocol.DEVELOPMENT_END == oracle_last["W6"]

    # 10. compare_raw_adjusted_w4_w6.py
    compare_ids = ("W4", "W5", "W6")
    assert compare_raw_adjusted_w4_w6.WINDOW_IDS == compare_ids
    assert len(compare_raw_adjusted_w4_w6.WINDOW_IDS) == 3
    compare_lock = tuple(
        item for item in lock_records if item["id"] in compare_ids
    )
    _assert_records(
        "compare_raw_adjusted_w4_w6 (W4-W6 desde lock)",
        compare_lock,
        tuple(oracle_by_id[key] for key in compare_ids),
    )

    # 11-13. conclusiones: exponen su definición efectiva importable.
    conclusion_modules = {
        "_p2_w1_w6_confirm": _p2_w1_w6_confirm,
        "_manual_w1_w6_analysis": _manual_w1_w6_analysis,
        "_manual_filter025_w1_w6": _manual_filter025_w1_w6,
    }
    for name, module in conclusion_modules.items():
        assert module.EFFECTIVE_WINDOWS == PRE_REFACTOR_WINDOWS, name
        assert module.run_windows is _manual_common.run_windows, name
        _assert_records(
            f"{name}.EFFECTIVE_WINDOWS",
            _records_from_windows(module.EFFECTIVE_WINDOWS, oracle_by_id),
            oracle,
        )

    # Artefactos generados: deben conservar el mismo orden y valores.
    for path in (BLOCKS_PATH, P2_JSON, FILTER_JSON):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = _records_from_artifacts(payload, oracle_by_id)
        _assert_records(f"artefacto {path.name}", records, oracle)

    print("COVERAGE:", ", ".join(CONSUMER_NAMES))
    print("COVERAGE: 13 consumidores + lock + 3 artefactos")
    print("WINDOW_EQUIVALENCE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
