"""COIN MEMORY tests (run in an isolated subprocess so the heavy real-app
import cannot pollute other test modules).

Guarantee under test: coins selected by the user survive refreshes, engine
respawns and redeploys until the user himself selects different coins.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve().parent / "_coin_memory_runner.py"


def test_coin_memory_scenarios():
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        cwd=str(REPO), capture_output=True, text=True, timeout=180,
    )
    line = next((l for l in proc.stdout.splitlines() if l.startswith("COINMEM_JSON:")), None)
    assert line is not None, (
        f"runner produced no verdict\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}")
    verdict = json.loads(line[len("COINMEM_JSON:"):])
    for name, res in verdict["results"].items():
        assert res == "PASS", f"{name}: {res}"
    assert verdict["all_pass"] is True
