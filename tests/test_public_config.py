import os
import subprocess
import sys
from pathlib import Path


def test_web_server_requires_explicit_admin_password():
    env = os.environ.copy()
    env.pop('ADMIN_PASSWORD', None)
    result = subprocess.run(
        [sys.executable, '-c', 'import web_ui'],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert 'Set ADMIN_PASSWORD before starting' in result.stderr
