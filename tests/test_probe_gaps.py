"""Pruebas del sondeo de huecos sin red ni credenciales."""

from __future__ import annotations

from datetime import date

from probe_gaps import _epoch_seconds, probe
from server.market.massive_fetch import MassiveError
from server.timeutil import timestamp_for


class _StubClient:
    def __init__(self, stamp: int) -> None:
        self.stamp = stamp
        self.calls: list[tuple[str, dict[str, object]]] = []

    def paginate(self, path: str, params: dict[str, object] | None = None):
        assert params is not None
        self.calls.append((path, params))
        return [{"window_start": str(self.stamp * 1_000_000_000)}]


def test_probe_pide_el_tramo_en_nanosegundos_y_una_llamada_por_resolucion():
    stamp = timestamp_for(date(2025, 1, 16), "13:55")
    client = _StubClient(stamp)

    report = probe(client, "MNQH5", stamp, stamp + 1800, ["1sec", "1min", "5min"])

    assert [path for path, _ in client.calls] == ["/futures/v1/aggs/MNQH5"] * 3
    assert [params["resolution"] for _, params in client.calls] == ["1sec", "1min", "5min"]
    for _, params in client.calls:
        assert params["window_start.gte"] == str(stamp * 1_000_000_000)
        assert params["window_start.lte"] == str((stamp + 1800) * 1_000_000_000 - 1)
        assert params["limit"] == 50000
        assert params["sort"] == "window_start.asc"
    assert _epoch_seconds(str(stamp * 1_000_000_000)) == stamp
    assert any("13:55" in line for line in report.lines)
    assert report.conclusion.startswith("Conclusión:")


def test_probe_una_resolucion_sin_plan_no_tapa_las_demas():
    stamp = timestamp_for(date(2025, 1, 16), "14:00")

    class _MixedClient:
        def paginate(self, path: str, params: dict[str, object] | None = None):
            assert params is not None
            if params["resolution"] == "1sec":
                raise MassiveError(
                    "Massive respondió 403 en https://api.massive.com/futures/v1/aggs/MNQH5"
                )
            return [
                {
                    "window_start": str(stamp * 1_000_000_000),
                    "transactions": 7,
                    "volume": 120,
                }
            ]

    report = probe(_MixedClient(), "MNQH5", stamp, stamp + 300, ["1sec", "5min"])

    assert "403" in report.lines[0] and "plan" in report.lines[0]
    assert any("7 transacciones" in line and "volumen 120" in line for line in report.lines)
    assert any("14:00" in line for line in report.lines)


def test_probe_concluye_fallo_de_agregacion_si_el_5min_tiene_operaciones_en_el_hueco():
    stamp = timestamp_for(date(2025, 1, 16), "14:00")

    class _GapClient:
        def paginate(self, path: str, params: dict[str, object] | None = None):
            assert params is not None
            if params["resolution"] == "1min":
                return []  # el 1min no trae ninguna vela del tramo
            return [
                {
                    "window_start": str((stamp + 300 * i) * 1_000_000_000),
                    "transactions": 5,
                    "volume": 75,
                }
                for i in range(4)
            ]

    report = probe(_GapClient(), "MNQH5", stamp, stamp + 1200, ["1min", "5min"])

    assert "fallo de agregación" in report.conclusion
    assert "20 transacciones" in report.conclusion


def test_probe_solo_cuenta_las_barras_de_5min_que_cubren_el_hueco():
    base = timestamp_for(date(2025, 1, 16), "13:55")

    class _PartialClient:
        def paginate(self, path: str, params: dict[str, object] | None = None):
            assert params is not None
            if params["resolution"] == "1min":
                # 1min trae 13:55-13:59; falta desde las 14:00.
                return [{"window_start": str((base + 60 * i) * 1_000_000_000)} for i in range(5)]
            return [
                {"window_start": str(base * 1_000_000_000), "transactions": 100, "volume": 900},
                {
                    "window_start": str((base + 300) * 1_000_000_000),
                    "transactions": 5,
                    "volume": 75,
                },
            ]

    report = probe(_PartialClient(), "MNQH5", base, base + 600, ["1min", "5min"])

    assert "1 barra de 5min" in report.conclusion
    assert "5 transacciones" in report.conclusion
    assert "100" not in report.conclusion
    assert "fallo de agregación" in report.conclusion


def test_probe_concluye_que_no_hay_hueco_si_el_1min_cubre_todo():
    base = timestamp_for(date(2025, 1, 16), "14:00")

    class _FullClient:
        def paginate(self, path: str, params: dict[str, object] | None = None):
            assert params is not None
            if params["resolution"] == "1min":
                return [{"window_start": str((base + 60 * i) * 1_000_000_000)} for i in range(5)]
            return [{"window_start": str(base * 1_000_000_000), "transactions": 9, "volume": 90}]

    report = probe(_FullClient(), "MNQH5", base, base + 300, ["1min", "5min"])

    assert "no hay hueco" in report.conclusion


def test_probe_concluye_hueco_del_proveedor_si_el_5min_tampoco_tiene_barras():
    class _EmptyClient:
        def paginate(self, path: str, params: dict[str, object] | None = None):
            return []

    report = probe(_EmptyClient(), "MNQH5", 0, 60, ["1min", "5min"])

    assert "0 barras" in report.lines[0]
    assert "proveedor" in report.conclusion
    assert "agregación" not in report.conclusion


def test_probe_sin_5min_no_inventa_conclusion():
    client = _StubClient(0)

    report = probe(client, "MNQH5", 0, 60, ["1min"])

    assert "5min" in report.conclusion
    assert "no se puede decidir" in report.conclusion
