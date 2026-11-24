"""Pruebas del conversor Databento sin usar la API ni ejecutar backtests."""

from __future__ import annotations

import csv
import json
import types
from datetime import date
from pathlib import Path

import pytest

from server.market import databento_fetch
from server.market.csv_data import inspect_csv
from server.market.databento_fetch import (
    DEFINITION_LEAD_DAYS,
    EXPECTED_CODES,
    ROOTS,
    activate_dataset,
    active_definition,
    convert,
    download_bars,
    download_definitions,
    load_fixture,
    main,
    parse_definitions,
    roll_dates_for_window,
)

FIXTURE = Path(__file__).parent / "fixtures" / "databento_small.json"
EXPECTED_ROLLS = [
    date(2025, 3, 13),
    date(2025, 6, 12),
    date(2025, 9, 11),
    date(2025, 12, 11),
    date(2026, 3, 12),
    date(2026, 6, 10),
    date(2026, 9, 10),
]


def test_calendar_has_24_contracts_and_protocol_rolls():
    definitions = parse_definitions(load_fixture(FIXTURE)["definitions"])

    assert set(definitions) == set(EXPECTED_CODES)
    assert len(definitions) == 24
    for root in ROOTS:
        assert len([code for code in definitions if code.startswith(root) and code[len(root)] in "HMUZ"]) == 8
        assert definitions[f"{root}H25"].raw_symbol == f"{root}H5"
        assert definitions[f"{root}H25"].expiry == date(2025, 3, 21)
        assert definitions[f"{root}M26"].raw_symbol == f"{root}M6"
        assert definitions[f"{root}M26"].expiry == date(2026, 6, 18)

    rolls = roll_dates_for_window(definitions, date(2025, 1, 10), date(2026, 10, 30))
    for root in ROOTS:
        assert rolls[root] == EXPECTED_ROLLS

    assert active_definition(definitions, "MNQ", date(2025, 7, 3)).code == "MNQU25"
    assert active_definition(definitions, "MNQ", date(2025, 9, 11)).code == "MNQU25"
    assert active_definition(definitions, "MNQ", date(2025, 9, 12)).code == "MNQZ25"
    assert active_definition(definitions, "NQ", date(2025, 6, 12)).code == "NQM25"
    assert active_definition(definitions, "NQ", date(2025, 6, 13)).code == "NQU25"


def test_fixture_conversion_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    out = tmp_path / "bars.csv"
    fills = tmp_path / "fills.csv"
    summary = tmp_path / "summary.json"

    # Sin --start/--end: el fixture declara su propia ventana de una sesión.
    assert main([
        "--fixture", str(FIXTURE),
        "--out", str(out),
        "--fills-out", str(fills),
        "--summary", str(summary),
    ]) == 0

    report = inspect_csv(out)
    assert report["ok"], report["errors"]
    assert report["session_count"] == 1
    assert report["all_sessions"] == ["2025-07-03"]
    assert report["common_bars"] == 240
    assert report["all_common_bars"] == 240
    assert report["session_validation"]["early_close_sessions"] == ["2025-07-03"]

    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 720
    assert {row["symbol"] for row in rows} == {"MNQ", "NQ", "ES"}
    assert {row["contract"] for row in rows} == {"MNQU25", "NQU25", "ESU25"}
    assert rows[0]["timestamp"] == "2025-07-03T09:00:00-04:00"
    assert rows[-1]["timestamp"] == "2025-07-03T12:59:00-04:00"
    # El premarket, el afterhours del cierre anticipado, el contrato inactivo
    # (M25) y la sesión festiva del 4 de julio no forman parte del CSV.
    assert not any(row["timestamp"].endswith("08:30:00-04:00") for row in rows)
    assert not any(row["timestamp"].startswith("2025-07-04") for row in rows)
    assert not any(row["contract"] == "MNQM25" for row in rows)

    with fills.open(newline="", encoding="utf-8") as handle:
        fill_rows = list(csv.DictReader(handle))
    assert len(fill_rows) == 1
    assert fill_rows[0] == {
        "timestamp": "2025-07-03T10:00:00-04:00",
        "symbol": "MNQ",
        "contract": "MNQU25",
        "expiry": "2025-09-19",
        "previous_close": "20015",
    }

    filled = next(
        row for row in rows
        if row["timestamp"] == "2025-07-03T10:00:00-04:00" and row["symbol"] == "MNQ"
    )
    assert filled["open"] == filled["high"] == filled["low"] == filled["close"] == "20015"
    assert filled["volume"] == "0"

    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["expected_sessions"] == 1
    assert payload["rows"] == 720
    assert payload["fills"] == 1
    assert len(payload["contracts"]) == 24
    assert payload["rolls"] == {root: [] for root in ROOTS}


def test_two_consecutive_missing_minutes_abort(tmp_path):
    payload = load_fixture(FIXTURE)
    missing = {"2025-07-03T14:00:00Z", "2025-07-03T14:01:00Z"}
    bars = [
        row for row in payload["bars"]
        if not (row["symbol"] == "MNQU5" and row["ts_event"] in missing)
    ]

    with pytest.raises(ValueError, match="consecutivos sin operaciones"):
        convert(payload["definitions"], bars, date(2025, 7, 3), date(2025, 7, 4))


def test_real_mode_requires_api_key(monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="DATABENTO_API_KEY"):
        main([])


def test_databento_refuses_holdout_window(capsys):
    with pytest.raises(SystemExit):
        main(["--end", "2026-07-01"])

    assert "holdout" in capsys.readouterr().err


def test_activate_solo_se_llama_tras_validar(tmp_path, monkeypatch):
    llamado = []
    monkeypatch.setattr(
        "server.market.databento_fetch.activate_dataset",
        lambda path: llamado.append(path),
    )
    out = tmp_path / "bars.csv"

    assert main(
        [
            "--fixture", str(FIXTURE),
            "--out", str(out),
            "--fills-out", str(tmp_path / "fills.csv"),
            "--summary", str(tmp_path / "summary.json"),
            "--activate",
        ]
    ) == 0

    assert llamado == [out]
    assert out.exists()
    assert not out.with_name(out.name + ".tmp").exists()


def test_activate_dataset_deja_csv_raw_sin_rolls(tmp_path, monkeypatch):
    from server.config import Settings

    guardado: dict[str, object] = {}
    monkeypatch.setattr(
        "server.market.databento_fetch.load_settings", lambda: Settings()
    )
    monkeypatch.setattr(
        "server.market.databento_fetch.save_settings",
        lambda settings: guardado.update(json.loads(settings.model_dump_json())),
    )

    activate_dataset(tmp_path / "bars.csv")

    feed = guardado["feed"]
    assert feed["provider"] == "csv"
    assert str(feed["csv_path"]).endswith("bars.csv")
    assert feed["series_mode"] == "raw"
    assert feed["exclude_roll_sessions"] is True
    assert feed["loop_sessions"] is False
    assert feed["start_date"] == ""
    assert guardado["mode"] == "paper"
    assert guardado["live"]["live_enabled"] is False


class _FakeFrame:
    def __init__(self, records):
        self.records = records

    def to_dict(self, orient):
        assert orient == "records"
        return self.records


class _FakeData:
    def __init__(self, records):
        self.records = records

    def to_df(self):
        return _FakeFrame(self.records)


class _FakeTimeseries:
    def __init__(self):
        self.calls = []

    def get_range(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeData([{"ts_event": "2025-07-03T13:00:00Z", "symbol": "MNQU5"}])


class _FakeClient:
    def __init__(self):
        self.timeseries = _FakeTimeseries()


def test_download_calls_use_protocol_symbols_and_dates(tmp_path):
    payload = load_fixture(FIXTURE)
    definitions = parse_definitions(payload["definitions"])
    client = _FakeClient()

    definition_records = download_definitions(
        client, "GLBX.MDP3", date(2025, 7, 3), date(2025, 7, 4)
    )
    assert definition_records[0]["symbol"] == "MNQU5"
    definition_call = client.timeseries.calls[0]
    assert definition_call == {
        "dataset": "GLBX.MDP3",
        "schema": "definition",
        "stype_in": "parent",
        "symbols": ["MNQ.FUT", "NQ.FUT", "ES.FUT"],
        "start": "2025-03-05T00:00:00Z",
        "end": "2025-11-02T00:00:00Z",
    }
    # parent/raw_symbol no es una combinación válida en Databento: 422.
    assert "stype_out" not in definition_call

    bar_records = download_bars(
        client, "GLBX.MDP3", definitions, date(2025, 7, 3), date(2025, 7, 4)
    )
    assert bar_records[0]["symbol"] == "MNQU5"
    bar_call = client.timeseries.calls[1]
    assert bar_call["dataset"] == "GLBX.MDP3"
    assert bar_call["schema"] == "ohlcv-1m"
    assert bar_call["stype_in"] == "raw_symbol"
    assert "stype_out" not in bar_call
    assert bar_call["start"] == "2025-07-03T00:00:00Z"
    assert bar_call["end"] == "2025-07-05T00:00:00Z"
    assert bar_call["symbols"] == [definition.raw_symbol for definition in definitions.values()]
    assert DEFINITION_LEAD_DAYS == 120


class _HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"{status} NOT AUTHORIZED")
        self.http_status = status


def _fail_with(status: int, monkeypatch) -> None:
    monkeypatch.setenv("DATABENTO_API_KEY", "db-prueba")
    monkeypatch.setattr(
        databento_fetch,
        "_import_databento",
        lambda: types.SimpleNamespace(Historical=lambda key: object()),
    )

    def _denied(*args, **kwargs):
        raise _HttpError(status)

    monkeypatch.setattr(databento_fetch, "download_definitions", _denied)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ["401", "no es válida", "32 caracteres"]),
        (402, ["402", "pago", "facturación"]),
        (403, ["403", "list_datasets", "portal", "DATABENTO_API_KEY"]),
    ],
)
def test_los_errores_de_credenciales_se_explican_sin_traceback(
    monkeypatch, tmp_path, status, expected
):
    _fail_with(status, monkeypatch)

    with pytest.raises(SystemExit) as info:
        main([
            "--start", "2025-01-10",
            "--end", "2025-01-12",
            "--out", str(tmp_path / "bars.csv"),
        ])

    text = str(info.value)
    for fragment in expected:
        assert fragment in text


def test_convert_con_dates_exige_solo_esas_sesiones():
    payload = load_fixture(FIXTURE)

    # La ventana abarca tres sesiones, pero solo se descargó la del 3 de julio.
    with pytest.raises(ValueError, match="Faltan"):
        convert(payload["definitions"], payload["bars"], date(2025, 7, 1), date(2025, 7, 4))

    result = convert(
        payload["definitions"],
        payload["bars"],
        date(2025, 7, 1),
        date(2025, 7, 4),
        dates=[date(2025, 7, 3)],
    )

    assert {row.day for row in result.rows} == {date(2025, 7, 3)}


def test_dates_descarga_una_peticion_por_sesion_y_no_activa(monkeypatch, tmp_path):
    payload = load_fixture(FIXTURE)
    calls: list[tuple[date, date]] = []
    monkeypatch.setenv("DATABENTO_API_KEY", "db-prueba")
    monkeypatch.setattr(
        databento_fetch,
        "_import_databento",
        lambda: types.SimpleNamespace(Historical=lambda key: object()),
    )
    monkeypatch.setattr(
        databento_fetch, "download_definitions", lambda *args, **kwargs: payload["definitions"]
    )

    def _bars(client, dataset, definitions, start, end):
        calls.append((start, end))
        return payload["bars"]

    monkeypatch.setattr(databento_fetch, "download_bars", _bars)
    out = tmp_path / "pilot.csv"
    summary = tmp_path / "summary.json"

    code = main([
        "--dates", "2025-07-03",
        "--out", str(out),
        "--fills-out", str(tmp_path / "fills.csv"),
        "--summary", str(summary),
    ])

    assert code == 0
    # Una petición por sesión, con el día como ventana, no el rango completo.
    assert calls == [(date(2025, 7, 3), date(2025, 7, 3))]
    assert out.exists()
    assert json.loads(summary.read_text(encoding="utf-8"))["dates"] == ["2025-07-03"]


def test_dates_escribe_fills_y_summary_junto_al_csv(monkeypatch, tmp_path):
    payload = load_fixture(FIXTURE)
    monkeypatch.setenv("DATABENTO_API_KEY", "db-prueba")
    monkeypatch.setattr(
        databento_fetch,
        "_import_databento",
        lambda: types.SimpleNamespace(Historical=lambda key: object()),
    )
    monkeypatch.setattr(
        databento_fetch, "download_definitions", lambda *args, **kwargs: payload["definitions"]
    )
    monkeypatch.setattr(
        databento_fetch, "download_bars", lambda *args, **kwargs: payload["bars"]
    )
    out = tmp_path / "pilot_10_sesiones.csv"

    code = main(["--dates", "2025-07-03", "--out", str(out)])

    assert code == 0
    fills = tmp_path / "pilot_10_sesiones_fills.csv"
    summary_path = tmp_path / "pilot_10_sesiones_summary.json"
    assert out.exists()
    assert fills.exists()
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["out"] == str(out)
    assert summary["fills_out"] == str(fills)
    assert summary["dates"] == ["2025-07-03"]


def test_dates_rechaza_activar_y_escribir_el_csv_completo(tmp_path):
    with pytest.raises(SystemExit):
        main(["--dates", "2025-07-03", "--activate", "--out", str(tmp_path / "p.csv")])

    with pytest.raises(SystemExit):
        main(["--dates", "2025-07-03"])


def test_dates_rechaza_un_dia_sin_sesion_y_el_fixture(monkeypatch, tmp_path):
    with pytest.raises(SystemExit):
        main(["--dates", "2025-07-04", "--out", str(tmp_path / "p.csv")])

    with pytest.raises(SystemExit):
        main(["--dates", "2025-07-03", "--fixture", str(FIXTURE), "--out", str(tmp_path / "p.csv")])


def test_un_error_que_no_es_de_credenciales_se_propaga(monkeypatch, tmp_path):
    _fail_with(500, monkeypatch)

    with pytest.raises(_HttpError):
        main([
            "--start", "2025-01-10",
            "--end", "2025-01-12",
            "--out", str(tmp_path / "bars.csv"),
        ])


@pytest.fixture(autouse=True)
def _esperas(monkeypatch):
    """Ningún test duerme de verdad esperando un reintento."""
    esperas: list[float] = []
    monkeypatch.setattr(databento_fetch.time, "sleep", esperas.append)
    return esperas


def _flaky_client(status: int, failures: int) -> tuple[_FakeClient, dict[str, int]]:
    client = _FakeClient()
    original = client.timeseries.get_range
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise _HttpError(status)
        return original(**kwargs)

    client.timeseries.get_range = flaky
    return client, calls


def test_un_504_se_reintenta_y_termina(_esperas):
    definitions = parse_definitions(load_fixture(FIXTURE)["definitions"])
    client, calls = _flaky_client(504, failures=1)

    records = download_bars(
        client, "GLBX.MDP3", definitions, date(2025, 7, 3), date(2025, 7, 4)
    )

    assert calls["n"] == 2
    assert records[0]["symbol"] == "MNQU5"
    assert _esperas == [2.0]


def test_download_bars_recupera_ts_event_del_indice():
    pd = pytest.importorskip("pandas")
    definitions = parse_definitions(load_fixture(FIXTURE)["definitions"])

    class _FrameData:
        def to_df(self):
            return pd.DataFrame(
                [
                    {
                        "symbol": "MNQU5",
                        "open": 1.0,
                        "high": 1.0,
                        "low": 1.0,
                        "close": 1.0,
                        "volume": 2.0,
                    }
                ],
                index=pd.Index([1751547600000000000], name="ts_event"),
            )

    class _IndexedClient:
        class timeseries:
            @staticmethod
            def get_range(**kwargs):
                return _FrameData()

    records = download_bars(
        _IndexedClient, "GLBX.MDP3", definitions, date(2025, 7, 3), date(2025, 7, 4)
    )

    assert "ts_event" in records[0]
    assert records[0]["symbol"] == "MNQU5"


def test_un_422_no_se_reintenta(_esperas):
    definitions = parse_definitions(load_fixture(FIXTURE)["definitions"])
    client, calls = _flaky_client(422, failures=99)

    with pytest.raises(_HttpError):
        download_bars(client, "GLBX.MDP3", definitions, date(2025, 7, 3), date(2025, 7, 4))

    assert calls["n"] == 1
    assert _esperas == []


def test_un_corte_de_stream_se_reintenta(_esperas):
    """``Response ended prematurely`` no trae http_status pero es transitorio."""
    BentoError = pytest.importorskip("databento.common.error").BentoError
    definitions = parse_definitions(load_fixture(FIXTURE)["definitions"])
    client = _FakeClient()
    original = client.timeseries.get_range
    calls = {"n": 0}

    def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise BentoError("Error streaming response: Response ended prematurely")
        return original(**kwargs)

    client.timeseries.get_range = flaky

    records = download_bars(
        client, "GLBX.MDP3", definitions, date(2025, 7, 3), date(2025, 7, 4)
    )

    assert calls["n"] == 2
    assert records[0]["symbol"] == "MNQU5"
    assert _esperas == [2.0]


def test_un_error_de_programacion_no_se_reintenta(_esperas):
    definitions = parse_definitions(load_fixture(FIXTURE)["definitions"])
    client = _FakeClient()
    calls = {"n": 0}

    def broken(**kwargs):
        calls["n"] += 1
        raise ValueError("error de programación")

    client.timeseries.get_range = broken

    with pytest.raises(ValueError):
        download_bars(client, "GLBX.MDP3", definitions, date(2025, 7, 3), date(2025, 7, 4))

    assert calls["n"] == 1
    assert _esperas == []
