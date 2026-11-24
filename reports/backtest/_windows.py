"""Única definición de las ventanas canónicas de desarrollo W1-W6.

Las fechas de cierre, el número de sesiones y la primera sesión real de cada
bloque viven aquí. Los runners de ``reports/backtest`` importan este módulo;
no deben volver a declarar estas tuplas.

W5 empieza a nivel de trimestre el 2026-01-01, pero la primera sesión real es
el 2026-01-02 (el 1 de enero no hay sesión en el dataset).
"""

from __future__ import annotations

from datetime import date

# (bloque, inicio solicitado, fin, sesiones evaluadas)
WINDOWS: tuple[tuple[str, str, str, int], ...] = (
    ("W1", "2025-01-10", "2025-03-31", 54),
    ("W2", "2025-04-01", "2025-06-30", 61),
    ("W3", "2025-07-01", "2025-09-30", 63),
    ("W4", "2025-10-01", "2025-12-31", 63),
    ("W5", "2026-01-01", "2026-03-31", 60),
    ("W6", "2026-04-01", "2026-06-30", 61),
)

# Primera sesión realmente cargada por ventana. W5 abre el 2026-01-02.
WINDOW_FIRST: dict[str, str] = {
    "W1": "2025-01-10",
    "W2": "2025-04-01",
    "W3": "2025-07-01",
    "W4": "2025-10-01",
    "W5": "2026-01-02",
    "W6": "2026-04-01",
}

WINDOW_IDS: tuple[str, ...] = tuple(spec[0] for spec in WINDOWS)


def window_date_ranges() -> tuple[tuple[str, date, date], ...]:
    """Devuelve las ventanas con objetos ``date`` para los reportes de equity."""
    return tuple(
        (key, date.fromisoformat(start), date.fromisoformat(end))
        for key, start, end, _days in WINDOWS
    )
