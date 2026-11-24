"""Descarga barras reales de Massive y construye el CSV del bot.

Usa la API de futuros de Massive (plan Futures Basic gratuito): descubre los
contratos trimestrales de MNQ, NQ y ES, descarga agregados de 1 minuto y deja
el CSV largo que consume :mod:`server.market.csv_data`.

La ventana por defecto es **solo desarrollo** (2025-01-10 a 2026-06-30). No se
descarga ni se reproduce el holdout sellado. Para pedir una ventana distinta,
usa ``--start`` y ``--end``; el comando rechaza fechas que entren en el holdout.

Uso::

    set MASSIVE_API_KEY=...          # PowerShell: $env:MASSIVE_API_KEY="..."
    python -m server.market.massive_fetch --activate

La clave se lee de ``MASSIVE_API_KEY`` y nunca se escribe en el CSV, el resumen
ni la configuración. El plan gratuito limita las peticiones a 5 por minuto; el
cliente espacia las llamadas para no agotar la cuota.

Massive no imprime una barra si no hubo operaciones en el minuto. El pipeline
respeta la regla del protocolo: rellena únicamente minutos aislados con una
barra plana y registra cada relleno; dos minutos consecutivos ausentes abortan
la descarga.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

import httpx

from ..config import BASE_DIR, CONFIG_PATH
from .contracts import default_expiry
from .csv_data import REQUIRED_SYMBOLS, inspect_csv
from .databento_fetch import (
    EXPECTED_CODES,
    HOLDOUT_START,
    ROOTS,
    Definition,
    activate_dataset,
    convert,
    relative_path,
    write_csv,
    write_fills,
    write_summary,
)

BASE_URL = "https://api.massive.com"
DEFAULT_START = date(2025, 1, 10)
DEFAULT_END = date(2026, 6, 30)
DEFAULT_OUT = Path("data/real/bars_mnq_nq_es_1m_dev.csv")
CONTRACT_RE = re.compile(r"^(?P<root>MNQ|NQ|ES)(?P<month>[HMUZ])(?P<year>\d{1,2})$")


class MassiveError(RuntimeError):
    """Error de API o de datos de Massive."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_date(value: Any, field: str, ticker: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise MassiveError(f"{ticker}: falta {field}")
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        raise MassiveError(f"{ticker}: {field} inválido ({text!r}); se espera YYYY-MM-DD") from None


def _as_epoch(value: Any) -> int:
    """Convierte window_start (ns, ms o ISO UTC) a segundos UTC."""
    if isinstance(value, datetime):
        instant = value
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        seconds = int(instant.timestamp())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise MassiveError("window_start no finito")
        if abs(number) >= 1e17:
            number /= 1e9
        elif abs(number) >= 1e14:
            number /= 1e6
        elif abs(number) >= 1e11:
            number /= 1e3
        seconds = int(number)
    else:
        text = str(value or "").strip()
        if not text:
            raise MassiveError("window_start vacío")
        try:
            number = float(text)
        except ValueError:
            number = None
        if number is not None:
            return _as_epoch(number)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise MassiveError(f"window_start inválido: {text!r}") from None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = int(parsed.timestamp())
    if seconds % 60:
        raise MassiveError(f"window_start no alineado al minuto: {value!r}")
    return seconds


def _as_float(record: dict[str, Any], field: str, ticker: str) -> float:
    try:
        value = float(record.get(field))
    except (TypeError, ValueError):
        raise MassiveError(f"{ticker}: {field} no numérico") from None
    if not math.isfinite(value):
        raise MassiveError(f"{ticker}: {field} no finito")
    return value


def _candidate_tickers() -> list[str]:
    """Tickers de Massive para los 24 contratos, aceptando año de 1 o 2 dígitos."""
    candidates: list[str] = []
    for code in EXPECTED_CODES:
        root = next((item for item in ROOTS if code.startswith(item)), None)
        if root is None:
            continue
        rest = code[len(root):]
        month = rest[0]
        year = int(rest[1:])
        candidates.extend([f"{root}{month}{year % 10}", f"{root}{month}{year:02d}"])
    return candidates


def parse_contracts(
    records: Iterable[dict[str, Any]], *, require_all: bool = True
) -> dict[str, Definition]:
    """Normaliza los contratos de Massive a los 24 códigos del protocolo."""
    expected = set(EXPECTED_CODES)
    found: dict[str, Definition] = {}
    for record in records:
        raw = str(record.get("ticker") or "").strip().upper()
        match = CONTRACT_RE.fullmatch(raw)
        if match is None:
            continue
        product = str(record.get("product_code") or match.group("root")).strip().upper()
        root = match.group("root")
        if product != root:
            continue
        contract_type = record.get("type")
        if contract_type not in (None, "single"):
            continue
        month_code = match.group("month")
        year_digits = match.group("year")
        year = 2020 + int(year_digits) if len(year_digits) == 1 else 2000 + int(year_digits)
        code = f"{root}{month_code}{year % 100:02d}"
        if code not in expected:
            continue
        expiry = _as_date(
            record.get("settlement_date") or record.get("last_trade_date"),
            "settlement_date/last_trade_date",
            raw,
        )
        if (expiry.year, expiry.month) != (year, {"H": 3, "M": 6, "U": 9, "Z": 12}[month_code]):
            raise MassiveError(
                f"{raw}: vencimiento {expiry.isoformat()} no corresponde al mes del contrato"
            )
        existing = found.get(code)
        if existing is not None:
            if existing.expiry != expiry:
                raise MassiveError(
                    f"{code}: dos vencimientos distintos "
                    f"({existing.expiry.isoformat()} y {expiry.isoformat()})"
                )
            continue
        found[code] = Definition(root=root, raw_symbol=raw, code=code, expiry=expiry)
    missing = [code for code in EXPECTED_CODES if code not in found]
    if missing and require_all:
        raise MassiveError("Faltan contratos del protocolo en Massive: " + ", ".join(missing))
    return {code: found[code] for code in EXPECTED_CODES if code in found}


def definition_records(definitions: dict[str, Definition]) -> list[dict[str, Any]]:
    """Adapta las definiciones al formato que consume ``convert``."""
    return [
        {"raw_symbol": item.raw_symbol, "expiration": item.expiry.isoformat()}
        for item in definitions.values()
    ]


class MassiveClient:
    """Cliente REST mínimo con autenticación, paginación y límite de cuota."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        http_client: httpx.Client | None = None,
        request_interval: float = 12.0,
    ) -> None:
        if not api_key.strip():
            raise MassiveError("MASSIVE_API_KEY vacía")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.request_interval = max(0.0, request_interval)
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(timeout=90.0, follow_redirects=True)
        self._last_request = 0.0
        self.requests = 0

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        for attempt in range(3):
            wait = self.request_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            response = self.http.get(url, params=params, headers=headers)
            self.requests += 1
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(max(self.request_interval, 2.0 * (attempt + 1)))
                continue
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise MassiveError(
                    f"Massive respondió {response.status_code} en {url}: {response.text[:300]}"
                ) from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise MassiveError(f"Massive devolvió JSON inválido en {url}") from exc
            if not isinstance(payload, dict):
                raise MassiveError(f"Massive devolvió una respuesta inesperada en {url}")
            return payload
        raise MassiveError(f"Massive no respondió tras reintentos en {url}")

    def paginate(self, path_or_url: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        url = path_or_url if path_or_url.startswith("http") else f"{self.base_url}{path_or_url}"
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        while url:
            if url in seen:
                raise MassiveError("Massive devolvió un next_url repetido")
            seen.add(url)
            payload = self._get(url, params=params if not results else None)
            page = payload.get("results")
            if not isinstance(page, list):
                raise MassiveError(f"Massive no devolvió results en {url}")
            results.extend(item for item in page if isinstance(item, dict))
            next_url = payload.get("next_url")
            url = str(next_url) if next_url else ""
            params = None
        return results

    def contracts(self) -> list[dict[str, Any]]:
        candidates = _candidate_tickers()
        records: list[dict[str, Any]] = []
        # La API admite listas largas, pero se fragmenta para no depender del
        # límite de longitud de la URL ni de un fallo de validación del servidor.
        for index in range(0, len(candidates), 16):
            chunk = candidates[index:index + 16]
            records.extend(
                self.paginate(
                    "/futures/v1/contracts",
                    {"ticker.any_of": ",".join(chunk), "limit": 1000, "sort": "ticker.asc"},
                )
            )
        return records

    def contracts_at(self, root: str, day: date) -> list[dict[str, Any]]:
        """Fallback para contratos vencidos ausentes de la consulta global."""
        return self.paginate(
            "/futures/v1/contracts",
            {
                "product_code": root,
                "date": day.isoformat(),
                "limit": 1000,
                "sort": "ticker.asc",
            },
        )

    def aggregates(self, ticker: str, start: date, end: date) -> list[dict[str, Any]]:
        return self.paginate(
            f"/futures/v1/aggs/{ticker}",
            {
                "resolution": "1min",
                "window_start.gte": start.isoformat(),
                # La sesión que termina en end puede empezar la tarde anterior.
                "window_start.lte": (end + timedelta(days=1)).isoformat(),
                "limit": 50000,
                "sort": "window_start.asc",
            },
        )


def download_contracts(client: MassiveClient) -> dict[str, Definition]:
    """Descubre los 24 contratos, con fallback por fecha para los vencidos."""
    definitions = parse_contracts(client.contracts(), require_all=False)
    for code in EXPECTED_CODES:
        if code in definitions:
            continue
        root = next(item for item in ROOTS if code.startswith(item))
        month_code = code[len(root)]
        year = 2000 + int(code[len(root) + 1:])
        month = {"H": 3, "M": 6, "U": 9, "Z": 12}[month_code]
        # Una semana antes del vencimiento el contrato está activo en CME.
        probe = default_expiry(year, month) - timedelta(days=7)
        definitions.update(
            parse_contracts(client.contracts_at(root, probe), require_all=False)
        )
    missing = [code for code in EXPECTED_CODES if code not in definitions]
    if missing:
        raise MassiveError("Faltan contratos del protocolo en Massive: " + ", ".join(missing))
    return {code: definitions[code] for code in EXPECTED_CODES}


def _log(message: str) -> None:
    """Progreso con hora local; sin esto la descarga parece colgada."""
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def _et_day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=ET).date().isoformat()


def _alternate_tickers(raw_symbol: str) -> list[str]:
    """El mismo contrato con el año en el otro formato (1 o 2 dígitos)."""
    current = raw_symbol.strip().upper()
    match = CONTRACT_RE.fullmatch(current)
    if match is None:
        return []
    root, month, digits = match.group("root"), match.group("month"), match.group("year")
    year = 2020 + int(digits) if len(digits) == 1 else 2000 + int(digits)
    both = [f"{root}{month}{year % 10}", f"{root}{month}{year % 100:02d}"]
    return [ticker for ticker in both if ticker != current]


def _contract_bars(
    client: MassiveClient,
    definition: Definition,
    ticker: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Barras de un ticker concreto, normalizadas al contrato del protocolo."""
    bars: list[dict[str, Any]] = []
    for record in client.aggregates(ticker, start, end):
        reported = str(record.get("ticker") or ticker).upper()
        if reported != ticker.upper():
            raise MassiveError(
                f"{definition.code}: Massive devolvió ticker {reported!r} para {ticker!r}"
            )
        if "window_start" not in record:
            raise MassiveError(f"{definition.code}: barra sin window_start")
        values = {
            field: _as_float(record, field, reported)
            for field in ("open", "high", "low", "close")
        }
        volume = _as_float(record, "volume", reported)
        if min(values.values()) <= 0 or volume < 0:
            raise MassiveError(f"{definition.code}: OHLC/volumen inválido")
        bars.append(
            {
                "symbol": definition.raw_symbol,
                "ts_event": _as_epoch(record["window_start"]),
                **values,
                "volume": volume,
            }
        )
    return bars


def needed_definitions(
    definitions: dict[str, Definition], start: date, end: date
) -> list[Definition]:
    """Contratos cuya vigencia se cruza con la ventana solicitada.

    Un contrato está vigente desde el día siguiente al roll del anterior hasta
    su propio roll, ambos inclusive. Hay que incluir el siguiente aunque su
    roll caiga después de ``end``: si no, las últimas sesiones quedan sin serie
    activa y ``convert`` las rechaza.
    """
    needed: list[Definition] = []
    for root in ROOTS:
        chain = sorted(
            (definition for definition in definitions.values() if definition.root == root),
            key=lambda definition: (definition.expiry, definition.code),
        )
        active_from = date.min
        for definition in chain:
            if definition.roll_date >= start and active_from <= end:
                needed.append(definition)
            active_from = definition.roll_date
    return needed


def download_bars(
    client: MassiveClient,
    definitions: dict[str, Definition],
    start: date,
    end: date,
    *,
    log: Callable[[str], None] = _log,
) -> list[dict[str, Any]]:
    """Descarga solo contratos activos en la ventana solicitada."""
    active = needed_definitions(definitions, start, end)
    records: list[dict[str, Any]] = []
    total = len(active)
    log(
        f"Contratos activos en la ventana: {total}; "
        f"una petición cada {client.request_interval:.0f}s como máximo."
    )
    for index, definition in enumerate(active, start=1):
        log(f"[{index}/{total}] {definition.code} ({definition.raw_symbol}): descargando...")
        requests_before = client.requests
        candidates = [definition.raw_symbol, *_alternate_tickers(definition.raw_symbol)]
        fetched_bars: list[dict[str, Any]] = []
        used_ticker = ""
        for attempt, ticker in enumerate(candidates):
            if attempt:
                log(
                    f"[{index}/{total}] {definition.code}: {definition.raw_symbol} sin velas; "
                    f"probando {ticker}..."
                )
            fetched_bars = _contract_bars(client, definition, ticker, start, end)
            if fetched_bars:
                used_ticker = ticker
                break
        if not fetched_bars:
            raise MassiveError(
                f"{definition.code}: Massive no devolvió velas para "
                f"{', '.join(candidates)} entre {start} y {end}; "
                "sin ese contrato la descarga queda incompleta"
            )
        records.extend(fetched_bars)
        first = _et_day(min(bar["ts_event"] for bar in fetched_bars))
        last = _et_day(max(bar["ts_event"] for bar in fetched_bars))
        log(
            f"[{index}/{total}] {definition.code}: {len(fetched_bars)} velas ({first} -> {last}) "
            f"vía {used_ticker}, {client.requests - requests_before} peticiones, "
            f"acumulado {len(records)}."
        )
    return records


def _cache_handle(path: Path, mode: str, *, compressed: bool):
    if compressed:
        return gzip.open(path, mode + "t", encoding="utf-8")
    return path.open(mode, encoding="utf-8", newline="\n")


def save_raw_cache(
    path: Path,
    start: date,
    end: date,
    definitions: Sequence[dict[str, Any]],
    bars: Sequence[dict[str, Any]],
) -> None:
    """Guarda definiciones y velas crudas para reconvertir sin gastar cuota.

    La primera linea es la cabecera y cada linea siguiente, una vela. Sin
    marcas por linea: con millones de barras cualquier campo extra pesa.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    header = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "definitions": list(definitions),
    }
    with _cache_handle(tmp, "w", compressed=path.suffix.lower() == ".gz") as handle:
        handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        for bar in bars:
            handle.write(json.dumps(bar) + "\n")
    tmp.replace(path)


def load_raw_cache(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Lee un cache creado por :func:`save_raw_cache`."""
    with _cache_handle(path, "r", compressed=path.suffix.lower() == ".gz") as handle:
        header = handle.readline()
        if not header.strip():
            raise ValueError(f"{path}: cache vacío")
        meta = json.loads(header)
        faltan = [key for key in ("start", "end", "definitions") if key not in meta]
        if faltan:
            raise ValueError(f"{path}: cache sin {', '.join(faltan)}")
        bars = [json.loads(line) for line in handle if line.strip()]
    return meta, bars


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Descarga MNQ/NQ/ES de 1 minuto desde Massive y genera el CSV real del bot."
        )
    )
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fills-out", type=Path, default=None)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help=(
            "Guarda la descarga cruda en .jsonl o .jsonl.gz y la reutiliza en la "
            "siguiente ejecución con la misma ventana; reconvierte sin gastar cuota."
        ),
    )
    parser.add_argument("--api-key-env", default="MASSIVE_API_KEY")
    parser.add_argument(
        "--request-interval",
        type=float,
        default=12.0,
        help="Segundos entre peticiones (plan gratuito: 5/minuto).",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Activa el CSV en data/config.json solo si la validación es correcta.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start > args.end:
        parser.error("--start no puede ser posterior a --end")
    if args.end >= HOLDOUT_START:
        parser.error(
            "La ventana termina dentro del holdout sellado (2026-07-01 → 2026-10-30). "
            "Usa --end 2026-06-30 para el dataset de desarrollo."
        )
    cache_path = None
    if args.cache is not None:
        cache_path = args.cache.expanduser()
        if not cache_path.is_absolute():
            cache_path = BASE_DIR / cache_path

    out = args.out.expanduser()
    if not out.is_absolute():
        out = BASE_DIR / out
    fills_out = args.fills_out or out.with_name(out.stem + "_fills.csv")
    summary_path = args.summary or out.with_name(out.stem + "_summary.json")
    if not fills_out.is_absolute():
        fills_out = BASE_DIR / fills_out
    if not summary_path.is_absolute():
        summary_path = BASE_DIR / summary_path

    if cache_path is not None and cache_path.exists():
        meta, bars = load_raw_cache(cache_path)
        definition_rows = meta["definitions"]
        cached = (date.fromisoformat(meta["start"]), date.fromisoformat(meta["end"]))
        if cached != (args.start, args.end):
            parser.error(
                f"El cache {cache_path} cubre {cached[0]} -> {cached[1]}; pide esa "
                "ventana o borra el archivo."
            )
        _log(f"Cache: {len(bars)} velas y {len(definition_rows)} contratos ({cache_path}).")
    else:
        api_key = os.environ.get(args.api_key_env, "").strip()
        if not api_key:
            raise SystemExit(
                f"Falta {args.api_key_env}. Crea una cuenta gratuita en "
                "https://massive.com/dashboard/signup y expórtala en la terminal; "
                "no la pegues en el chat ni en el repositorio.\n"
                "PowerShell: $env:MASSIVE_API_KEY=\"...\""
            )
        client = MassiveClient(api_key, request_interval=args.request_interval)
        try:
            _log("Consultando contratos trimestrales en Massive...")
            definitions = download_contracts(client)
            _log(f"Contratos del protocolo encontrados: {len(definitions)}/24.")
            _log(f"Descargando velas 1m de {args.start} a {args.end}...")
            bars = download_bars(client, definitions, args.start, args.end)
        finally:
            client.close()
        definition_rows = definition_records(definitions)
        if cache_path is not None and bars:
            save_raw_cache(cache_path, args.start, args.end, definition_rows, bars)
            _log(f"Crudo guardado en {cache_path}: {len(bars)} velas.")

    if not bars:
        raise SystemExit("Massive no devolvió ninguna barra para la ventana solicitada.")

    result = convert(definition_rows, bars, args.start, args.end)
    tmp = out.with_name(out.name + ".tmp")
    write_csv(tmp, result.rows)
    try:
        report = inspect_csv(tmp, REQUIRED_SYMBOLS, series_mode="raw", exclude_roll_sessions=True)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    if not report.get("ok"):
        tmp.unlink(missing_ok=True)
        details = "; ".join(report.get("errors") or ["validación fallida"])
        raise SystemExit(f"El CSV no pasó la validación; no se activa. {details}")
    tmp.replace(out)

    summary = dict(result.summary)
    summary.update(
        {
            "source": "massive:futures-v1",
            "api": "https://api.massive.com/futures/v1",
            "out": str(out),
            "fills_out": str(fills_out),
            "file_sha256": _sha256(out),
            "validation": {
                "ok": report.get("ok"),
                "aligned": report.get("aligned"),
                "sessions": report.get("session_count"),
                "invalid_sessions": (report.get("session_validation") or {}).get("invalid_sessions"),
                "missing_sessions": (report.get("session_validation") or {}).get("missing_session_count"),
                "dataset_id": report.get("dataset_id"),
                "series_id": report.get("series_id"),
            },
        }
    )
    if cache_path is not None:
        summary["cache"] = relative_path(cache_path)
    write_fills(fills_out, result.fills)
    write_summary(summary_path, summary)
    if args.activate:
        activate_dataset(out)

    print(
        f"Listo: {summary['rows']} filas, {summary['session_count']} sesiones, "
        f"{summary['fills']} rellenos ({summary['fill_share']:.4%})."
    )
    print(f"CSV: {out}")
    print(f"Rellenos: {fills_out}")
    print(f"Resumen: {summary_path}")
    if args.activate:
        print(
            f"Configuración activada en {relative_path(CONFIG_PATH)}; "
            "el motor espera inicio manual."
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())