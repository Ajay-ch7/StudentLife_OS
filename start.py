from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent


def get_python_command() -> str:
    for relative_path in (
        Path(".venv") / "Scripts" / "python.exe",
        Path("venv") / "Scripts" / "python.exe",
        Path(".venv") / "bin" / "python",
        Path("venv") / "bin" / "python",
    ):
        python_path = ROOT_DIR / relative_path
        if python_path.exists():
            return str(python_path)
    return sys.executable


def main() -> int:
    npm_command = shutil.which("npm.cmd") or shutil.which("npm")
    if npm_command is None:
        print("npm was not found. Install Node.js 18+ and run this command again.")
        return 1

    environment = os.environ.copy()
    backend_path = str(ROOT_DIR / "backend")
    root_path = str(ROOT_DIR)
    environment["PYTHONPATH"] = os.pathsep.join(
        [backend_path, root_path, environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    python_command = get_python_command()

    backend_process = subprocess.Popen(
        [
            python_command,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            backend_path,
            "--reload",
            "--reload-dir",
            backend_path,
            "--reload-dir",
            str(ROOT_DIR / "openclaw"),
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ],
        cwd=ROOT_DIR,
        env=environment,
    )

    frontend_process = subprocess.Popen(
        [npm_command, "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"],
        cwd=ROOT_DIR / "frontend",
        env=environment,
    )
    processes = [backend_process, frontend_process]

    def stop_processes(*_: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGINT, stop_processes)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_processes)

    try:
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
    except KeyboardInterrupt:
        stop_processes()
    finally:
        stop_processes()
        for process in processes:
            process.wait()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())