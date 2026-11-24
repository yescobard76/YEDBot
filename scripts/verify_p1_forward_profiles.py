#!/usr/bin/env python3
"""Verificación read-only de los dos perfiles forward congelados de P1.

Comprueba, sin escribir archivos ni abrir la base de datos:

- hashes de archivo y hashes canónicos de configuración;
- que control y filtro 0,25 solo difieren en ``risk.min_stop_or_ratio``;
- que ambos conservan la geometría P1 (max_contracts=5, max_sl_ticks=200,
  validez 210, tolerancia 24) y el feed forward congelado;
- que las copias coinciden con los brazos operativos de la ventana P1.

No lee ni modifica el holdout. Salida: JSON por stdout; código 1 si falla.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import Settings  # noqa: E402
from server.experiments import config_sha256  # noqa: E402

CONTROL = ROOT / "profiles" / "p1_forward_control" / "config.json"
FILTER = ROOT / "profiles" / "p1_forward_filter025" / "config.json"
MANIFEST = ROOT / "profiles" / "p1_forward.lock.json"
BASE = ROOT / "profiles" / "p2_freq" / "config.json"
OPERATIONAL_CONTROL = (
    ROOT
    / "data"
    / "forward"
    / "2026-12-01_p1_filter025"
    / "arms"
    / "control"
    / "profile"
    / "config.json"
)
OPERATIONAL_FILTER = (
    ROOT
    / "data"
    / "forward"
    / "2026-12-01_p1_filter025"
    / "arms"
    / "treatment"
    / "profile"
    / "config.json"
)

ONLY_DIFFERENCE = "risk.min_stop_or_ratio"
EXPECTED_SCHEMA = "p1-forward-frozen-v1"


class VerificationError(RuntimeError):
    """Una comprobación de integridad no se cumple."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"archivo ausente: {path.relative_to(ROOT)}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VerificationError(f"JSON inválido en {path.relative_to(ROOT)}: {exc}") from exc
    require(isinstance(payload, dict), f"se esperaba un objeto JSON: {path.relative_to(ROOT)}")
    return payload


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def diff_values(left: Any, right: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Diff recursivo determinista; devuelve cada ruta que no coincide."""
    if type(left) is not type(right):
        return [{"path": prefix or "$", "control": left, "treatment": right}]

    if isinstance(left, dict):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(left) | set(right)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in left:
                differences.append({"path": path, "control": "<missing>", "treatment": right[key]})
            elif key not in right:
                differences.append({"path": path, "control": left[key], "treatment": "<missing>"})
            else:
                differences.extend(diff_values(left[key], right[key], path))
        return differences

    if isinstance(left, list):
        differences = []
        for index in range(max(len(left), len(right))):
            path = f"{prefix}[{index}]"
            if index >= len(left):
                differences.append({"path": path, "control": "<missing>", "treatment": right[index]})
            elif index >= len(right):
                differences.append({"path": path, "control": left[index], "treatment": "<missing>"})
            else:
                differences.extend(diff_values(left[index], right[index], path))
        return differences

    if left != right:
        return [{"path": prefix or "$", "control": left, "treatment": right}]
    return []


def validate_arm(
    *,
    name: str,
    path: Path,
    payload: dict[str, Any],
    expected_ratio: float,
    expected_file_sha: str,
    expected_config_sha: str,
    expected_feed_path: str,
) -> dict[str, Any]:
    settings = Settings.model_validate(payload)

    require(settings.mode == "paper", f"{name}: mode debe ser paper")
    require(settings.live.live_enabled is False, f"{name}: live debe estar deshabilitado")
    require(settings.risk.max_contracts == 5, f"{name}: max_contracts debe ser 5")
    require(settings.risk.max_sl_ticks == 200, f"{name}: max_sl_ticks debe ser 200")
    require(
        settings.strategy.setup_validity_minutes == 210,
        f"{name}: setup_validity_minutes debe ser 210",
    )
    require(
        settings.strategy.retest_tolerance_ticks == 24,
        f"{name}: retest_tolerance_ticks debe ser 24",
    )
    require(
        settings.risk.min_stop_or_ratio == expected_ratio,
        f"{name}: min_stop_or_ratio debe ser {expected_ratio}",
    )
    require(settings.feed.provider == "csv", f"{name}: feed.provider debe ser csv")
    require(settings.feed.series_mode == "raw", f"{name}: feed.series_mode debe ser raw")
    require(
        settings.feed.exclude_roll_sessions is True,
        f"{name}: debe excluir sesiones de roll",
    )
    require(settings.feed.loop_sessions is False, f"{name}: loop_sessions debe ser false")
    require(
        settings.feed.csv_path == expected_feed_path,
        f"{name}: csv_path no coincide con la ventana P1 congelada",
    )

    actual_file_sha = file_sha256(path)
    require(
        actual_file_sha == expected_file_sha,
        f"{name}: config_file_sha256 no coincide "
        f"(esperado {expected_file_sha}, actual {actual_file_sha})",
    )
    actual_config_sha = config_sha256(settings)
    require(
        actual_config_sha == expected_config_sha,
        f"{name}: config_sha256 no coincide "
        f"(esperado {expected_config_sha}, actual {actual_config_sha})",
    )

    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "config_file_sha256": actual_file_sha,
        "config_sha256": actual_config_sha,
        "min_stop_or_ratio": settings.risk.min_stop_or_ratio,
        "p1": {
            "max_contracts": settings.risk.max_contracts,
            "max_sl_ticks": settings.risk.max_sl_ticks,
            "setup_validity_minutes": settings.strategy.setup_validity_minutes,
            "retest_tolerance_ticks": settings.strategy.retest_tolerance_ticks,
        },
        "feed": {
            "provider": settings.feed.provider,
            "csv_path": settings.feed.csv_path,
            "series_mode": settings.feed.series_mode,
            "exclude_roll_sessions": settings.feed.exclude_roll_sessions,
            "loop_sessions": settings.feed.loop_sessions,
        },
        "live_enabled": settings.live.live_enabled,
    }


def main() -> int:
    try:
        control = read_json(CONTROL)
        treatment = read_json(FILTER)
        manifest = read_json(MANIFEST)
        base = read_json(BASE)

        require(manifest.get("schema") == EXPECTED_SCHEMA, "schema del manifiesto inválido")
        require(manifest.get("only_difference") == ONLY_DIFFERENCE, "only_difference inválido")
        require(manifest.get("holdout_used") is False, "el manifiesto debe declarar holdout_used=false")
        require(
            manifest.get("guards", {}).get("database_accessed") is False,
            "el manifiesto debe declarar database_accessed=false",
        )

        base_sha = file_sha256(BASE)
        require(
            manifest.get("p1_definition", {}).get("base_config_file_sha256") == base_sha,
            "hash del perfil base P2 no coincide",
        )

        feed_path = manifest.get("forward_feed", {}).get("csv_path")
        require(isinstance(feed_path, str) and feed_path, "falta forward_feed.csv_path en el manifiesto")

        arms = manifest.get("arms", {})
        require(set(arms) == {"control", "filter025"}, "el manifiesto debe declarar control y filter025")

        control_info = validate_arm(
            name="control",
            path=CONTROL,
            payload=control,
            expected_ratio=0.0,
            expected_file_sha=arms["control"]["config_file_sha256"],
            expected_config_sha=arms["control"]["config_sha256"],
            expected_feed_path=feed_path,
        )
        treatment_info = validate_arm(
            name="filter025",
            path=FILTER,
            payload=treatment,
            expected_ratio=0.25,
            expected_file_sha=arms["filter025"]["config_file_sha256"],
            expected_config_sha=arms["filter025"]["config_sha256"],
            expected_feed_path=feed_path,
        )

        differences = diff_values(control, treatment)
        require(
            [item["path"] for item in differences] == [ONLY_DIFFERENCE],
            "los perfiles no difieren exactamente en risk.min_stop_or_ratio: "
            + json.dumps(differences, ensure_ascii=False),
        )
        require(
            differences[0]["control"] == 0.0 and differences[0]["treatment"] == 0.25,
            "los valores del filtro deben ser 0.0 y 0.25",
        )
        require(
            manifest.get("differences") == differences,
            "la comprobación del manifiesto no coincide con el diff real",
        )

        for arm_name, path, expected_hash in (
            ("control", OPERATIONAL_CONTROL, manifest["source_operational_window"]["control_config_file_sha256"]),
            ("treatment", OPERATIONAL_FILTER, manifest["source_operational_window"]["treatment_config_file_sha256"]),
        ):
            actual = file_sha256(path)
            require(
                actual == expected_hash,
                f"el perfil operativo {arm_name} cambió desde la congelación",
            )

        for profile_dir in (CONTROL.parent, FILTER.parent):
            unexpected = sorted(
                item.name for item in profile_dir.iterdir() if item.name != "config.json"
            )
            require(
                not unexpected,
                f"{profile_dir.relative_to(ROOT)} contiene archivos inesperados: {unexpected}",
            )

        summary = {
            "schema": "p1-forward-verification-v1",
            "status": "PASS",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "only_difference": differences[0],
            "arms": {"control": control_info, "filter025": treatment_info},
            "base_profile": {
                "path": str(BASE.relative_to(ROOT)).replace("\\", "/"),
                "config_file_sha256": base_sha,
            },
            "source_operational_window": manifest["source_operational_window"],
            "reads": [
                str(path.relative_to(ROOT)).replace("\\", "/")
                for path in (CONTROL, FILTER, MANIFEST, BASE, OPERATIONAL_CONTROL, OPERATIONAL_FILTER)
            ],
            "writes": [],
            "db_accessed": False,
            "holdout_accessed": False,
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, VerificationError) as exc:
        print(
            json.dumps(
                {
                    "schema": "p1-forward-verification-v1",
                    "status": "FAIL",
                    "error": str(exc),
                },
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
