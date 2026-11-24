"""Contrato OpenAPI versionado y tipos del frontend.

El snapshot ``tests/fixtures/openapi/v1.json`` es la línea base pública de la
API. El test compara el esquema actual contra esa versión y falla solo ante
cambios incompatibles (no ante adiciones). Si el cambio incompatible es
intencionado, se crea una nueva versión del snapshot y se actualiza
``SNAPSHOT_PATH``; nunca se sobrescribe la versión anterior.

Para regenerar la línea base actual tras revisar el diff::

    OPENAPI_UPDATE=1 python -m pytest tests/test_openapi_contract.py

No se genera código TypeScript ni se ejecuta ningún generador en runtime: el
test lee ``frontend/src/types.ts`` y comprueba sus campos contra los componentes
del esquema servido por FastAPI.
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi import FastAPI

from server import __version__
from server.api import router

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "tests" / "fixtures" / "openapi" / "v1.json"
FRONTEND_TYPES = ROOT / "frontend" / "src" / "types.ts"
JSON_MEDIA = "application/json"


def build_openapi() -> dict[str, Any]:
    """Esquema del router /api, sin arrancar motor, base de datos ni servidor."""
    app = FastAPI(title="YEDTradingBot", version=__version__)
    app.include_router(router, prefix="/api")
    return app.openapi()


def _resolve(schema: Any, root: dict[str, Any], depth: int = 0) -> Any:
    if not isinstance(schema, dict) or depth > 32:
        return schema
    ref = schema.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/components/schemas/"):
        return schema
    name = ref.rsplit("/", 1)[-1]
    target = ((root.get("components") or {}).get("schemas") or {}).get(name)
    if not isinstance(target, dict):
        return schema
    return _resolve(target, root, depth + 1)


def _properties(
    schema: Any, root: dict[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    resolved = _resolve(schema, root)
    if not isinstance(resolved, dict):
        return {}, set()
    properties = dict(resolved.get("properties") or {})
    required = set(resolved.get("required") or [])
    for part in resolved.get("allOf") or []:
        part_properties, part_required = _properties(part, root)
        properties.update(part_properties)
        required |= part_required
    return properties, required


def _signature(schema: Any, root: dict[str, Any], depth: int = 0) -> Any:
    """Firma estructural estable para comparar tipos sin depender del orden."""
    if not isinstance(schema, dict):
        return ("any",)
    if "$ref" in schema:
        return ("ref", schema["$ref"])
    if depth > 12:
        return ("deep",)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return (
                key,
                tuple(sorted(_signature(item, root, depth + 1) for item in schema[key])),
            )
    if "type" in schema:
        parts: list[Any] = [schema["type"]]
        if schema.get("format"):
            parts.append(schema["format"])
        if schema.get("enum") is not None:
            parts.append(tuple(sorted(str(value) for value in schema["enum"])))
        for constraint in (
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "minLength",
            "maxLength",
            "pattern",
            "minItems",
            "maxItems",
            "multipleOf",
        ):
            if constraint in schema:
                parts.append((constraint, schema[constraint]))
        if schema["type"] == "array":
            parts.append(_signature(schema.get("items") or {}, root, depth + 1))
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            parts.append(_signature(additional, root, depth + 1))
        return tuple(parts)
    if "additionalProperties" in schema:
        return ("map", _signature(schema["additionalProperties"], root, depth + 1))
    return ("any",)


def _request_schema(operation: dict[str, Any]) -> Any:
    return (
        (((operation.get("requestBody") or {}).get("content") or {}).get(JSON_MEDIA) or {})
        .get("schema")
    )


def _response_schema(response: dict[str, Any]) -> Any:
    return (((response.get("content") or {}).get(JSON_MEDIA)) or {}).get("schema")


def _operation_changes(
    path: str,
    method: str,
    baseline_op: dict[str, Any],
    current_op: dict[str, Any],
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    changes: list[str] = []
    prefix = f"{method.upper()} {path}"

    base_params = {
        (param.get("in"), param.get("name")): param
        for param in baseline_op.get("parameters") or []
    }
    current_params = {
        (param.get("in"), param.get("name")): param
        for param in current_op.get("parameters") or []
    }
    for key, base_param in base_params.items():
        current_param = current_params.get(key)
        if current_param is None:
            changes.append(f"{prefix}: parámetro eliminado {key[0]} {key[1]}")
            continue
        if not base_param.get("required") and current_param.get("required"):
            changes.append(f"{prefix}: parámetro ahora obligatorio {key[0]} {key[1]}")
        if _signature(base_param.get("schema") or {}, baseline) != _signature(
            current_param.get("schema") or {}, current
        ):
            changes.append(f"{prefix}: tipo de parámetro cambiado {key[0]} {key[1]}")

    base_body = baseline_op.get("requestBody")
    current_body = current_op.get("requestBody")
    if base_body is not None:
        if current_body is None:
            changes.append(f"{prefix}: requestBody eliminado")
        else:
            if not base_body.get("required") and current_body.get("required"):
                changes.append(f"{prefix}: requestBody ahora obligatorio")
            base_schema = _request_schema(baseline_op)
            current_schema = _request_schema(current_op)
            if base_schema is not None:
                if current_schema is None:
                    changes.append(f"{prefix}: esquema de requestBody eliminado")
                else:
                    if _signature(base_schema, baseline) != _signature(
                        current_schema, current
                    ):
                        changes.append(f"{prefix}: forma del request cambiada")
                    base_props, base_required = _properties(base_schema, baseline)
                    current_props, current_required = _properties(current_schema, current)
                    for name, schema in base_props.items():
                        if name not in current_props:
                            changes.append(f"{prefix}: campo de request eliminado {name}")
                        elif _signature(schema, baseline) != _signature(
                            current_props[name], current
                        ):
                            changes.append(f"{prefix}: tipo de request cambiado {name}")
                    for name in sorted(current_required - base_required):
                        changes.append(f"{prefix}: campo de request obligatorio nuevo {name}")

    for status, base_response in (baseline_op.get("responses") or {}).items():
        current_response = (current_op.get("responses") or {}).get(status)
        if current_response is None:
            changes.append(f"{prefix}: respuesta {status} eliminada")
            continue
        base_schema = _response_schema(base_response)
        current_schema = _response_schema(current_response)
        if base_schema is None:
            continue
        if current_schema is None:
            changes.append(f"{prefix}: respuesta {status} sin esquema JSON")
            continue
        if _signature(base_schema, baseline) != _signature(current_schema, current):
            changes.append(f"{prefix}: forma de la respuesta {status} cambiada")
        base_props, _ = _properties(base_schema, baseline)
        current_props, _ = _properties(current_schema, current)
        for name, schema in base_props.items():
            if name not in current_props:
                changes.append(f"{prefix}: campo de respuesta eliminado {name}")
            elif _signature(schema, baseline) != _signature(current_props[name], current):
                changes.append(f"{prefix}: tipo de respuesta cambiado {name}")

    return changes


def breaking_changes(
    baseline: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Cambios que rompen consumidores existentes; las adiciones no cuentan."""
    changes: list[str] = []

    base_paths = baseline.get("paths") or {}
    current_paths = current.get("paths") or {}
    for path, base_methods in base_paths.items():
        current_methods = current_paths.get(path)
        if current_methods is None:
            changes.append(f"ruta eliminada {path}")
            continue
        for method, baseline_op in base_methods.items():
            if method == "parameters":
                continue
            current_op = current_methods.get(method)
            if current_op is None:
                changes.append(f"operación eliminada {method.upper()} {path}")
                continue
            changes.extend(
                _operation_changes(
                    path, method, baseline_op, current_op, baseline, current
                )
            )

    base_schemas = (baseline.get("components") or {}).get("schemas") or {}
    current_schemas = (current.get("components") or {}).get("schemas") or {}
    for name, base_schema in base_schemas.items():
        current_schema = current_schemas.get(name)
        if current_schema is None:
            changes.append(f"componente eliminado {name}")
            continue
        base_props, base_required = _properties(base_schema, baseline)
        current_props, current_required = _properties(current_schema, current)
        for prop, schema in base_props.items():
            if prop not in current_props:
                changes.append(f"{name}: campo eliminado {prop}")
            elif _signature(schema, baseline) != _signature(current_props[prop], current):
                changes.append(f"{name}: tipo cambiado {prop}")
        for prop in sorted(current_required - base_required):
            changes.append(f"{name}: campo obligatorio nuevo {prop}")

    return changes


@dataclass(frozen=True)
class _Field:
    name: str
    required: bool
    nested: tuple["_Field", ...] = ()
    is_array: bool = False


def _matching_brace(text: str, open_at: int) -> int | None:
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _extract_body(source: str, open_at: int) -> str:
    close_at = _matching_brace(source, open_at)
    if close_at is None:
        raise ValueError("Interfaz TypeScript sin llave de cierre")
    return source[open_at + 1 : close_at]


def _split_fields(body: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(body):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == ";" and depth == 0:
            chunk = body[start:index].strip()
            if chunk:
                chunks.append(chunk)
            start = index + 1
    tail = body[start:].strip()
    if tail:
        chunks.append(tail)
    return chunks


def _parse_fields(body: str) -> tuple[_Field, ...]:
    fields: list[_Field] = []
    declaration = re.compile(r"^([A-Za-z_]\w*)(\?)?\s*:\s*(.*)$", re.S)
    for chunk in _split_fields(body):
        match = declaration.match(chunk)
        if not match:
            continue
        name, optional, type_text = match.group(1), match.group(2), match.group(3)
        nested: tuple[_Field, ...] = ()
        is_array = False
        open_at = type_text.find("{")
        if open_at != -1:
            close_at = _matching_brace(type_text, open_at)
            if close_at is not None:
                nested = _parse_fields(type_text[open_at + 1 : close_at])
                prefix = type_text[:open_at].rstrip()
                is_array = "Array<" in prefix or prefix.endswith("[]")
        fields.append(_Field(name, optional is None, nested, is_array))
    return tuple(fields)


def _interfaces(source: str) -> dict[str, tuple[_Field, ...]]:
    """Extrae interfaces y objetos inline anidados del archivo TypeScript."""
    result: dict[str, tuple[_Field, ...]] = {}
    for match in re.finditer(r"export interface (\w+)\s*\{", source):
        body = _extract_body(source, match.end() - 1)
        result[match.group(1)] = _parse_fields(body)
    return result


def _check_fields(
    owner: str,
    fields: tuple[_Field, ...],
    schema: Any,
    root: dict[str, Any],
    problems: list[str],
) -> None:
    resolved = _resolve(schema, root)
    if not isinstance(resolved, dict):
        return
    properties, required = _properties(schema, root)
    if not properties and not resolved.get("properties") and not resolved.get("allOf"):
        # Dict/any genérico: no hay nombres de campo que comprobar.
        return
    for field in fields:
        if field.name not in properties:
            problems.append(f"{owner}.{field.name}: no existe en el esquema")
            continue
        if field.required and field.name not in required:
            problems.append(
                f"{owner}.{field.name}: obligatorio en TS pero opcional en OpenAPI"
            )
        if field.nested:
            nested_schema = properties[field.name]
            if field.is_array:
                array_schema = _resolve(nested_schema, root)
                if isinstance(array_schema, dict) and array_schema.get("type") == "array":
                    nested_schema = array_schema.get("items") or {}
                else:
                    variants = (array_schema or {}).get("anyOf") or []
                    array_variant = next(
                        (
                            variant
                            for variant in variants
                            if _resolve(variant, root).get("type") == "array"
                        ),
                        None,
                    )
                    nested_schema = (array_variant or {}).get("items") or {}
            _check_fields(
                f"{owner}.{field.name}", field.nested, nested_schema, root, problems
            )


@pytest.fixture(scope="module")
def current_schema() -> dict[str, Any]:
    return build_openapi()


def test_openapi_snapshot_has_no_breaking_changes(current_schema) -> None:
    update = os.environ.get("OPENAPI_UPDATE") == "1"
    if not SNAPSHOT_PATH.exists():
        if not update:
            pytest.fail(f"Falta el snapshot versionado {SNAPSHOT_PATH}")
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(current_schema, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    baseline = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert "/api/status" in (baseline.get("paths") or {})
    assert len((baseline.get("components") or {}).get("schemas") or {}) >= 30

    changes = breaking_changes(baseline, current_schema)
    if changes:
        raise AssertionError(
            f"El esquema OpenAPI rompe el contrato de {SNAPSHOT_PATH.name}:\n- "
            + "\n- ".join(changes)
            + "\nSi el cambio es intencionado, crea una nueva versión "
            "(tests/fixtures/openapi/v2.json) y apunta SNAPSHOT_PATH a ella; "
            "no sobrescribas la línea base anterior."
        )

    if update:
        SNAPSHOT_PATH.write_text(
            json.dumps(current_schema, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def test_frontend_types_have_schema_fields_and_requiredness(current_schema) -> None:
    components = (current_schema.get("components") or {}).get("schemas") or {}
    interfaces = _interfaces(FRONTEND_TYPES.read_text(encoding="utf-8"))
    assert len(interfaces) >= 20, "No se pudieron leer las interfaces del frontend"

    problems: list[str] = []
    for name, fields in interfaces.items():
        component = components.get(name)
        if not isinstance(component, dict):
            problems.append(f"{name}: falta el componente OpenAPI")
            continue
        _check_fields(name, fields, component, current_schema, problems)

    assert not problems, "Tipos del frontend fuera del esquema:\n- " + "\n- ".join(
        problems
    )


def _minimal_contract() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "paths": {
            "/api/x": {
                "post": {
                    "requestBody": {
                        "required": True,
                        "content": {
                            JSON_MEDIA: {
                                "schema": {"$ref": "#/components/schemas/Request"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "content": {
                                JSON_MEDIA: {
                                    "schema": {"$ref": "#/components/schemas/Response"}
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Request": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "string"}},
                },
                "Response": {
                    "type": "object",
                    "required": ["value"],
                    "properties": {"value": {"type": "string"}},
                },
            }
        },
    }


def _mutated(
    mutate: Callable[[dict[str, Any]], None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline = _minimal_contract()
    current = copy.deepcopy(baseline)
    mutate(current)
    return baseline, current


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda schema: schema["paths"].pop("/api/x"),
            "ruta eliminada",
        ),
        (
            lambda schema: schema["components"]["schemas"]["Request"]["properties"].pop(
                "value"
            ),
            "Request: campo eliminado value",
        ),
        (
            lambda schema: schema["components"]["schemas"]["Request"]["properties"].update(
                {"value": {"type": "integer"}}
            ),
            "Request: tipo cambiado value",
        ),
        (
            lambda schema: schema["components"]["schemas"]["Request"]["properties"].update(
                {"value": {"type": "string", "minLength": 3}}
            ),
            "Request: tipo cambiado value",
        ),
        (
            lambda schema: schema["components"]["schemas"]["Request"]["properties"].update(
                {"extra": {"type": "string"}}
            )
            or schema["components"]["schemas"]["Request"]["required"].append("extra"),
            "Request: campo obligatorio nuevo extra",
        ),
        (
            lambda schema: schema["components"]["schemas"]["Response"]["properties"].pop(
                "value"
            ),
            "Response: campo eliminado value",
        ),
    ],
)
def test_breaking_change_detector_flags_incompatible_changes(
    mutate, expected: str
) -> None:
    baseline, current = _mutated(mutate)
    changes = breaking_changes(baseline, current)
    assert any(expected in change for change in changes), changes


def test_breaking_change_detector_flags_a_removed_union_member() -> None:
    baseline = _minimal_contract()
    baseline["paths"]["/api/x"]["post"]["responses"]["200"]["content"][
        JSON_MEDIA
    ]["schema"] = {
        "anyOf": [
            {"$ref": "#/components/schemas/Response"},
            {"$ref": "#/components/schemas/Request"},
        ]
    }
    current = copy.deepcopy(baseline)
    current["paths"]["/api/x"]["post"]["responses"]["200"]["content"][
        JSON_MEDIA
    ]["schema"] = {"$ref": "#/components/schemas/Response"}

    changes = breaking_changes(baseline, current)
    assert any("forma de la respuesta 200 cambiada" in change for change in changes)


def test_breaking_change_detector_accepts_additive_changes() -> None:
    baseline = _minimal_contract()
    current = copy.deepcopy(baseline)
    current["paths"]["/api/new"] = {"get": {"responses": {"200": {"description": "ok"}}}}
    current["components"]["schemas"]["Request"]["properties"]["optional"] = {
        "type": "string"
    }
    current["components"]["schemas"]["Response"]["properties"]["extra"] = {
        "type": "integer"
    }

    assert breaking_changes(baseline, current) == []
