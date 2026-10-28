"""Abre la contabilidad local sin exigir una terminal ni iniciar procesos duplicados."""

import argparse
import os
from dotenv import load_dotenv
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parent.parent
LOCAL_CONFIG = ROOT / '.offline/.env'
if LOCAL_CONFIG.exists():
    load_dotenv(LOCAL_CONFIG, override=True)
PORT = int(os.getenv('LOCAL_PORT', '8001'))
URL = f"http://127.0.0.1:{PORT}/ingresar/"
LOG_ROOT = ROOT / '.offline' if LOCAL_CONFIG.exists() else ROOT


def ready():
    try:
        with urlopen(URL, timeout=2) as response:
            page = response.read()
            if b'data-app="mi-contabilidad"' not in page:
                raise RuntimeError("El puerto local está ocupado por otra aplicación.")
            return True
    except URLError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not ready():
        logs = LOG_ROOT / "logs"
        logs.mkdir(exist_ok=True)
        with (logs / "server.log").open("ab") as log:
            process = subprocess.Popen(
                [
                    str(ROOT / ".venv/bin/python"),
                    "manage.py",
                    "runserver",
                    f"127.0.0.1:{PORT}",
                    "--noreload",
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        (logs / "server.pid").write_text(str(process.pid))
        for _ in range(50):
            if ready():
                break
            if process.poll() is not None:
                raise RuntimeError(
                    "No se pudo iniciar Mi Contabilidad. Consulte logs/server.log."
                )
            time.sleep(0.2)
        else:
            raise RuntimeError(
                "Mi Contabilidad tardó demasiado en iniciar. Intente abrirla de nuevo."
            )
    # El worker mantiene su propio bloqueo para no duplicarse al volver a abrir.
    logs = LOG_ROOT / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "sync.log").open("ab") as sync_log:
        subprocess.Popen(
            [str(ROOT / ".venv/bin/python"), "manage.py", "sync_cloud", "--watch"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=sync_log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
    if not args.no_browser:
        subprocess.run(["open", URL], check=True)
    print("Mi Contabilidad está lista: " + URL)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
