"""Lanzador del descargador real que no depende del directorio actual.

Uso::

    python fetch_data.py --activate

Es equivalente a ``python -m server.market.massive_fetch``, pero añade la
raíz del proyecto a ``sys.path``. Así funciona aunque PowerShell se haya
abierto en otra carpeta o ``PYTHONSAFEPATH`` esté activo.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.market.massive_fetch import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())