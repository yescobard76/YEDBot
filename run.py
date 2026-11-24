"""Arranque de YEDTradingBot: API, motor y dashboard en un solo proceso.

    python run.py

Variables opcionales: YED_HOST (127.0.0.1), YED_PORT (8765), YED_OPEN (1),
YED_PROFILE_DIR (data/), YED_CONFIG_PATH y YED_DB_PATH.
"""

from __future__ import annotations

import os
import threading
import webbrowser

import uvicorn


def main() -> None:
    host = os.environ.get("YED_HOST", "127.0.0.1")
    port = int(os.environ.get("YED_PORT", "8765"))
    url = f"http://{host}:{port}"
    if os.environ.get("YED_OPEN", "1") == "1":
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"\n  YEDTradingBot · dashboard en {url}\n  Ctrl+C para detener.\n")
    uvicorn.run("server.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
