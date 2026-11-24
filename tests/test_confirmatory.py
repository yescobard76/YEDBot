"""Tests del preflight confirmatorio y del sello one-shot del holdout."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.config import Settings
from server.confirmatory import (
    CODE_HASH_ALGORITHM,
    ConfirmatoryError,
    HoldoutAlreadySealed,
    HoldoutSeal,
    build_dataset_manifest,
    compute_code_hash,
    declared_settings,
    freeze_dataset_manifest,
    run_holdout,
    sha256_file,
    verify_confirmatory,
)
from server.market.synthetic import build_session


def _write_dataset(path: Path, days: list[date], *, volume_bump: float = 0.0) -> Path:
    settings = Settings()
    rows = ["timestamp,symbol,open,high,low,close,volume"]
    for day in days:
        data = build_session(day, settings)
        for symbol in ("MNQ", "NQ", "ES"):
            for index, bar in enumerate(data[symbol]):
                volume = bar.volume + (volume_bump if symbol == "NQ" and index == 0 else 0.0)
                rows.append(
                    f"{bar.ts},{symbol},{bar.open:.4f},{bar.high:.4f},"
                    f"{bar.low:.4f},{bar.close:.4f},{volume:.2f}"
                )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _fixture(tmp_path: Path, *, legacy_lock: bool = False) -> dict:
    root = tmp_path / "project"
    (root / "server").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "server" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "data").mkdir()
    (root / "reports").mkdir()

    day_one, day_two = date(2025, 6, 3), date(2025, 6, 4)
    dataset = _write_dataset(root / "data" / "bars.csv", [day_one, day_two])
    fills = root / "data" / "bars_fills.csv"
    fills.write_text(
        "timestamp,symbol,contract,expiry,previous_close\n",
        encoding="utf-8",
    )
    protocol = root / "docs" / "PROTOCOLO_BACKTEST.md"
    protocol.write_text("protocol fixture\n", encoding="utf-8")

    settings = Settings()
    settings.feed.provider = "csv"
    settings.feed.csv_path = str(dataset)
    settings.feed.series_mode = "raw"
    settings.feed.exclude_roll_sessions = True
    settings.feed.replay_speed = 200

    lock = {
        "protocol": "docs/PROTOCOLO_BACKTEST.md",
        "protocol_version": "test-1",
        "frozen_at": "2026-11-19",
        "protocol_sha256": sha256_file(protocol),
        "status": "frozen-not-executed",
        "dataset": {
            "expected_calendar_sessions": 2,
            "expected_sessions": 2,
            "expected_contracts": 0,
            "expected_roll_events": 0,
            "expected_roll_sessions": 0,
            "expected_regular_bars": 420,
            "expected_early_close_sessions": 0,
            "expected_early_close_bars": {},
            "expected_total_minutes_per_symbol": 900,
            "expected_total_minutes_all_symbols": 2700,
            "max_flat_filled_bars": 0,
        },
        "windows": [
            {
                "id": "W1",
                "start": day_one.isoformat(),
                "end": day_one.isoformat(),
                "calendar_sessions": 1,
                "sessions": 1,
            }
        ],
        "holdout": {
            "id": "H1",
            "start": day_two.isoformat(),
            "end": day_two.isoformat(),
            "calendar_sessions": 1,
            "sessions": 1,
        },
        "settings": settings.model_dump(),
    }
    if legacy_lock:
        # Simula un lock congelado antes de añadir un campo con default.
        lock["settings"]["strategy"].pop("or_retracement_pct", None)
    lock_path = root / "docs" / "protocolo_backtest.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    manifest_path = root / "reports" / "dataset_manifest.json"
    manifest = freeze_dataset_manifest(
        output=manifest_path,
        root=root,
        protocol_path=protocol,
        lock_path=lock_path,
        dataset_path=dataset,
        fills_path=fills,
        settings=settings,
        code_roots=[root / "server", root / "tests"],
    )
    return {
        "root": root,
        "protocol": protocol,
        "lock": lock_path,
        "dataset": dataset,
        "fills": fills,
        "manifest": manifest_path,
        "manifest_data": manifest,
        "settings": settings,
        "code_roots": [root / "server", root / "tests"],
    }


def _verify(fixture: dict, **overrides) -> dict:
    kwargs = {
        "root": fixture["root"],
        "protocol_path": fixture["protocol"],
        "lock_path": fixture["lock"],
        "dataset_manifest_path": fixture["manifest"],
        "settings": fixture["settings"],
        "code_roots": fixture["code_roots"],
    }
    kwargs.update(overrides)
    return verify_confirmatory(**kwargs)


def test_confirmatory_verification_passes_with_frozen_artifacts(tmp_path: Path):
    fixture = _fixture(tmp_path)
    report = _verify(fixture)

    assert report["ok"] is True
    names = {check["name"] for check in report["checks"]}
    assert {
        "protocol.sha256",
        "config.matches_lock",
        "manifest.code_sha256",
        "dataset.file_sha256",
        "dataset.holdout.sessions",
        "dataset.fills_not_consecutive",
    } <= names
    assert report["artifacts"]["code"]["algorithm"] == CODE_HASH_ALGORITHM
    assert report["artifacts"]["dataset"]["dataset_id"]
    assert report["artifacts"]["dataset_manifest"]["sha256"]


def test_protocol_hash_tamper_is_rejected(tmp_path: Path):
    fixture = _fixture(tmp_path)
    fixture["protocol"].write_text("protocol fixture altered\n", encoding="utf-8")
    report = _verify(fixture)

    assert report["ok"] is False
    failed = {check["name"] for check in report["checks"] if not check["ok"]}
    assert "protocol.sha256" in failed
    assert "manifest.protocol_sha256" in failed


def test_verify_detects_changed_lock_status(tmp_path: Path):
    fixture = _fixture(tmp_path)
    lock = json.loads(fixture["lock"].read_text(encoding="utf-8"))
    lock["status"] = "holdout-executed"
    fixture["lock"].write_text(json.dumps(lock), encoding="utf-8")

    report = verify_confirmatory(
        root=fixture["root"],
        protocol_path=fixture["protocol"],
        lock_path=fixture["lock"],
        dataset_manifest_path=fixture["manifest"],
        settings=fixture["settings"],
        code_roots=fixture["code_roots"],
    )

    assert report["ok"] is False
    assert any(item["name"] == "lock.status" and not item["ok"] for item in report["checks"])


def test_code_hash_tamper_is_rejected(tmp_path: Path):
    fixture = _fixture(tmp_path)
    (fixture["root"] / "server" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    report = _verify(fixture)

    assert report["ok"] is False
    failed = {check["name"] for check in report["checks"] if not check["ok"]}
    assert "manifest.code_sha256" in failed


def test_config_mismatch_is_rejected(tmp_path: Path):
    fixture = _fixture(tmp_path)
    modified = fixture["settings"].model_copy(deep=True)
    modified.risk.initial_capital += 1
    report = _verify(fixture, settings=modified)

    assert report["ok"] is False
    failed = {check["name"] for check in report["checks"] if not check["ok"]}
    assert "config.matches_lock" in failed


def test_dataset_hash_tamper_is_rejected(tmp_path: Path):
    fixture = _fixture(tmp_path)
    _write_dataset(fixture["dataset"], [date(2025, 6, 3), date(2025, 6, 4)], volume_bump=1.0)
    report = _verify(fixture)

    assert report["ok"] is False
    failed = {check["name"] for check in report["checks"] if not check["ok"]}
    assert "dataset.file_sha256" in failed or "manifest.dataset.file_sha256" in failed


def test_holdout_seal_is_one_shot_and_ledger_blocks_retry(tmp_path: Path):
    root = tmp_path / "seal"
    seal = HoldoutSeal(
        seal_path=root / "holdout.seal.json",
        ledger_path=root / "holdout.ledger.jsonl",
        result_path=root / "holdout.json",
        receipt_path=root / "holdout.receipt.json",
    )
    first = seal.reserve({"protocol_version": "test-1"})
    assert first["status"] == "reserved"
    assert seal.seal_path.exists()
    assert seal.ledger_path.exists()
    assert len(seal.ledger_path.read_text(encoding="utf-8").splitlines()) == 1

    with pytest.raises(HoldoutAlreadySealed, match="segundo intento"):
        seal.reserve({"protocol_version": "test-1"})


def test_holdout_seal_blocks_even_if_seal_file_disappears(tmp_path: Path):
    root = tmp_path / "seal"
    seal = HoldoutSeal(
        seal_path=root / "holdout.seal.json",
        ledger_path=root / "holdout.ledger.jsonl",
        result_path=root / "holdout.json",
        receipt_path=root / "holdout.receipt.json",
    )
    seal.reserve({"protocol_version": "test-1"})
    seal.seal_path.unlink()

    with pytest.raises(HoldoutAlreadySealed, match="ledger"):
        seal.reserve({"protocol_version": "test-1"})


def test_run_holdout_seals_before_runner_and_never_runs_twice(tmp_path: Path):
    fixture = _fixture(tmp_path)
    seal_path = fixture["root"] / "reports" / "holdout.seal.json"
    ledger_path = fixture["root"] / "reports" / "holdout.ledger.jsonl"
    result_path = fixture["root"] / "reports" / "holdout.json"
    receipt_path = fixture["root"] / "reports" / "holdout.receipt.json"
    calls: list[tuple[int, date]] = []

    def runner(settings: Settings, days: int, start: date):
        assert seal_path.exists(), "el sello debe existir antes de ejecutar"
        assert not result_path.exists(), "el resultado no puede existir antes del runner"
        calls.append((days, start))
        return [{"variant": "full", "trades": []}]

    first = run_holdout(
        root=fixture["root"],
        protocol_path=fixture["protocol"],
        lock_path=fixture["lock"],
        dataset_manifest_path=fixture["manifest"],
        seal_path=seal_path,
        ledger_path=ledger_path,
        result_path=result_path,
        receipt_path=receipt_path,
        settings=fixture["settings"],
        code_roots=fixture["code_roots"],
        runner=runner,
    )
    assert calls == [(1, date(2025, 6, 4))]
    assert json.loads(result_path.read_text(encoding="utf-8"))[0]["variant"] == "full"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == "completed"
    assert first["seal"]["run_id"]

    with pytest.raises(HoldoutAlreadySealed):
        run_holdout(
            root=fixture["root"],
            protocol_path=fixture["protocol"],
            lock_path=fixture["lock"],
            dataset_manifest_path=fixture["manifest"],
            seal_path=seal_path,
            ledger_path=ledger_path,
            result_path=result_path,
            receipt_path=receipt_path,
            settings=fixture["settings"],
            code_roots=fixture["code_roots"],
            runner=lambda *_: pytest.fail("el runner no debe ejecutarse dos veces"),
        )
    assert len(calls) == 1


def test_run_holdout_does_not_seal_when_preflight_fails(tmp_path: Path):
    fixture = _fixture(tmp_path)
    (fixture["root"] / "server" / "app.py").write_text("BROKEN = True\n", encoding="utf-8")
    seal_path = fixture["root"] / "reports" / "holdout.seal.json"

    with pytest.raises(ConfirmatoryError, match="Preflight falló"):
        run_holdout(
            root=fixture["root"],
            protocol_path=fixture["protocol"],
            lock_path=fixture["lock"],
            dataset_manifest_path=fixture["manifest"],
            seal_path=seal_path,
            ledger_path=fixture["root"] / "reports" / "holdout.ledger.jsonl",
            result_path=fixture["root"] / "reports" / "holdout.json",
            receipt_path=fixture["root"] / "reports" / "holdout.receipt.json",
            settings=fixture["settings"],
            code_roots=fixture["code_roots"],
            runner=lambda *_: pytest.fail("el runner no debe ejecutarse"),
        )
    assert not seal_path.exists()


def test_freeze_refuses_to_overwrite_manifest(tmp_path: Path):
    fixture = _fixture(tmp_path)
    with pytest.raises(FileExistsError):
        freeze_dataset_manifest(
            output=fixture["manifest"],
            root=fixture["root"],
            protocol_path=fixture["protocol"],
            lock_path=fixture["lock"],
            dataset_path=fixture["dataset"],
            fills_path=fixture["fills"],
            settings=fixture["settings"],
            code_roots=fixture["code_roots"],
        )


def test_freeze_fails_if_lock_expectations_do_not_match_dataset(tmp_path: Path):
    fixture = _fixture(tmp_path)
    lock = json.loads(fixture["lock"].read_text(encoding="utf-8"))
    lock["dataset"]["expected_calendar_sessions"] = 99
    fixture["lock"].write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(ConfirmatoryError, match="no cumple el lock"):
        build_dataset_manifest(
            root=fixture["root"],
            protocol_path=fixture["protocol"],
            lock_path=fixture["lock"],
            dataset_path=fixture["dataset"],
            fills_path=fixture["fills"],
            settings=fixture["settings"],
            code_roots=fixture["code_roots"],
        )


def test_current_protocol_and_lock_are_internally_consistent():
    root = Path(__file__).resolve().parents[1]
    lock = json.loads(
        (root / "docs" / "protocolo_backtest.lock.json").read_text(encoding="utf-8")
    )
    assert sha256_file(root / "docs" / "PROTOCOLO_BACKTEST.md") == lock["protocol_sha256"]
    # El lock es un snapshot congelado: un campo nuevo con default no debe
    # invalidarlo si el lock no lo declara. Los valores sí deben coincidir.
    assert declared_settings(lock["settings"]) == lock["settings"]


def test_verify_accepts_lock_that_omits_new_defaulted_field(tmp_path: Path):
    fixture = _fixture(tmp_path, legacy_lock=True)
    lock = json.loads(fixture["lock"].read_text(encoding="utf-8"))
    assert "or_retracement_pct" not in lock["settings"]["strategy"]

    report = _verify(fixture)

    assert report["ok"] is True


def test_code_hash_is_stable_and_changes_with_content(tmp_path: Path):
    root = tmp_path / "project"
    (root / "server").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "server" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (root / "tests" / "test_a.py").write_text("def test_a(): pass\n", encoding="utf-8")

    first, first_count = compute_code_hash(root, [root / "server", root / "tests"])
    second, second_count = compute_code_hash(root, [root / "server", root / "tests"])
    assert (first, first_count) == (second, second_count) == (first, 2)

    (root / "server" / "a.py").write_text("A = 2\n", encoding="utf-8")
    changed, changed_count = compute_code_hash(root, [root / "server", root / "tests"])
    assert changed != first
    assert changed_count == 2
