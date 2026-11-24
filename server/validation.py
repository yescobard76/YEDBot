"""Carga y valida el informe de decisión forward.

El informe es un artefacto de investigación versionado en el repositorio. La API
solo lo sirve; no ejecuta backtests ni escribe en la base de datos.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import BASE_DIR

REPORT_PATH = BASE_DIR / "reports" / "backtest" / "forward_validation.json"
SCHEMA = "forward-validation-v1"


class ValidationReportError(ValueError):
    """El informe existe pero no cumple el contrato mínimo."""


def load_forward_validation(path: Path | None = None) -> dict[str, Any]:
    """Devuelve el informe validado o lanza una excepción explícita.

    ``FileNotFoundError`` significa que aún no se generó el artefacto;
    ``ValidationReportError`` significa que está corrupto o es de otro schema.
    """

    target = Path(path) if path is not None else REPORT_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValidationReportError(f"JSON de validación inválido: {exc}") from exc

    if not isinstance(data, dict):
        raise ValidationReportError("El informe de validación debe ser un objeto")
    if data.get("schema") != SCHEMA:
        raise ValidationReportError(
            f"Schema inesperado: {data.get('schema')!r}; se esperaba {SCHEMA!r}"
        )
    required = ("decision", "forward", "holdout", "development", "candidates")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValidationReportError(
            "Faltan secciones obligatorias: " + ", ".join(sorted(missing))
        )
    candidates = data["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ValidationReportError("candidates debe ser una lista no vacía")
    ids = {item.get("id") for item in candidates if isinstance(item, dict)}
    expected = {"baseline_manual", "p2", "p2_be_1r"}
    if not expected <= ids:
        raise ValidationReportError(
            "Faltan candidatos: " + ", ".join(sorted(expected - ids))
        )
    if data["decision"].get("kind") not in {"keep_current", "adopt_candidate"}:
        raise ValidationReportError("decision.kind no reconocido")
    if not isinstance(data["holdout"].get("executed"), bool):
        raise ValidationReportError("holdout.executed debe ser booleano")
    return data
