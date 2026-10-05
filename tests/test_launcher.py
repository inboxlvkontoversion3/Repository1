from pathlib import Path

import launcher
from launcher import APP_FILE, PROJECT_ROOT, _is_project_streamlit_process


def test_matches_project_streamlit_started_from_project_directory() -> None:
    assert _is_project_streamlit_process(
        ["/venv/bin/streamlit", "run", "app.py"],
        PROJECT_ROOT,
    )


def test_matches_project_streamlit_started_with_absolute_script_path() -> None:
    assert _is_project_streamlit_process(
        ["python", "-m", "streamlit", "run", str(APP_FILE)],
        Path("/tmp"),
    )


def test_does_not_match_an_unrelated_streamlit_app() -> None:
    assert not _is_project_streamlit_process(
        ["streamlit", "run", "other_app.py"],
        PROJECT_ROOT,
    )


def test_does_not_match_another_process_serving_a_file_named_app() -> None:
    assert not _is_project_streamlit_process(
        ["python", "app.py"],
        PROJECT_ROOT,
    )


def test_ctrl_c_returns_interrupt_status_without_propagating(monkeypatch) -> None:
    def interrupt_wait(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(launcher.subprocess, "call", interrupt_wait)

    assert launcher.main() == 130