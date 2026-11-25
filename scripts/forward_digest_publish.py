r"""Publica un digest del forward fuera de la máquina con scp y verifica su hash.

El transporte usa un alias SSH ya configurado **fuera del repositorio**
(``%USERPROFILE%\.ssh\config`` en Windows). No lee claves, no pide contraseña
y no escribe credenciales en el proyecto. El remoto debe ser POSIX y disponer
de ``sha256sum``, ``mkdir``, ``mv`` y ``rm``.

El archivo se sube primero a un temporal remoto, se compara su SHA-256 con el
local, se promueve con ``mv`` y se vuelve a comparar. Si el destino ya existe
con otro contenido, aborta sin sobrescribirlo. El resultado se guarda en un
recibo ``transport-YYYY-MM-DD.json`` junto a los digests.

No abre SQLite, no arranca el bot y no toca el 8765.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from forward_digest import (  # noqa: E402
    DEFAULT_AUDIT_DIR,
    atomic_write,
    out_dir_external,
    sha256_file,
    verify_chain,
)

HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
REMOTE_DIR_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")
DIGEST_RE = re.compile(r"^digest-\d{4}-\d{2}-\d{2}\.json$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes")

Runner = Callable[..., subprocess.CompletedProcess[str]]


class PublishError(RuntimeError):
    """Error de transporte o de verificación remota."""


def now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def validate_host(raw: str) -> str:
    host = raw.strip()
    if not HOST_RE.fullmatch(host):
        raise PublishError(
            "ssh-host inválido: usa un alias de ~/.ssh/config "
            "(letras, números, punto, guion o guion bajo)"
        )
    return host


def validate_remote_dir(raw: str) -> str:
    value = raw.strip()
    if not REMOTE_DIR_RE.fullmatch(value):
        raise PublishError(
            "remote-dir inválido: debe ser una ruta POSIX absoluta, "
            "sin espacios ni caracteres especiales"
        )
    value = value.rstrip("/")
    if not value or value == "/":
        raise PublishError("remote-dir no puede ser la raíz remota")
    segments = value.split("/")[1:]
    if any(segment in ("", ".", "..") for segment in segments):
        raise PublishError("remote-dir no puede contener segmentos vacíos, '.' o '..'")
    return value


def select_digest(out_dir: Path, name: str) -> Path:
    if name:
        if not DIGEST_RE.fullmatch(name):
            raise PublishError("file inválido: se espera digest-YYYY-MM-DD.json")
        path = (out_dir / name).resolve()
        if path.parent != out_dir.resolve():
            raise PublishError("file debe estar dentro de out-dir")
    else:
        candidates = sorted(out_dir.glob("digest-*.json"))
        if not candidates:
            raise PublishError(f"no hay digests en {out_dir}")
        path = candidates[-1].resolve()
        if path.parent != out_dir.resolve():
            raise PublishError(f"digest fuera de out-dir: {path}")
    if not path.is_file():
        raise PublishError(f"no existe el digest: {path}")
    return path


def verify_local_chain(out_dir: Path) -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = verify_chain(out_dir)
    if code != 0:
        detail = stderr.getvalue().strip() or stdout.getvalue().strip()
        raise PublishError(f"cadena de digests inválida: {detail or 'verify_chain falló'}")


def default_runner(
    command: Sequence[str], cwd: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def run_checked(
    command: Sequence[str],
    runner: Runner,
    *,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = runner(list(command), cwd=cwd)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise PublishError(
            f"comando de transporte falló ({Path(command[0]).name}, "
            f"código {result.returncode}): {detail[:500]}"
        )
    return result


def resolve_tool(raw: str, name: str) -> str:
    if raw:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise PublishError(f"no existe {name}: {path}")
        return str(path)
    found = shutil.which(name)
    if not found:
        raise PublishError(
            f"no se encontró {name} en PATH; instala OpenSSH o pasa el ejecutable"
        )
    return found


def ssh_command(ssh: str, host: str, remote_script: str) -> list[str]:
    return [ssh, *SSH_OPTIONS, host, remote_script]


def remote_hash(
    ssh: str, host: str, remote_path: str, runner: Runner
) -> str | None:
    quoted = shlex.quote(remote_path)
    script = (
        f"if [ -f {quoted} ]; then "
        f"sha256sum -- {quoted}; "
        f"else printf 'MISSING\\n'; fi"
    )
    result = run_checked(ssh_command(ssh, host, script), runner)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if lines == ["MISSING"]:
        return None
    if len(lines) != 1:
        raise PublishError(
            f"respuesta remota inesperada al hashear {remote_path}: {lines!r}"
        )
    fields = lines[0].split()
    value = fields[0].lower() if fields else ""
    if not SHA_RE.fullmatch(value):
        raise PublishError(
            f"el remoto no devolvió SHA-256 válido para {remote_path}: {lines[0]!r}"
        )
    return value


def remote_mkdir(ssh: str, host: str, remote_dir: str, runner: Runner) -> None:
    run_checked(
        ssh_command(ssh, host, f"mkdir -p -- {shlex.quote(remote_dir)}"),
        runner,
    )


def remote_move(
    ssh: str, host: str, source: str, destination: str, runner: Runner
) -> None:
    run_checked(
        ssh_command(
            ssh,
            host,
            f"mv -- {shlex.quote(source)} {shlex.quote(destination)}",
        ),
        runner,
    )


def remote_remove(ssh: str, host: str, path: str, runner: Runner) -> None:
    try:
        runner(ssh_command(ssh, host, f"rm -f -- {shlex.quote(path)}"))
    except Exception:  # noqa: BLE001
        pass


def scp_upload(
    scp: str,
    host: str,
    source_name: str,
    remote_path: str,
    source_dir: Path,
    runner: Runner,
) -> None:
    # El nombre relativo evita que scp interprete ``C:`` como un host.
    command = [scp, "-q", *SSH_OPTIONS, source_name, f"{host}:{remote_path}"]
    run_checked(command, runner, cwd=str(source_dir))


def publish_digest(
    digest_path: Path,
    host: str,
    remote_dir: str,
    *,
    ssh: str,
    scp: str,
    verify_only: bool,
    runner: Runner = default_runner,
) -> dict[str, Any]:
    local_sha = sha256_file(digest_path)
    remote_path = f"{remote_dir}/{digest_path.name}"
    remote_sha = remote_hash(ssh, host, remote_path, runner)

    if remote_sha == local_sha:
        action = "already-present"
    elif remote_sha is not None:
        raise PublishError(
            "REMOTE_CONFLICT: el archivo remoto ya existe con otro SHA-256; "
            f"no se sobrescribe: {remote_path}"
        )
    elif verify_only:
        raise PublishError(
            f"REMOTE_MISSING: no existe el archivo remoto: {remote_path}"
        )
    else:
        remote_mkdir(ssh, host, remote_dir, runner)
        temp_path = f"{remote_dir}/.{digest_path.name}.part-{uuid.uuid4().hex}"
        moved = False
        try:
            scp_upload(scp, host, digest_path.name, temp_path, digest_path.parent, runner)
            temp_sha = remote_hash(ssh, host, temp_path, runner)
            if temp_sha != local_sha:
                raise PublishError(
                    "el SHA-256 del temporal remoto no coincide con el local"
                )
            existing = remote_hash(ssh, host, remote_path, runner)
            if existing is not None and existing != local_sha:
                raise PublishError(
                    "REMOTE_CONFLICT: el archivo remoto apareció con otro SHA-256 "
                    f"durante la subida; no se sobrescribe: {remote_path}"
                )
            if existing is None:
                remote_move(ssh, host, temp_path, remote_path, runner)
                moved = True
            action = "uploaded" if moved else "already-present"
            final_sha = remote_hash(ssh, host, remote_path, runner)
            if final_sha != local_sha:
                raise PublishError(
                    "el SHA-256 remoto final no coincide con el local"
                )
            remote_sha = final_sha
        finally:
            if not moved:
                remote_remove(ssh, host, temp_path, runner)

    return {
        "ok": True,
        "transport": "scp",
        "ssh_host": host,
        "remote_dir": remote_dir,
        "remote_path": remote_path,
        "local_path": str(digest_path),
        "local_sha256": local_sha,
        "remote_sha256": remote_sha,
        "matches": remote_sha == local_sha,
        "action": action,
        "verified_at": now_utc(),
    }


def receipt_path(out_dir: Path, digest_path: Path) -> Path:
    day = digest_path.stem.removeprefix("digest-")
    return out_dir / f"transport-{day}.json"


def write_receipt(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    atomic_write(target, data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", required=True, help="Alias de ~/.ssh/config")
    parser.add_argument(
        "--remote-dir",
        required=True,
        help="Directorio POSIX absoluto, por ejemplo /srv/yedbot-audit/forward-digests",
    )
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_AUDIT_DIR / "forward-digests"),
        help="Directorio externo donde están los digests.",
    )
    parser.add_argument("--file", default="", help="Digest concreto; por defecto el último.")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="No sube ni crea nada; solo compara el remoto con el local.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida y calcula hashes locales sin contactar con el remoto.",
    )
    parser.add_argument(
        "--receipt",
        default="",
        help="Recibo JSON; por defecto out-dir/transport-YYYY-MM-DD.json",
    )
    parser.add_argument("--ssh", default="", help="Ruta explícita a ssh (opcional).")
    parser.add_argument("--scp", default="", help="Ruta explícita a scp (opcional).")
    args = parser.parse_args(argv)

    out_dir: Path | None = None
    digest_path: Path | None = None
    payload: dict[str, Any] = {
        "ok": False,
        "transport": "scp",
        "ssh_host": args.ssh_host,
        "remote_dir": args.remote_dir,
    }
    try:
        host = validate_host(args.ssh_host)
        remote_dir = validate_remote_dir(args.remote_dir)
        out_dir = out_dir_external(args.out_dir)
        digest_path = select_digest(out_dir, args.file)
        verify_local_chain(out_dir)
        payload.update(
            {
                "remote_path": f"{remote_dir}/{digest_path.name}",
                "local_path": str(digest_path),
                "local_sha256": sha256_file(digest_path),
            }
        )

        if args.dry_run:
            payload.update(
                {
                    "ok": True,
                    "remote_sha256": None,
                    "matches": None,
                    "action": "dry-run",
                    "verified_at": now_utc(),
                }
            )
        else:
            ssh = resolve_tool(args.ssh, "ssh")
            scp = resolve_tool(args.scp, "scp")
            payload.update(
                publish_digest(
                    digest_path,
                    host,
                    remote_dir,
                    ssh=ssh,
                    scp=scp,
                    verify_only=args.verify_only,
                )
            )

        receipt = (
            Path(args.receipt).expanduser().resolve()
            if args.receipt
            else receipt_path(out_dir, digest_path)
        )
        payload["receipt"] = str(receipt)
        write_receipt(receipt, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except (PublishError, SystemExit) as exc:
        message = str(exc) or "fallo de transporte"
        payload["error"] = message
        if out_dir is not None and digest_path is not None:
            try:
                receipt = receipt_path(out_dir, digest_path)
                payload["receipt"] = str(receipt)
                write_receipt(receipt, payload)
            except Exception:  # noqa: BLE001
                pass
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        payload["error"] = str(exc)
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
