"""Aplicación HTTP de un brazo forward.

No monta el dashboard de control y bloquea cualquier método mutante salvo
`POST /api/forward/stop`. Cada intento bloqueado queda en el ledger del brazo
como `VIOLATION`, lo que marca la ventana como NO_VÁLIDA.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import uvicorn

from .identity import file_sha256
from .ledger import Ledger, derive_status, read_records, verify_chain
from .paths import arm_dir, heartbeat_path, profile_dir

ALLOWED_MUTATION = "/api/forward/stop"


def _session_summary(window_id: str, arm: str) -> dict[str, Any]:
    folder = arm_dir(window_id, arm) / "sessions"
    entries = sorted(folder.glob("*.json")) if folder.exists() else []
    valid = 0
    last = None
    for path in entries:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if value.get("valid"):
            valid += 1
        last = value
    return {
        "sealed": len(entries),
        "valid": valid,
        "last_session": (last or {}).get("session"),
        "last_valid": (last or {}).get("valid"),
    }


def build_app(
    *,
    window_id: str,
    arm: str,
    port: int,
    settings: Any,
    snapshot: dict[str, Any],
    ledger: Ledger,
):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from server.api import router
    from server.db import Store
    from server.engine import TradingEngine

    store = Store()
    engine = TradingEngine(store, settings)

    async def supervisor_watchdog(app: FastAPI) -> None:
        """Si el supervisor desaparece, el brazo se detiene solo.

        Evita procesos huérfanos que seguirían escribiendo en el ledger si el
        supervisor muere de forma no capturable (TerminateProcess en Windows).
        """
        heartbeat = heartbeat_path(window_id, arm)
        while True:
            await asyncio.sleep(5)
            try:
                age = time.time() - heartbeat.stat().st_mtime
            except OSError:
                age = 10**6
            if age > 30:
                ledger.append(
                    "SUPERVISOR_LOST",
                    {"heartbeat_age_seconds": round(age, 1), "arm_pid": os.getpid()},
                )
                server = getattr(app.state, "uvicorn_server", None)
                if server is not None:
                    server.should_exit = True
                return

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watchdog = None
        if os.environ.get("YED_FORWARD_SUPERVISED") == "1":
            watchdog = asyncio.create_task(supervisor_watchdog(app))
        ledger.append(
            "ARM_LISTENING",
            {
                "port": port,
                "engine_status": engine.status,
                "feed_error": engine.feed_error,
                "db_path": str(store.path),
                "config_path": str(profile_dir(window_id, arm) / "config.json"),
            },
        )
        try:
            yield
        finally:
            if watchdog is not None:
                watchdog.cancel()
            await engine.stop()
            store.close()

    app = FastAPI(
        title=f"YED forward {window_id}/{arm}",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.engine = engine
    app.state.store = store
    app.state.window_id = window_id
    app.state.arm = arm
    app.state.forward_ledger = ledger
    app.state.snapshot = snapshot

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        if request.method == "POST" and path == ALLOWED_MUTATION:
            return await call_next(request)
        detail = {
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "client": request.client.host if request.client else None,
        }
        ledger.append("VIOLATION", detail)
        return JSONResponse(
            status_code=403,
            content={
                "detail": "ruta mutante bloqueada en modo forward de solo lectura",
                "allowed": ALLOWED_MUTATION,
                "window_status": derive_status(read_records(ledger.path)),
                "logged": True,
            },
        )

    @app.get("/api/forward/state")
    def forward_state() -> dict[str, Any]:
        records = read_records(ledger.path)
        return {
            "window_id": window_id,
            "arm": arm,
            "status": derive_status(records),
            "chain_ok": not verify_chain(records),
            "ledger_head": records[-1]["sha256"] if records else None,
            "events": len(records),
            "config_file_sha256": file_sha256(
                profile_dir(window_id, arm) / "config.json"
            ),
            "code_sha256": snapshot.get("code_sha256"),
            "engine_status": engine.status,
            "feed_error": engine.feed_error,
            "db_path": str(store.path),
            "sessions": _session_summary(window_id, arm),
        }

    @app.post("/api/forward/stop")
    def forward_stop() -> dict[str, Any]:
        ledger.append(
            "STOPPED",
            {
                "reason": "parada solicitada",
                "by": "http",
                "engine_status": engine.status,
                "window_labeled": True,
            },
        )
        server = getattr(app.state, "uvicorn_server", None)
        if server is not None:
            server.should_exit = True
        return {
            "ok": True,
            "stopped": True,
            "window_status": derive_status(read_records(ledger.path)),
        }

    app.include_router(router, prefix="/api")
    return app


def serve(
    *,
    window_id: str,
    arm: str,
    port: int,
    settings: Any,
    snapshot: dict[str, Any],
    ledger: Ledger,
) -> None:
    app = build_app(
        window_id=window_id,
        arm=arm,
        port=port,
        settings=settings,
        snapshot=snapshot,
        ledger=ledger,
    )
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server
    server.run()
