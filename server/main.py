"""Aplicación FastAPI: API + WebSocket + frontend compilado."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import router
from .config import BASE_DIR, load_settings
from .db import Store
from .engine import TradingEngine

DIST = BASE_DIR / "frontend" / "dist"


def create_app() -> FastAPI:
    settings = load_settings()
    store = Store()
    engine = TradingEngine(store, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # El motor no arranca solo: el operador debe revisar el feed y pulsar Iniciar.
        engine._emit("INFO", "system", "Motor listo; inicio manual requerido")
        try:
            yield
        finally:
            await engine.stop()
            store.close()

    app = FastAPI(title="YEDTradingBot", version=__version__, lifespan=lifespan)
    app.state.engine = engine
    app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    if DIST.exists():
        app.mount("/", StaticFiles(directory=str(DIST), html=True), name="dashboard")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def build_missing() -> str:
            return (
                "<body style='background:#080b10;color:#e6ebf2;font-family:system-ui;padding:40px'>"
                "<h1>YEDTradingBot</h1><p>El frontend no está compilado.</p>"
                "<pre style='color:#3ddc97'>cd frontend\nnpm install\nnpm run build</pre>"
                "<p>La API está disponible en <a style='color:#4c9ffe' href='/api/status'>/api/status</a>.</p>"
                "</body>"
            )

    return app


app = create_app()
