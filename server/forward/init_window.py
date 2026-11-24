"""Crea una ventana forward y sus snapshots T0 inmutables."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .identity import init_arm, now_utc
from .paths import ARM_PORTS, PROJECT_ROOT, arm_dir, profile_dir, window_dir

WINDOW_SCHEMA = "forward-window-v1"


def _common_overrides(window_id: str) -> dict:
    return {
        "mode": "paper",
        "feed": {
            "provider": "csv",
            "csv_path": f"data/forward/{window_id}/bars_forward.csv",
            "series_mode": "raw",
            "exclude_roll_sessions": True,
            "loop_sessions": False,
            "replay_speed": 1.0,
            "start_date": "",
        },
        "live": {"live_enabled": False},
        "risk": {"max_contracts": 5, "max_sl_ticks": 200},
    }


def create_window(
    *,
    window_id: str,
    kind: str,
    arms: list[str],
    base_config: str,
    note: str = "",
    start_date: str = "2026-12-01",
    sessions_target: int = 378,
) -> dict:
    root = window_dir(window_id)
    if root.exists():
        raise FileExistsError(f"la ventana ya existe: {root}")
    root.mkdir(parents=True, exist_ok=False)

    arm_meta: dict[str, dict] = {}
    for arm in arms:
        overrides = _common_overrides(window_id)
        overrides["risk"]["min_stop_or_ratio"] = 0.0 if arm == "control" else 0.25
        snapshot = init_arm(
            window_id=window_id,
            arm=arm,
            base_config_path=base_config,
            overrides=overrides,
            port=ARM_PORTS[arm],
            kind=kind,
            note=note,
        )
        arm_path = arm_dir(window_id, arm)
        for name in ("sessions", "logs"):
            (arm_path / name).mkdir(parents=True, exist_ok=True)
        (arm_path / "signals.jsonl").touch()
        arm_meta[arm] = {
            "port": ARM_PORTS[arm],
            "profile_dir": f"arms/{arm}/profile",
            "config_file_sha256": snapshot["config_file_sha256"],
            "code_sha256": snapshot["code_sha256"],
        }

    window = {
        "schema": WINDOW_SCHEMA,
        "window_id": window_id,
        "kind": kind,
        "created_at": now_utc(),
        "start_date": start_date,
        "sessions_target": sessions_target,
        "note": note,
        "holdout_used": False,
        "arms": arm_meta,
    }
    (root / "window.json").write_text(
        json.dumps(window, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return window


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea una ventana forward aislada (T0).")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--kind", default="harness", choices=["harness", "forward"])
    parser.add_argument("--arms", default="control,treatment")
    parser.add_argument(
        "--base-config",
        default="profiles/p2_freq/config.json",
        help="Config base de solo lectura; nunca se modifica.",
    )
    parser.add_argument("--start-date", default="2026-12-01")
    parser.add_argument("--sessions-target", type=int, default=378)
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)

    arms = [item.strip() for item in args.arms.split(",") if item.strip()]
    try:
        window = create_window(
            window_id=args.window_id,
            kind=args.kind,
            arms=arms,
            base_config=args.base_config,
            note=args.note,
            start_date=args.start_date,
            sessions_target=args.sessions_target,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FORWARD_INIT_FAIL: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(window, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
