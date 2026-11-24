"""Pruebas del adaptador Massive sin red, credenciales ni backtest."""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from server.market.contracts import default_expiry
from server.market.csv_data import REQUIRED_SYMBOLS
from server.market.databento_fetch import EXPECTED_CODES, ROOTS
from server.market.massive_fetch import (
    MassiveClient,
    MassiveError,
    definition_records,
    download_bars,
    download_contracts,
    load_raw_cache,
    main,
    needed_definitions,
    parse_contracts,
    save_raw_cache,
)
from server.timeutil import timestamp_for

MONTH_NUMBER = {"H": 3, "M": 6, "U": 9, "Z": 12}


def test_required_symbols_are_mnq_nq_es():
    assert REQUIRED_SYMBOLS == ("MNQ", "NQ", "ES")


def _contract_rows():
    rows = []
    for code in EXPECTED_CODES:
        root = next(item for item in ROOTS if code.startswith(item))
        month_code = code[len(root)]
        year = 2000 + int(code[len(root) + 1:])
        ticker = f"{root}{month_code}{year % 10}"
        rows.append(
            {
                "ticker": ticker,
                "product_code": root,
                "type": "single",
                "settlement_date": default_expiry(year, MONTH_NUMBER[month_code]).isoformat(),
                "last_trade_date": default_expiry(year, MONTH_NUMBER[month_code]).isoformat(),
            }
        )
    return rows


def test_parse_contracts_normalizes_24_contracts():
    definitions = parse_contracts(_contract_rows())

    assert set(definitions) == set(EXPECTED_CODES)
    assert len(definitions) == 24
    assert definitions["MNQH25"].raw_symbol == "MNQH5"
    assert definitions["MNQH25"].expiry == date(2025, 3, 21)
    assert definitions["ESZ26"].raw_symbol == "ESZ6"


def test_parse_contracts_rejects_conflicting_expiries():
    rows = _contract_rows()
    rows[0]["settlement_date"] = "2025-03-14"

    with pytest.raises(MassiveError, match="dos vencimientos distintos"):
        parse_contracts(rows + [rows[0] | {"settlement_date": "2025-03-21"}])


def test_download_contracts_uses_date_fallback_for_missing_contract():
    rows = _contract_rows()

    class StubClient:
        def contracts(self):
            return rows[:-1]

        def contracts_at(self, root, day):
            assert root == "ES"
            assert day.year == 2026
            return [rows[-1]]

    definitions = download_contracts(StubClient())

    assert set(definitions) == set(EXPECTED_CODES)


def test_download_bars_calls_contract_aggregate_and_normalizes_record():
    definitions = parse_contracts(_contract_rows())
    start = date(2025, 1, 10)
    end = date(2025, 3, 14)
    stamp = timestamp_for(date(2025, 1, 10), "09:30")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/futures/v1/aggs/MNQH5"
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.url.params["resolution"] == "1min"
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "ticker": "MNQH5",
                        "window_start": str(stamp * 1_000_000_000),
                        "open": 20000.0,
                        "high": 20010.0,
                        "low": 19990.0,
                        "close": 20005.0,
                        "volume": 120,
                    }
                ],
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = MassiveClient("test-key", http_client=http, request_interval=0)
    try:
        records = download_bars(client, {"MNQH25": definitions["MNQH25"]}, start, end)
    finally:
        client.close()
        http.close()

    assert len(calls) == 1
    assert records == [
        {
            "symbol": "MNQH5",
            "ts_event": stamp,
            "open": 20000.0,
            "high": 20010.0,
            "low": 19990.0,
            "close": 20005.0,
            "volume": 120.0,
        }
    ]


def test_needed_definitions_incluye_el_contrato_que_cruza_el_fin_de_la_ventana():
    definitions = parse_contracts(_contract_rows())

    needed = needed_definitions(definitions, date(2025, 1, 10), date(2026, 6, 30))
    codes = {definition.code for definition in needed}

    # Su vigencia arranca con el roll del contrato de junio (2026-06-10) y su
    # propio roll cae en septiembre, después de --end. Sin él, las últimas
    # sesiones de la ventana no tienen serie activa.
    assert {"MNQU26", "NQU26", "ESU26"} <= codes
    assert "MNQZ26" not in codes
    assert "MNQH25" in codes
    assert len(needed) == 21


def test_download_bars_prueba_el_otro_formato_de_ticker_si_no_hay_velas():
    definitions = parse_contracts(_contract_rows())
    start = date(2025, 1, 10)
    end = date(2025, 3, 14)
    stamp = timestamp_for(start, "09:30")
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("MNQH5"):
            return httpx.Response(200, json={"status": "OK", "results": []})
        assert request.url.path.endswith("MNQH25")
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "ticker": "MNQH25",
                        "window_start": str(stamp * 1_000_000_000),
                        "open": 20000.0,
                        "high": 20010.0,
                        "low": 19990.0,
                        "close": 20005.0,
                        "volume": 120,
                    }
                ],
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = MassiveClient("test-key", http_client=http, request_interval=0)
    try:
        records = download_bars(
            client,
            {"MNQH25": definitions["MNQH25"]},
            start,
            end,
            log=lambda message: None,
        )
    finally:
        client.close()
        http.close()

    assert paths == ["/futures/v1/aggs/MNQH5", "/futures/v1/aggs/MNQH25"]
    assert records == [
        {
            "symbol": "MNQH5",
            "ts_event": stamp,
            "open": 20000.0,
            "high": 20010.0,
            "low": 19990.0,
            "close": 20005.0,
            "volume": 120.0,
        }
    ]


def test_download_bars_aborta_si_un_contrato_no_trae_velas():
    definitions = parse_contracts(_contract_rows())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "OK", "results": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = MassiveClient("test-key", http_client=http, request_interval=0)
    try:
        with pytest.raises(MassiveError, match="no devolvió velas para"):
            download_bars(
                client,
                {"MNQH25": definitions["MNQH25"]},
                date(2025, 1, 10),
                date(2025, 3, 14),
                log=lambda message: None,
            )
    finally:
        client.close()
        http.close()


def test_paginate_follows_next_url():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "results": [{"ticker": "MNQH5"}],
                    "next_url": "https://api.massive.com/futures/v1/contracts?cursor=abc",
                },
            )
        return httpx.Response(200, json={"results": [{"ticker": "NQH5"}]})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = MassiveClient("test-key", http_client=http, request_interval=0)
    try:
        rows = client.paginate("/futures/v1/contracts", {"limit": 1})
    finally:
        client.close()
        http.close()

    assert [row["ticker"] for row in rows] == ["MNQH5", "NQH5"]
    assert len(calls) == 2


def test_massive_mode_requires_api_key(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="MASSIVE_API_KEY"):
        main([])


def test_massive_refuses_holdout_window():
    with pytest.raises(SystemExit):
        main(["--end", "2026-07-01"])


def _sample_bar() -> dict[str, object]:
    return {
        "symbol": "MNQH5",
        "ts_event": timestamp_for(date(2025, 1, 16), "09:30"),
        "open": 20000.0,
        "high": 20010.0,
        "low": 19990.0,
        "close": 20005.0,
        "volume": 120.0,
    }


def test_cache_crudo_conserva_definiciones_y_velas(tmp_path):
    definitions = parse_contracts(_contract_rows())
    bars = [_sample_bar()]
    path = tmp_path / "raw.jsonl.gz"

    save_raw_cache(
        path, date(2025, 1, 16), date(2025, 1, 16), definition_records(definitions), bars
    )
    meta, loaded = load_raw_cache(path)

    assert meta["start"] == "2025-01-16"
    assert meta["end"] == "2025-01-16"
    assert len(meta["definitions"]) == 24
    assert loaded == bars


def test_cache_incompleto_falla_con_mensaje_claro(tmp_path):
    path = tmp_path / "raw.jsonl"
    path.write_text('{"start": "2025-01-16"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="cache sin end, definitions"):
        load_raw_cache(path)

    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cache vacío"):
        load_raw_cache(empty)


def test_main_rechaza_un_cache_de_otra_ventana(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    definitions = parse_contracts(_contract_rows())
    cache = tmp_path / "raw.jsonl"
    save_raw_cache(
        cache,
        date(2025, 1, 16),
        date(2025, 1, 16),
        definition_records(definitions),
        [_sample_bar()],
    )

    with pytest.raises(SystemExit):
        main(
            [
                "--start",
                "2025-01-17",
                "--end",
                "2025-01-17",
                "--out",
                str(tmp_path / "out.csv"),
                "--cache",
                str(cache),
            ]
        )
    assert "cubre 2025-01-16 -> 2025-01-16" in capsys.readouterr().err


def test_main_reconvierte_desde_el_cache_sin_clave(tmp_path, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    definitions = parse_contracts(_contract_rows())
    cache = tmp_path / "raw.jsonl"
    save_raw_cache(
        cache,
        date(2025, 1, 16),
        date(2025, 1, 16),
        definition_records(definitions),
        [_sample_bar()],
    )

    # Sin clave: si intentara descargar, el error sería MASSIVE_API_KEY. Al llegar
    # al convert y señalar el hueco con su horario, demuestra que usó el cache.
    with pytest.raises(ValueError, match=r"minutos consecutivos.*\(09:00 -> 09:30\)"):
        main(
            [
                "--start",
                "2025-01-16",
                "--end",
                "2025-01-16",
                "--out",
                str(tmp_path / "out.csv"),
                "--cache",
                str(cache),
            ]
        )