"""Contrato del esqueleto de captura forward (sin motor ni backtests)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from server.forward.capture import (
    BAR_HEADER,
    CAPTURE_MANIFEST_SCHEMA,
    EQUITY_HEADER,
    FORWARD_END,
    FORWARD_START,
    STATUS_SKELETON,
    CaptureError,
    capture_paths,
    guard_session_date,
    guard_window,
    init_capture,
    main,
    validate_bars_file,
    verify_capture,
)
from server.market.csv_data import HOLDOUT_END, HOLDOUT_START

WINDOW = "TEST-FORWARD-CAPTURE"


def _init(root: Path) -> dict:
    return init_capture(window_id=WINDOW, root=root)


def _write_manifest(root: Path, payload: dict) -> None:
    paths = capture_paths(root, WINDOW)
    paths.manifest.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_init_creates_all_streams_and_manifest(tmp_path: Path) -> None:
    manifest = _init(tmp_path)
    paths = capture_paths(tmp_path, WINDOW)

    assert manifest["schema"] == CAPTURE_MANIFEST_SCHEMA
    assert manifest["status"] == STATUS_SKELETON
    assert manifest["window"]["start"] == FORWARD_START.isoformat()
    assert manifest["window"]["end"] == FORWARD_END.isoformat()
    assert manifest["holdout"]["sealed"] is True
    assert manifest["holdout"]["accessed"] is False
    assert manifest["holdout"]["status"] == "sealed_not_executed"
    assert manifest["policy"]["allow_synthetic"] is False
    assert manifest["policy"]["allow_backfill"] is False
    assert set(manifest["streams"]) == {
        "bars",
        "control.signals",
        "control.trades",
        "control.equity",
        "treatment.signals",
        "treatment.trades",
        "treatment.equity",
    }
    assert paths.bars.read_text(encoding="utf-8").splitlines()[0] == ",".join(
        BAR_HEADER
    )
    for arm in ("control", "treatment"):
        assert paths.signals[arm].read_bytes() == b""
        assert paths.trades[arm].read_bytes() == b""
        assert paths.equity[arm].read_text(encoding="utf-8").splitlines()[0] == ",".join(
            EQUITY_HEADER
        )
    assert paths.sessions.is_dir()

    report = verify_capture(window_id=WINDOW, root=tmp_path)
    assert report["ok"] is True, report["errors"]
    assert report["manifest"]["manifest_sha256"] == manifest["manifest_sha256"]


def test_reinit_does_not_overwrite_or_duplicate(tmp_path: Path) -> None:
    first = _init(tmp_path)
    paths = capture_paths(tmp_path, WINDOW)
    paths.signals["control"].write_text(
        '{"signal_id":"s-1"}\n', encoding="utf-8"
    )

    # La idempotencia solo se acepta si el esqueleto sigue verificando. Como
    # acabamos de alterar un stream, el segundo init debe negarse, no pisarlo.
    with pytest.raises(CaptureError, match="no verifica"):
        _init(tmp_path)
    assert paths.signals["control"].read_text(encoding="utf-8") == '{"signal_id":"s-1"}\n'
    assert json.loads(paths.manifest.read_text(encoding="utf-8")) == first


def test_clean_reinit_is_idempotent(tmp_path: Path) -> None:
    first = _init(tmp_path)
    second = _init(tmp_path)
    assert second["manifest_sha256"] == first["manifest_sha256"]


def test_tampered_stream_is_rejected(tmp_path: Path) -> None:
    _init(tmp_path)
    paths = capture_paths(tmp_path, WINDOW)
    with paths.trades["treatment"].open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"trade_id":"t-1"}\n')

    report = verify_capture(window_id=WINDOW, root=tmp_path)
    assert report["ok"] is False
    assert any("treatment.trades" in error and "sha256" in error for error in report["errors"])


def test_tampered_manifest_is_rejected(tmp_path: Path) -> None:
    _init(tmp_path)
    paths = capture_paths(tmp_path, WINDOW)
    payload = json.loads(paths.manifest.read_text(encoding="utf-8"))
    payload["status"] = "captured"
    _write_manifest(tmp_path, payload)

    report = verify_capture(window_id=WINDOW, root=tmp_path)
    assert report["ok"] is False
    assert any("manifest_sha256" in error for error in report["errors"])
    assert any("barras vacías" in error for error in report["errors"])


def test_holdout_session_guard_rejects_both_edges() -> None:
    assert guard_session_date(FORWARD_START) == FORWARD_START
    for day in (HOLDOUT_START, HOLDOUT_END, date(2026, 7, 15)):
        with pytest.raises(CaptureError, match="holdout sellado"):
            guard_session_date(day)


def test_holdout_and_burn_in_window_are_rejected(tmp_path: Path) -> None:
    for value in (date(2026, 7, 1), date(2026, 10, 30), date(2026, 11, 30)):
        with pytest.raises(CaptureError):
            init_capture(window_id=WINDOW, root=tmp_path, start=value, end=value)
    assert not capture_paths(tmp_path, WINDOW).root.exists()


def test_forward_window_bounds_are_enforced() -> None:
    with pytest.raises(CaptureError, match="muestra prohibida BURN_IN"):
        guard_window("2026-11-30", "2026-12-01")
    with pytest.raises(CaptureError, match="holdout sellado"):
        guard_window("2026-07-01", "2026-07-02")
    with pytest.raises(CaptureError, match="forward pre-registrado"):
        guard_window("2026-11-02", "2026-11-20")
    with pytest.raises(CaptureError, match="forward pre-registrado"):
        guard_window("2029-11-30", "2029-12-01")
    with pytest.raises(CaptureError, match="posterior"):
        guard_window("2027-01-02", "2027-01-01")
    with pytest.raises(CaptureError, match="sesiones de trading"):
        guard_window("2026-12-05", "2026-12-07")


def test_empty_capture_directory_without_manifest_is_not_overwritten(
    tmp_path: Path,
) -> None:
    paths = capture_paths(tmp_path, WINDOW)
    paths.root.mkdir(parents=True)
    (paths.root / "foreign.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(CaptureError, match="no vacío"):
        _init(tmp_path)
    assert (paths.root / "foreign.txt").read_text(encoding="utf-8") == "do not overwrite"


def test_missing_manifest_is_reported(tmp_path: Path) -> None:
    report = verify_capture(window_id=WINDOW, root=tmp_path)
    assert report["ok"] is False
    assert "manifiesto" in report["errors"][0]


def _holdout_bar() -> str:
    return (
        "2026-07-01T09:00:00-04:00,MNQ,20000,20001,19999,20000,1,"
        "MNQZ26,2026-12-18\n"
    )


def test_bars_validator_rejects_holdout_even_with_valid_ohlc(
    tmp_path: Path,
) -> None:
    path = tmp_path / "bars_forward.csv"
    path.write_text(",".join(BAR_HEADER) + "\n" + _holdout_bar(), encoding="utf-8")

    errors = validate_bars_file(path)
    assert any("holdout sellado" in error for error in errors)


def test_bars_validator_rejects_incoherent_ohlc(tmp_path: Path) -> None:
    path = tmp_path / "bars_forward.csv"
    path.write_text(
        ",".join(BAR_HEADER)
        + "\n2026-12-01T09:00:00-05:00,MNQ,20000,19999,19998,20000,1,MNQZ26,2026-12-18\n",
        encoding="utf-8",
    )

    errors = validate_bars_file(path)
    assert any("OHLC incoherente" in error for error in errors)


def test_verify_rejects_holdout_rows_even_if_manifest_is_resigned(
    tmp_path: Path,
) -> None:
    _init(tmp_path)
    paths = capture_paths(tmp_path, WINDOW)
    payload = json.loads(paths.manifest.read_text(encoding="utf-8"))
    payload["streams"]["bars"]["rows"] = 1
    paths.bars.write_text(
        ",".join(BAR_HEADER) + "\n" + _holdout_bar(), encoding="utf-8"
    )
    payload["streams"]["bars"]["sha256"] = hashlib.sha256(
        paths.bars.read_bytes()
    ).hexdigest()
    # Recomputar el sello del manifiesto simula a un atacante que intenta
    # hacer pasar una fila del holdout como si fuera legítima.
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    _write_manifest(tmp_path, payload)

    report = verify_capture(window_id=WINDOW, root=tmp_path)
    assert report["ok"] is False
    assert any("holdout" in error for error in report["errors"])


def test_cli_init_and_verify(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["init", "--window-id", WINDOW, "--root", str(tmp_path)]) == 0
    assert STATUS_SKELETON in capsys.readouterr().out
    assert main(["verify", "--window-id", WINDOW, "--root", str(tmp_path)]) == 0
    assert '"ok": true' in capsys.readouterr().out
