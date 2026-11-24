"""Pre-registro E-ATR-1: stop normalizado por ATR con sizing al 1 %.

Este módulo solo carga y verifica el lock. No ejecuta backtests, no lee datos
de mercado y no modifica la configuración activa.

El experimento compara dos brazos sobre la misma muestra externa:

- control: stop estructural, configuración 150/12/200;
- tratamiento: ``strategy.sl_mode = "atr"`` con ATR(14) de 15m y
  ``atr_sl_mult = 1.2``.

El sizing usa el 1 % del equity **planificado en la señal** y el objetivo se
mantiene en 3R. El tope de 200 ticks se mantiene en ambos brazos como guardia
de elegibilidad previa al sizing; el 1 % es el único presupuesto de tamaño, no
un permiso para stops más anchos. El riesgo efectivo al fill se mide después y
debe pasar el gate de tolerancia por slippage máximo; el gate no modifica el
target. El lock también congela los hashes de los archivos que implementan el
stop ATR; un lock de ejecución debe verificarlos con
``verify_execution_lock_provenance``. La muestra externa todavía no está
asignada; por eso ``assert_execution_blocked`` siempre falla en este lock.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = ROOT / "docs" / "experimento_stop_atr.lock.json"

PAYLOAD_KEYS: tuple[str, ...] = (
    "experiment",
    "execution_gate",
    "code_provenance",
    "arms",
    "frozen",
    "rule",
    "sample",
    "analysis",
    "decision",
)
EXPECTED_STATUS = "pre_registered_not_executed"
EXPERIMENT_ID = "E-ATR-1"
CODE_PROVENANCE_ALGORITHM = "sha256-files-v1"
ATR_STOP_CODE_FILES: tuple[str, ...] = (
    "server/strategy/indicators.py",
    "server/strategy/strategy.py",
)
ATR_STOP_ENTRYPOINTS: tuple[str, ...] = (
    "ORBStrategy.evaluate",
    "ORBStrategy._stop",
    "atr",
    "true_range",
    "aggregate",
)
PREREGISTRATION_LOCK_PATH = "docs/experimento_stop_atr.lock.json"


class StopAtrLockError(ValueError):
    """El lock E-ATR-1 no coincide con el pre-registro congelado."""


def _payload(lock: Mapping[str, Any]) -> dict[str, Any]:
    missing = [key for key in PAYLOAD_KEYS if key not in lock]
    if missing:
        raise StopAtrLockError(f"Lock incompleto: faltan {', '.join(missing)}")
    return {key: lock[key] for key in PAYLOAD_KEYS}


def payload_sha256(lock: Mapping[str, Any]) -> str:
    """Hash canónico del payload, sin el propio campo de hash."""
    encoded = json.dumps(
        _payload(lock),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def control_overrides() -> dict[str, Any]:
    """El control no cambia ningún parámetro."""
    return {}


def treatment_overrides() -> dict[str, Any]:
    """El tratamiento cambia solo el modo de stop."""
    return {"strategy": {"sl_mode": "atr"}}


def effective_fill_risk_gate(
    *,
    equity: float,
    qty_filled: int,
    effective_fill_risk: float,
    tick_value: float,
    max_slippage_ticks: int,
    risk_per_trade_pct: float = 1.0,
) -> tuple[bool, float]:
    """Evalúa el riesgo efectivo al fill contra el 1 % más slippage máximo.

    El 1 % de E-ATR-1 es un presupuesto **planificado**; el fill puede empeorar
    la distancia al stop. La tolerancia se fija con ``max_slippage_ticks``, no
    con el slippage observado. Devuelve ``(pasa, límite_permitido)``.
    """
    budget = max(equity, 0.0) * risk_per_trade_pct / 100
    tolerance = max(qty_filled, 0) * max(max_slippage_ticks, 0) * max(tick_value, 0.0)
    allowed = budget + tolerance
    return effective_fill_risk <= allowed + 1e-9, allowed


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StopAtrLockError(message)


def compute_code_provenance(
    root: str | Path = ROOT,
    files: Sequence[str] = ATR_STOP_CODE_FILES,
) -> dict[str, Any]:
    """SHA-256 de los archivos completos que implementan el stop ATR.

    ``files`` se normaliza a orden lexicográfico. El hash combinado incluye
    ruta y contenido de cada archivo, con longitudes explícitas para evitar
    concatenaciones ambiguas. No sigue imports ni hashea código no incluido.
    """
    base = Path(root).resolve()
    scope = tuple(sorted(str(item).replace("\\", "/") for item in files))
    _require(bool(scope), "La procedencia del código no puede estar vacía")
    digests: dict[str, str] = {}
    digest = hashlib.sha256()
    digest.update(b"yed-e-atr-1-code-files-v1\0")
    for relative in scope:
        path = (base / relative).resolve()
        _require(
            path.is_file() and base in path.parents,
            f"No existe el archivo de código congelado: {relative}",
        )
        data = path.read_bytes()
        digests[relative] = hashlib.sha256(data).hexdigest()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return {
        "algorithm": CODE_PROVENANCE_ALGORITHM,
        "scope": list(scope),
        "entrypoints": list(ATR_STOP_ENTRYPOINTS),
        "files": digests,
        "combined_sha256": digest.hexdigest(),
    }


def verify_execution_lock_provenance(
    execution_lock: Mapping[str, Any],
    *,
    root: str | Path = ROOT,
    prereg_lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verifica que un lock de ejecución use exactamente el código congelado.

    No ejecuta el experimento, no valida la muestra y no autoriza el holdout.
    El lock de ejecución debe incluir ``pre_registration`` con el hash del
    payload pre-registrado y el hash combinado del código, además de una copia
    exacta de ``code_provenance``. También se recalculan los archivos actuales:
    un lock con hashes correctos pero código modificado no pasa.
    """
    base = load_stop_atr_lock() if prereg_lock is None else prereg_lock
    requirements = ((base.get("execution_gate") or {}).get("execution_lock_requirements") or {})
    _require(
        requirements.get("code_provenance") == "exact_copy_and_recompute",
        "El pre-registro debe exigir copiar y recalcular el code_provenance",
    )
    _require(
        requirements.get("pre_registration_binding")
        == "payload_sha256_and_code_sha256",
        "El pre-registro debe exigir el binding al payload y al código",
    )
    expected = base.get("code_provenance") or {}
    actual = execution_lock.get("code_provenance")
    _require(
        isinstance(actual, Mapping),
        "El lock de ejecución debe incluir code_provenance",
    )
    binding = execution_lock.get("pre_registration")
    _require(
        isinstance(binding, Mapping),
        "El lock de ejecución debe incluir pre_registration",
    )
    _require(
        binding.get("path") == PREREGISTRATION_LOCK_PATH,
        "El lock de ejecución debe apuntar al pre-registro E-ATR-1",
    )
    _require(
        binding.get("payload_sha256") == base.get("payload_sha256"),
        "El lock de ejecución no está vinculado al payload pre-registrado",
    )
    _require(
        binding.get("code_provenance_sha256") == expected.get("combined_sha256"),
        "El lock de ejecución no está vinculado al hash de código pre-registrado",
    )
    _require(
        actual == expected,
        "El code_provenance del lock de ejecución no coincide con el pre-registro",
    )
    current = compute_code_provenance(root, expected.get("scope") or ())
    _require(
        current == expected,
        "El código actual no coincide con el code_provenance pre-registrado",
    )
    return current


def load_stop_atr_lock(
    path: str | Path = DEFAULT_LOCK_PATH,
) -> dict[str, Any]:
    """Carga el lock y rechaza alteraciones o un estado ejecutable."""
    target = Path(path)
    try:
        raw = json.loads(target.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:  # pragma: no cover - entorno incompleto
        raise StopAtrLockError(f"No existe el lock: {target}") from exc
    _require(isinstance(raw, dict), "El lock debe ser un objeto JSON")
    lock: dict[str, Any] = raw  # type: ignore[assignment]

    expected = lock.get("payload_sha256")
    _require(
        isinstance(expected, str) and bool(expected),
        "El lock no declara payload_sha256",
    )
    actual = payload_sha256(lock)
    _require(
        actual == expected,
        f"Payload del lock alterado: esperado {expected}, calculado {actual}",
    )

    experiment = lock.get("experiment") or {}
    _require(
        experiment.get("id") == EXPERIMENT_ID,
        f"El lock no es {EXPERIMENT_ID}",
    )
    _require(
        experiment.get("status") == EXPECTED_STATUS,
        "El lock no está en estado pre_registered_not_executed",
    )
    _require(
        experiment.get("only_change") == "strategy.sl_mode",
        "El experimento debe cambiar solo strategy.sl_mode",
    )

    gate = lock.get("execution_gate") or {}
    _require(
        gate.get("can_execute") is False,
        "El lock declara can_execute=true; no es un pre-registro bloqueado",
    )
    _require(
        gate.get("external_sample_required") is True,
        "El lock debe exigir muestra externa",
    )
    _require(
        gate.get("requires_new_execution_lock") is True,
        "El lock debe exigir un lock de ejecución nuevo",
    )
    execution_requirements = gate.get("execution_lock_requirements") or {}
    _require(
        execution_requirements.get("code_provenance") == "exact_copy_and_recompute",
        "El lock debe exigir copiar y recalcular el code_provenance",
    )
    _require(
        execution_requirements.get("pre_registration_binding")
        == "payload_sha256_and_code_sha256",
        "El lock debe vincular payload y hash de código",
    )
    _require(
        execution_requirements.get("on_mismatch") == "reject_execution",
        "Un desajuste de código debe rechazar la ejecución",
    )
    provenance = lock.get("code_provenance") or {}
    _require(
        provenance.get("algorithm") == CODE_PROVENANCE_ALGORITHM,
        "El algoritmo de procedencia del código no es el esperado",
    )
    _require(
        provenance.get("scope") == list(ATR_STOP_CODE_FILES),
        "La procedencia debe cubrir exactamente los archivos del stop ATR",
    )
    _require(
        provenance.get("entrypoints") == list(ATR_STOP_ENTRYPOINTS),
        "La procedencia debe declarar los puntos de entrada del stop ATR",
    )
    current_provenance = compute_code_provenance(
        ROOT, provenance.get("scope") or ()
    )
    _require(
        provenance == current_provenance,
        "El código del stop ATR no coincide con el code_provenance del lock",
    )

    arms = lock.get("arms") or {}
    _require(
        arms.get("control", {}).get("overrides") == control_overrides(),
        "El control no puede tener overrides",
    )
    _require(
        arms.get("treatment", {}).get("overrides") == treatment_overrides(),
        "El tratamiento debe cambiar solo strategy.sl_mode a 'atr'",
    )

    frozen = lock.get("frozen") or {}
    strategy = frozen.get("strategy") or {}
    risk = frozen.get("risk") or {}
    rule = lock.get("rule") or {}
    stop_rule = rule.get("stop") or {}
    sizing_rule = rule.get("sizing") or {}
    _require(strategy.get("atr_period") == 14, "ATR period debe ser 14")
    _require(
        strategy.get("atr_sl_mult") == 1.2,
        "ATR multiplier debe ser 1.2",
    )
    _require(strategy.get("tp_rr") == 3.0, "El objetivo debe ser 3R")
    _require(
        risk.get("risk_per_trade_pct") == 1.0,
        "El riesgo por operación debe ser 1.0 %",
    )
    _require(risk.get("max_contracts") == 5, "max_contracts debe ser 5")
    _require(risk.get("max_sl_ticks") == 200, "max_sl_ticks debe ser 200")
    _require(stop_rule.get("max_sl_ticks") == 200, "rule.stop.max_sl_ticks debe ser 200")
    _require(
        stop_rule.get("max_sl_ticks_policy")
        == "both_arms_before_sizing_reject_stop_cap",
        "El tope debe aplicarse a ambos brazos antes del sizing",
    )
    _require(
        sizing_rule.get("risk_basis") == "planned_at_signal",
        "El 1 % debe definirse como riesgo planificado en la señal",
    )
    _require(
        str(sizing_rule.get("qty", "")).startswith("floor("),
        "El tamaño debe usar floor sobre el presupuesto de riesgo",
    )
    fill_gate = sizing_rule.get("effective_fill_risk_gate") or {}
    _require(
        fill_gate.get("budget") == "equity_actual * risk_per_trade_pct / 100",
        "El gate debe usar el 1 % del equity como presupuesto",
    )
    _require(
        fill_gate.get("tolerance") == "qty_filled * max_slippage_ticks * tick_value",
        "La tolerancia debe cubrir el slippage máximo por contrato",
    )
    _require(
        fill_gate.get("pass_if") == "actual_fill_risk <= budget + tolerance",
        "El gate debe comparar el riesgo efectivo con presupuesto + tolerancia",
    )
    _require(
        fill_gate.get("on_exceed") == "integrity_failure",
        "Superar el gate debe ser un fallo de integridad",
    )
    _require(
        fill_gate.get("target_3r_unchanged") is True,
        "El gate no puede modificar el objetivo 3R",
    )
    target_rule = rule.get("target") or {}
    _require(target_rule.get("tp_rr") == 3.0, "El target debe ser 3R")
    _require(
        target_rule.get("no_trailing") is True
        and target_rule.get("no_break_even") is True,
        "El experimento no puede introducir trailing ni break-even",
    )
    analysis = lock.get("analysis") or {}
    integrity = analysis.get("integrity") or {}
    required_integrity = (
        "atr_positive_on_all_signals",
        "stop_distance_matches_atr_rule",
        "target_equals_3r",
        "planned_risk_at_most_1pct",
        "max_sl_ticks_checked_before_sizing",
        "effective_fill_risk_gate",
        "code_provenance_verified",
        "no_lookahead",
        "same_entry_rule_as_control",
    )
    missing_integrity = [key for key in required_integrity if integrity.get(key) is not True]
    _require(
        not missing_integrity,
        f"Integridad incompleta: {', '.join(missing_integrity)}",
    )

    sample = lock.get("sample") or {}
    _require(
        sample.get("status") == "pending",
        "La muestra externa debe seguir pendiente",
    )
    _require(
        sample.get("must_be_locked_before_observation") is True,
        "La muestra debe congelarse antes de observar resultados",
    )
    return lock


def assert_execution_blocked(
    lock: Mapping[str, Any] | None = None,
) -> None:
    """Falla siempre mientras no exista una muestra externa bloqueada.

    Esta función existe para que ningún ejecutor pueda confundir el
    pre-registro con una autorización de corrida.
    """
    current = load_stop_atr_lock() if lock is None else lock
    gate = current.get("execution_gate") or {}
    sample = current.get("sample") or {}
    if gate.get("can_execute") is not False:
        raise StopAtrLockError(
            "El lock declara ejecución habilitada; se requiere un lock nuevo"
        )
    if sample.get("status") != "pending":
        raise StopAtrLockError(
            "La muestra ya no está pendiente; se requiere un lock de ejecución nuevo"
        )
    raise StopAtrLockError(
        "Ejecución bloqueada: falta una muestra externa nueva. "
        "Fije fechas, dataset, contratos y hashes en un lock de ejecución "
        "antes de correr E-ATR-1."
    )
