"""Restart the Autotourenplaner Streamlit app from its project directory."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parent
APP_FILE = PROJECT_ROOT / "app.py"


def _is_project_streamlit_process(command_line: list[str], working_directory: Path) -> bool:
    if "run" not in command_line or not any(
        Path(argument).name == "streamlit" for argument in command_line
    ):
        return False

    for argument in command_line:
        script_path = Path(argument)
        if not script_path.is_absolute():
            script_path = working_directory / script_path
        if script_path.resolve() == APP_FILE:
            return True
    return False


def _find_existing_instances() -> list[int]:
    proc_directory = Path("/proc")
    if not proc_directory.is_dir():
        return []

    process_ids = []
    for process_directory in proc_directory.iterdir():
        if not process_directory.name.isdecimal():
            continue
        try:
            command_line = [
                os.fsdecode(argument)
                for argument in (process_directory / "cmdline").read_bytes().split(b"\0")
                if argument
            ]
            working_directory = (process_directory / "cwd").resolve()
        except (OSError, RuntimeError):
            continue
        if _is_project_streamlit_process(command_line, working_directory):
            process_ids.append(int(process_directory.name))
    return process_ids


def _stop_processes(process_ids: list[int]) -> None:
    for process_id in process_ids:
        try:
            os.kill(process_id, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + 5
    remaining = set(process_ids)
    while remaining and time.monotonic() < deadline:
        for process_id in tuple(remaining):
            try:
                os.kill(process_id, 0)
            except ProcessLookupError:
                remaining.remove(process_id)
        if remaining:
            time.sleep(0.1)

    for process_id in remaining:
        try:
            os.kill(process_id, signal.SIGKILL)
        except ProcessLookupError:
            pass


def main() -> int:
    existing_processes = _find_existing_instances()
    if existing_processes:
        print("Stopping the existing Autotourenplaner instance...", flush=True)
        _stop_processes(existing_processes)

    try:
        return subprocess.call(
            [sys.executable, "-m", "streamlit", "run", str(APP_FILE)],
            cwd=PROJECT_ROOT,
        )
    except KeyboardInterrupt:
        return 128 + signal.SIGINT


if __name__ == "__main__":
    raise SystemExit(main())