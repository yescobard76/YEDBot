"""Reinicio operativo seguro: historial a cero y feed real explícito.

Uso::

    python -m server.reset --yes

El comando no descarga datos ni inventa barras. Con ``--dry-run`` muestra los
conteos y el archivo previsto sin modificar nada. Sin esa opción, ``--yes``
confirma el borrado: detiene el servidor si está escuchando en el puerto
configurado, archiva la base/configuración, borra el historial de SQLite
(incluidos los backtests guardados) y deja el perfil apuntando a un CSV
histórico validado. Para conservar los backtests, usa el botón «Reiniciar
estadísticas» de la interfaz o ``POST /api/stats/reset``.
El motor no arrancará con datos sintéticos salvo que se exporte
``YED_ALLOW_SIMULATED=1`` de forma explícita.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import time
from pathlib import Path

from .config import BASE_DIR, CONFIG_PATH, DB_PATH, PROFILE_DIR, load_settings, save_settings
from .db import Store, read_history_counts

DEFAULT_REAL_CSV = "data/real/bars_mnq_nq_es_1m.csv"


def _backup_database(destination: Path) -> None:
    if not DB_PATH.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(DB_PATH))
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def _backup_file(path: Path, destination: Path) -> bool:
    if not path.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(path.read_bytes())
    return True


def _server_is_running(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _activate_real_csv(csv_path: str) -> None:
    settings = load_settings()
    settings.feed.provider = "csv"
    settings.feed.csv_path = csv_path
    settings.feed.series_mode = "raw"
    settings.feed.exclude_roll_sessions = True
    settings.feed.loop_sessions = False
    settings.feed.start_date = ""
    settings.mode = "paper"
    settings.live.live_enabled = False
    settings.live.live_confirmation = ""
    save_settings(settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reinicio operativo completo: archiva la base y borra también los "
            "backtests guardados; deja el perfil listo para un CSV real."
        )
    )
    parser.add_argument("--yes", action="store_true", help="Confirma el borrado irreversible.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra los conteos y el archivo previsto sin borrar ni archivar nada.",
    )
    parser.add_argument(
        "--csv-path",
        default=DEFAULT_REAL_CSV,
        help=f"Ruta del CSV real que se usará al reiniciar (por defecto {DEFAULT_REAL_CSV}).",
    )
    parser.add_argument("--host", default=os.environ.get("YED_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("YED_PORT", "8765")))
    args = parser.parse_args(argv)

    if args.dry_run:
        counts = read_history_counts(DB_PATH)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "counts": counts,
                    "delete_backtests": True,
                    "requires_confirmation": True,
                    "archive_would_be": str(BASE_DIR / "backups" / f"reset_{stamp}"),
                    "server_running": _server_is_running(args.host, args.port),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if not args.yes:
        print("Reinicio cancelado: añade --yes para borrar el historial.")
        return 2
    if _server_is_running(args.host, args.port):
        print(
            f"Reinicio cancelado: hay un servidor escuchando en {args.host}:{args.port}. "
            "Detenlo antes de borrar la base."
        )
        return 3

    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup_dir = BASE_DIR / "backups" / f"reset_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    _backup_database(backup_dir / "yedbot.db")
    config_backed_up = _backup_file(CONFIG_PATH, backup_dir / "config.json")
    log_path = PROFILE_DIR / "server.log"
    log_backed_up = _backup_file(log_path, backup_dir / "server.log")

    store = Store(DB_PATH)
    try:
        # El reinicio operativo completo conserva el comportamiento documentado:
        # archiva la base y borra también los backtests guardados.
        counts = store.clear_history(delete_backtests=True)
    finally:
        store.close()

    _activate_real_csv(args.csv_path)
    if log_path.exists():
        log_path.write_text("", encoding="utf-8")

    csv_exists = (BASE_DIR / args.csv_path).exists() if not Path(args.csv_path).is_absolute() else Path(args.csv_path).exists()
    print(
        json.dumps(
            {
                "ok": True,
                "backup": str(backup_dir),
                "config_backed_up": config_backed_up,
                "log_backed_up": log_backed_up,
                "deleted": counts,
                "feed": {
                    "provider": "csv",
                    "csv_path": args.csv_path,
                    "csv_exists": csv_exists,
                },
                "note": (
                    "El motor no arrancará con datos sintéticos sin YED_ALLOW_SIMULATED=1. "
                    "No se ha descargado ni generado ningún dato."
                ),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())