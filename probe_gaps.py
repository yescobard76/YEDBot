"""Sondeo puntual de un tramo donde la descarga de 1 minuto no trae velas.

No descarga el dataset, no escribe caché ni CSV: pide el mismo tramo a varias
resoluciones para distinguir un fallo de agregación de una ausencia real de
operaciones. Massive construye los agregados desde trades, así que un minuto
sin barra significa "sin operaciones para su feed"; si a 1 segundo o 5 minutos
el tramo sí aparece, el hueco es de la agregación.

La API filtra por ``window_start`` con una fecha o con epoch en **nanosegundos**
(no admite ISO con hora) y ajusta el valor al inicio de la vela, así que el
sondeo manda nanosegundos para pedir exactamente el tramo.

Uso::

    $env:MASSIVE_API_KEY="..."
    python probe_gaps.py --date 2025-01-16 --ticker MNQH5 --from 13:55 --to 14:25
    python probe_gaps.py --date 2025-06-12 --ticker NQU5 --from 09:15 --to 09:26

La ventana se interpreta en hora del Este (America/New_York), igual que el
resto del proyecto, y las peticiones respetan el límite de 5 por minuto.

Ojo con el plan: Futures Basic incluye *minute aggregates* (1min, 5min, ...),
pero los *second aggregates* empiezan en Futures Starter. Pedir ``1sec`` en
Basic devuelve 403; cada resolución se informa por separado para que una no
tape las demás.

El informe acaba con una línea ``Conclusión:`` para no tener que interpretar
las barras: si en los minutos que faltan en 1min hay barras de 5min con
transacciones, el hueco es un fallo de agregación; si no hay ninguna, no hubo
operaciones y el hueco es del proveedor.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.market.massive_fetch import MassiveClient, MassiveError  # noqa: E402

ET = ZoneInfo("America/New_York")
NS = 1_000_000_000


def _epoch_seconds(value: Any) -> int:
    """``window_start`` (epoch en nanosegundos) -> segundos UTC."""
    number = int(value)
    while number > 4_102_444_800:  # 2100-01-01 en segundos
        number //= 1000
    return number


def _hhmm(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=ET).strftime("%H:%M")


def _window(args: argparse.Namespace) -> tuple[int, int]:
    start = datetime.combine(args.date, time.fromisoformat(args.time_from), tzinfo=ET)
    end = datetime.combine(args.date, time.fromisoformat(args.time_to), tzinfo=ET)
    if end <= start:
        raise SystemExit("--to debe ser posterior a --from")
    return int(start.timestamp()), int(end.timestamp())


Bar = tuple[int, int, float]  # inicio en segundos, transacciones, volumen


@dataclass
class Report:
    """Detalle por resolución y la conclusión que lo resume."""

    lines: list[str]
    conclusion: str


def _bars(records: list[dict[str, Any]]) -> list[Bar]:
    bars: list[Bar] = []
    for record in records:
        if "window_start" not in record:
            continue
        bars.append(
            (
                _epoch_seconds(record["window_start"]),
                int(record.get("transactions") or 0),
                float(record.get("volume") or 0),
            )
        )
    return sorted(bars)


def _conclusion(five_min: list[Bar] | None, one_min: set[int] | None) -> str:
    """Traduce el sondeo: agregación rota o hueco real, sin lectura manual."""
    if five_min is None:
        return (
            "Conclusión: falta el sondeo a 5min y no se puede decidir; "
            "repítelo con --resolutions 1min,5min."
        )
    if not five_min:
        return (
            "Conclusión: 0 barras de 5min en el tramo; el proveedor no reporta "
            "operaciones ahí y el hueco no se puede reconstruir."
        )
    if one_min:
        inside = [
            bar for bar in five_min if any(bar[0] + 60 * i not in one_min for i in range(5))
        ]
        if not inside:
            return "Conclusión: el 1min cubrió el tramo; no hay hueco que explicar."
        scope = "en los minutos sin vela de 1min"
    else:
        inside = five_min
        scope = "en el tramo"
    transactions = sum(bar[1] for bar in inside)
    volume = sum(bar[2] for bar in inside)
    if transactions or volume:
        noun = "barra" if len(inside) == 1 else "barras"
        return (
            f"Conclusión: hubo operaciones {scope} ({len(inside)} {noun} de 5min, "
            f"{transactions} transacciones, volumen {volume:g}); el hueco es un fallo "
            "de agregación del 1min, no ausencia de mercado."
        )
    return (
        "Conclusión: las barras de 5min solo cubren minutos que el 1min ya trae; "
        "en los que faltan no hubo operaciones, así que es un hueco del proveedor."
    )


def probe(
    client: MassiveClient,
    ticker: str,
    start: int,
    end: int,
    resolutions: Iterable[str],
) -> Report:
    """Pide el tramo a cada resolución y devuelve el informe en texto."""
    lines: list[str] = []
    five_min: list[Bar] | None = None
    one_min: set[int] | None = None
    for resolution in resolutions:
        try:
            records = client.paginate(
                f"/futures/v1/aggs/{ticker}",
                {
                    "resolution": resolution,
                    "window_start.gte": str(start * NS),
                    # -1 ns: excluye la barra que empieza justo en el fin del tramo.
                    "window_start.lte": str(end * NS - 1),
                    "limit": 50000,
                    "sort": "window_start.asc",
                },
            )
        except MassiveError as exc:
            # Un 403 es del plan, no del tramo: se informa y se sigue con la siguiente.
            if " 403 " in f" {exc} ":
                lines.append(f"  {resolution:<5} no incluido en el plan (403)")
                continue
            raise
        bars = _bars(records)
        if resolution == "5min":
            five_min = bars
        elif resolution == "1min":
            one_min = {bar[0] for bar in bars}
        if not bars:
            lines.append(f"  {resolution:<5} 0 barras: el proveedor no tiene velas en el tramo")
            continue
        if resolution.endswith("sec"):
            lines.append(
                f"  {resolution:<5} {len(bars)} barras de {_hhmm(bars[0][0])} "
                f"a {_hhmm(bars[-1][0])}"
            )
            continue
        transactions = sum(bar[1] for bar in bars)
        volume = sum(bar[2] for bar in bars)
        lines.append(
            f"  {resolution:<5} {len(bars)} barras, {transactions} transacciones, "
            f"volumen {volume:g}"
        )
        lines.append("        " + ", ".join(_hhmm(bar[0]) for bar in bars))
    return Report(lines, _conclusion(five_min, one_min))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sondea un tramo de Massive a varias resoluciones (solo lectura)."
    )
    parser.add_argument("--date", type=date.fromisoformat, required=True, help="Día ET a sondear")
    parser.add_argument("--ticker", required=True, help="Ticker del contrato, p. ej. MNQH5")
    parser.add_argument("--from", dest="time_from", default="09:00", help="Inicio ET (HH:MM)")
    parser.add_argument("--to", dest="time_to", default="16:00", help="Fin ET (HH:MM)")
    parser.add_argument(
        "--resolutions",
        default="1min,5min",
        help="Resoluciones separadas por coma (unidad: sec, min, hour)",
    )
    parser.add_argument("--api-key-env", default="MASSIVE_API_KEY")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        parser.error(f"Falta {args.api_key_env} en el entorno")

    ticker = args.ticker.strip().upper()
    start, end = _window(args)
    resolutions = [item.strip() for item in args.resolutions.split(",") if item.strip()]
    print(f"{ticker} {args.date} {args.time_from}-{args.time_to} ET")
    client = MassiveClient(api_key)
    try:
        report = probe(client, ticker, start, end, resolutions)
    except MassiveError as exc:
        print(f"Error de Massive: {exc}")
        return 1
    finally:
        client.close()
    for line in report.lines:
        print(line)
    print(f"Peticiones: {client.requests}")
    print(report.conclusion)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
