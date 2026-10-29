"""Setup is repeatable and reports local health without credentials or a cloud service."""

import json
import os
import subprocess
import sys


def test_sqlite_setup_is_idempotent_and_doctor_reports_persistence(tmp_path):
    env = {**os.environ, "OPENPOKE_MODE": "offline", "OPENPOKE_DATA_DIR": str(tmp_path)}
    command = [sys.executable, "-m", "task_router.cli"]
    first = json.loads(subprocess.check_output([*command, "setup", "--size", "12"], env=env, text=True))
    second = json.loads(subprocess.check_output([*command, "setup", "--size", "12"], env=env, text=True))
    doctor = json.loads(subprocess.check_output([*command, "doctor"], env=env, text=True))
    assert first["indexed"] == 0 and second["indexed"] == 0
    assert doctor["sqlite_integrity"] == [{"integrity_check": "ok"}]
    assert not doctor["foreign_key_errors"] and doctor["pending_index_updates"] == 12
    assert doctor["vectors"] == 0 and not doctor["live_calls_enabled"]

    assert not (tmp_path / "chroma").exists()
