"""Verify the DevForge decision loops in-process (no HTTP needed).

Covers:
1. Gate rejection loop — rejecting a gate re-runs the same agent with the
   reviewer's feedback (iteration counter + visible feedback incorporation).
2. D4 (tests) self-heal loop — failing pytest runs route back to the Coding
   Agent automatically (no human gate) until tests pass or the bound is hit.
3. D5 (security) fix loop — HIGH findings route back to the Coding Agent and
   the scan is re-run until clean.

Usage (backend venv):  python scripts/test_loops.py
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import Project, TestResult  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.execution import runner as runner_mod  # noqa: E402
from app.orchestrator.workflow_engine import get_engine  # noqa: E402
from app.utils.files import workspace_root  # noqa: E402

_REAL_PYTEST = runner_mod.run_pytest
_REAL_SCAN = runner_mod.run_security_scan


async def drive(name: str, task: str, decisions, timeout: float = 180.0):
    """Create a project, start the engine, respond to gates, await terminal state."""
    pid = uuid.uuid4().hex
    workspace_root(pid).mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        db.add(Project(id=pid, name=name, task=task))
        db.commit()
    eng = get_engine(pid)
    await eng.start()
    seen: set[tuple] = set()
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.3)
        gate = eng.state.awaiting_gate
        if gate:
            key = (gate, tuple(sorted(eng.state.iterations.items())))
            if key not in seen:
                seen.add(key)
                decision = decisions(gate)
                if decision:
                    eng.submit_approval(gate, *decision)
        if eng.state.stage in ("completed", "failed"):
            break
    # let the engine task finish its final emits before the loop closes
    if eng._task is not None and not eng._task.done():
        try:
            await asyncio.wait_for(eng._task, timeout=5)
        except asyncio.TimeoutError:
            pass
    return eng


def test_rejection_loop() -> None:
    calls = {"rejected_once": False}

    def decisions(gate: str):
        if gate == "requirement" and not calls["rejected_once"]:
            calls["rejected_once"] = True
            return ("changes_requested", "Focus only on the CLI; drop the API table.")
        return ("approved", "ok")

    eng = asyncio.run(drive("RejectLoop", "Build a small demo service.", decisions))
    assert eng.state.stage == "completed", f"expected completed, got {eng.state.stage}: {eng.state.error}"
    assert eng.state.iterations.get("requirement") == 1, eng.state.iterations
    assert any("drop the API table" in fr for fr in eng.state.requirement.functional_requirements), (
        "reviewer feedback was not incorporated into the re-run SRS"
    )
    print("PASS 1/3  gate rejection re-runs RA with feedback (iteration=1, FR-07 present)")


def test_self_heal_loop() -> None:
    calls = {"n": 0}

    def patched(workspace: Path, timeout: float = 180):
        calls["n"] += 1
        r = _REAL_PYTEST(workspace, timeout)
        if calls["n"] <= 2:
            return {
                **r,
                "passed": False,
                "failed_count": max(r["passed_count"], 1),
                "exit_code": 1,
                "summary": "1 failed (injected)",
                "failures": ["FAILED tests/test_core.py::test_injected (AssertionError)"],
                "output": r["output"] + "\n[loop-test] injected failure",
            }
        return r

    runner_mod.run_pytest = patched
    try:
        eng = asyncio.run(drive("HealLoop", "Build a small demo service.", lambda g: ("approved", "ok")))
    finally:
        runner_mod.run_pytest = _REAL_PYTEST
    assert eng.state.stage == "completed", f"expected completed, got {eng.state.stage}: {eng.state.error}"
    assert calls["n"] == 3, f"expected 3 pytest runs, got {calls['n']}"
    assert eng.state.iterations.get("test_heals") == 2, eng.state.iterations
    with SessionLocal() as db:
        runs = db.query(TestResult).filter(TestResult.project_id == eng.project_id).count()
    assert runs == 3, f"expected 3 TestResult rows, got {runs}"
    print("PASS 2/3  D4 self-heal loop: 2 injected failures → CA heal x2 → green on run 3 (3 TestResult rows)")


def test_security_fix_loop() -> None:
    calls = {"n": 0}

    def patched(workspace: Path, timeout: float = 120):
        calls["n"] += 1
        r = _REAL_SCAN(workspace, timeout)
        if calls["n"] == 1:
            return {
                **r,
                "clean": False,
                "findings": [
                    *r["findings"],
                    {
                        "severity": "HIGH",
                        "category": "hardcoded-secret",
                        "message": "possible hardcoded secret assigned to 'api_key' (injected)",
                        "file": "src/core.py",
                        "line": 42,
                    },
                ],
            }
        return r

    runner_mod.run_security_scan = patched
    try:
        eng = asyncio.run(drive("SecLoop", "Build a small demo service.", lambda g: ("approved", "ok")))
    finally:
        runner_mod.run_security_scan = _REAL_SCAN
    assert eng.state.stage == "completed", f"expected completed, got {eng.state.stage}: {eng.state.error}"
    assert calls["n"] == 2, f"expected 2 scans, got {calls['n']}"
    assert eng.state.iterations.get("security_fixes") == 1, eng.state.iterations
    print("PASS 3/3  D5 security fix loop: 1 HIGH finding → CA security fix → re-scan clean")


def main() -> int:
    init_db()
    test_rejection_loop()
    test_self_heal_loop()
    test_security_fix_loop()
    print("\nALL LOOP TESTS PASSED ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
