r"""Puerta pública con contraseña para el dashboard de YEDBot.

Escucha solo en 127.0.0.1:8790, exige Basic auth y reenvía HTTP y WebSocket a
http://127.0.0.1:8765. Se publica con un túnel (cloudflared); nunca debe
escuchar en 0.0.0.0.

Credenciales: .git/public-gateway.json (fuera de control de versiones), con
{"user": "...", "password": "..."}. Sin ese archivo la puerta no arranca.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask
from websockets.asyncio.client import connect as ws_connect

UPSTREAM_HTTP = "http://127.0.0.1:8765"
UPSTREAM_WS = "ws://127.0.0.1:8765/api/ws"
CREDENTIALS = Path(".git") / "public-gateway.json"
HOST = "127.0.0.1"
PORT = int(os.environ.get("YED_PUBLIC_PORT", "8791"))

# Cabeceras de salto de proxy: no se reenvían en ninguna dirección.
HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "authorization",
}


def load_credentials() -> tuple[bytes, bytes]:
    try:
        data = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    except OSError:
        raise SystemExit(f"faltan credenciales en {CREDENTIALS}")
    user = str(data.get("user", ""))
    password = str(data.get("password", ""))
    if not user or not password:
        raise SystemExit(f"credenciales incompletas en {CREDENTIALS}")
    return user.encode(), password.encode()


EXPECTED = b"Basic " + base64.b64encode(b":".join(load_credentials()))


def _authorized(header: str | None) -> bool:
    if not header:
        return False
    return hmac.compare_digest(header.encode(), EXPECTED)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(follow_redirects=False, timeout=None)
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(
    title="YEDBot public gateway",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)


@app.middleware("http")
async def _require_auth(request: Request, call_next):
    if not _authorized(request.headers.get("authorization")):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="YEDBot", charset="UTF-8"'},
            content=b"autenticacion requerida\n",
        )
    return await call_next(request)


@app.websocket("/api/ws")
async def _ws_proxy(websocket: WebSocket) -> None:
    if not _authorized(websocket.headers.get("authorization")):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        async with ws_connect(UPSTREAM_WS, ping_interval=20, ping_timeout=20) as upstream:

            async def to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            async def to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            tasks = [
                asyncio.create_task(to_client()),
                asyncio.create_task(to_upstream()),
            ]
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.exception()
    except Exception:  # noqa: BLE001 - el cliente ve el cierre, el túnel no cae
        pass
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


@app.api_route(
    "/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def _proxy(path: str, request: Request) -> StreamingResponse:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP
    }
    body = await request.body()
    upstream_request = app.state.client.build_request(
        request.method,
        f"{UPSTREAM_HTTP}/{path}",
        params=request.query_params,
        headers=headers,
        content=body,
    )
    upstream_response = await app.state.client.send(upstream_request, stream=True)
    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in HOP
    }
    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        background=BackgroundTask(upstream_response.aclose),
    )


def main() -> None:
    print(f"puerta publica en http://{HOST}:{PORT} -> {UPSTREAM_HTTP}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info", access_log=True)


if __name__ == "__main__":
    main()
