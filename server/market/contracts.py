"""Calendario y selección de contratos de futuros.

El CSV puede declarar el contrato real (``MNQZ26``) y, opcionalmente, su fecha
de vencimiento (``expiry``). Cuando no se declara ``expiry`` se usa el tercer
viernes del mes del contrato, convención de los futuros de índices del CME.

La selección del contrato activo es determinista: para cada sesión se elige,
entre los contratos con barras ese día, el de vencimiento más próximo que aún
no ha vencido. El primer día en que cambia ese contrato es la sesión de roll.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from functools import lru_cache

MONTH_CODES = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}
CODE_MONTHS = {value: key for key, value in MONTH_CODES.items()}


@dataclass(frozen=True, slots=True)
class ContractSpec:
    """Contrato declarado en el CSV."""

    code: str
    root: str
    month: int
    year: int
    expiry: date

    @property
    def month_code(self) -> str:
        return CODE_MONTHS[self.month]

    def with_expiry(self, expiry: date) -> "ContractSpec":
        return replace(self, expiry=expiry)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


@lru_cache(maxsize=256)
def default_expiry(year: int, month: int) -> date:
    """Tercer viernes del mes, o el día hábil anterior si es feriado.

    Es la convención de vencimiento de los futuros de índices del CME. El
    ajuste por feriado cubre casos como el Viernes Santo, que puede coincidir
    con el tercer viernes.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"Mes de contrato inválido: {month}")
    expiry = _nth_weekday(year, month, 4, 3)
    # Import local para mantener contracts.py independiente de la carga del
    # calendario de sesiones y evitar un ciclo de importación.
    from .sessions import is_trading_day

    while not is_trading_day(expiry):
        expiry -= timedelta(days=1)
    return expiry


def parse_contract(code: str, symbol: str | None = None) -> ContractSpec:
    """Convierte ``MNQZ26`` en un :class:`ContractSpec`.

    ``symbol`` actúa como raíz esperada: si se indica, el contrato debe
    pertenecer a ese símbolo. El parser acepta raíces de 1 a 5 letras y exige
    el formato mes (F..Z) + dos dígitos de año.
    """
    raw = (code or "").strip().upper()
    if not raw:
        raise ValueError("contract vacío")
    expected = (symbol or "").strip().upper()
    if expected:
        if not raw.startswith(expected):
            raise ValueError(f"contract {raw!r} no corresponde al símbolo {expected}")
        rest = raw[len(expected):]
    else:
        rest = raw[-3:]
    if len(rest) != 3:
        raise ValueError(f"contract {raw!r} inválido; usa raíz+mes+año (ej. MNQZ26)")
    month_code, year_digits = rest[0], rest[1:]
    if month_code not in MONTH_CODES or not year_digits.isdigit():
        raise ValueError(f"contract {raw!r} inválido; mes F..Z y año de dos dígitos")
    root = expected or raw[:-3]
    if not root.isalpha() or not 1 <= len(root) <= 5:
        raise ValueError(f"contract {raw!r} inválido; raíz no válida")
    month = MONTH_CODES[month_code]
    year = 2000 + int(year_digits)
    return ContractSpec(
        code=raw,
        root=root,
        month=month,
        year=year,
        expiry=default_expiry(year, month),
    )


def parse_expiry(raw: str) -> date:
    """Fecha ISO ``YYYY-MM-DD`` del CSV."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("expiry vacío")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"expiry inválido {value!r}; usa YYYY-MM-DD") from None


def select_active_contract(candidates: list[ContractSpec], day: date) -> ContractSpec | None:
    """Contrato vigente con vencimiento más próximo para ``day``.

    Un contrato se considera vigente hasta su fecha de vencimiento inclusive.
    Si hay varios con el mismo vencimiento se desempata por código para que la
    selección sea estable.
    """
    valid = [spec for spec in candidates if spec.expiry >= day]
    if not valid:
        return None
    return min(valid, key=lambda spec: (spec.expiry, spec.code))


def roll_dates(specs: list[ContractSpec], sessions: list[date]) -> list[date]:
    """Sesiones donde cambia el contrato activo (excluye el primer día)."""
    previous: str | None = None
    dates: list[date] = []
    for day in sorted(sessions):
        active = select_active_contract(specs, day)
        code = active.code if active else None
        if previous is not None and code != previous:
            dates.append(day)
        previous = code
    return dates
