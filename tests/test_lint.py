import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_lint_passes_on_seed():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "grounding_lint.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
