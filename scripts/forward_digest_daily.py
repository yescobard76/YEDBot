r"""Genera el digest diario y lo publica fuera de la máquina por scp.

No guarda credenciales: usa un alias SSH configurado en ``%USERPROFILE%\.ssh``
o ``~/.ssh``, fuera del repositorio. Primero ejecuta ``forward_digest.py`` y
solo publica si la generación termina correctamente.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
PROJECT = SCRIPTS.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from forward_digest import DEFAULT_AUDIT_DIR  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", default="")
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_AUDIT_DIR / "forward-digests"),
    )
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--remote-dir", required=True)
    parser.add_argument("--date", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--receipt", default="")
    args = parser.parse_args(argv)

    if not args.verify_only and not args.window_id:
        parser.error("--window-id es obligatorio salvo con --verify-only")

    if not args.verify_only:
        command = [
            sys.executable,
            str(SCRIPTS / "forward_digest.py"),
            "--window-id",
            args.window_id,
            "--out-dir",
            args.out_dir,
        ]
        if args.date:
            command.extend(["--date", args.date])
        if args.force:
            command.append("--force")
        code = subprocess.call(command, cwd=str(PROJECT))
        if code != 0:
            print(
                f"FORWARD_DIGEST_FAIL: generación terminó con código {code}",
                file=sys.stderr,
            )
            return code

    from forward_digest_publish import main as publish_main

    publish_args = [
        "--ssh-host",
        args.ssh_host,
        "--remote-dir",
        args.remote_dir,
        "--out-dir",
        args.out_dir,
    ]
    if args.verify_only:
        publish_args.append("--verify-only")
    if args.dry_run:
        publish_args.append("--dry-run")
    if args.receipt:
        publish_args.extend(["--receipt", args.receipt])
    return publish_main(publish_args)


if __name__ == "__main__":
    raise SystemExit(main())
