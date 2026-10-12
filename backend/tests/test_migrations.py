"""
Tests — Alembic migrations stay in sync with the ORM models
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(*args: str, db_url: str) -> subprocess.CompletedProcess[str]:
    # The subprocess doesn't inherit pytest's pythonpath; point it at src explicitly
    pythonpath = os.pathsep.join(filter(None, [str(BACKEND / "src"), os.environ.get("PYTHONPATH")]))
    env = {**os.environ, "DATABASE_URL": db_url, "PYTHONPATH": pythonpath}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, check=False,
    )


def test_migrations_upgrade_downgrade_and_match_models(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'mig.db'}"
    for args in (("upgrade", "head"), ("downgrade", "base"), ("upgrade", "head")):
        result = _alembic(*args, db_url=url)
        assert result.returncode == 0, result.stderr
    check = _alembic("check", db_url=url)
    assert check.returncode == 0, check.stdout + check.stderr
