"""Test runner: executes the generated project's test suite inside the sandbox.

The runner is framework aware but conservative — it currently supports pytest
(Python) and vitest/npm test (Node) when a ``package.json`` test script exists,
and it parses pytest's verbose output into structured per-test results so the
Testing Agent can feed precise failures back to the Developer Agent:

* ``--json-report`` is used when ``pytest-json-report`` is installed;
* otherwise the verbose text output is parsed (tolerant to formatting changes).

Every execution goes through the :class:`SandboxExecutor` abstraction, so no
AI-generated test ever runs unguarded on the host.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import ExecutionError
from app.core.logging import get_logger
from app.tools.executor.base import ExecutionResult
from app.tools.executor.factory import get_executor

logger = get_logger("devforge.test_runner")

SUMMARY_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<kind>passed|failed|error|errors|skipped|xfailed|xpassed|warning|warnings)"
)
RESULT_LINE_RE = re.compile(
    r"^(?P<file>[^\s:]+\.(?:py|js|ts|tsx|jsx))::(?P<name>[^\s]+)\s+"
    r"(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)",
    re.MULTILINE,
)
DURATION_RE = re.compile(r"in\s+(?P<seconds>\d+\.\d+)s")
FAIL_SHORT_RE = re.compile(
    r"^_{5,}\s*(?P<name>.+?)\s*_{5,}$\s*(?P<body>.*?)(?=^_{5,}|\Z)", re.MULTILINE | re.DOTALL
)


@dataclass
class ParsedTestResult:
    name: str
    file_path: str = ""
    status: str = "ERROR"  # PASSED | FAILED | ERROR | SKIPPED
    duration_ms: int = 0
    message: str = ""


@dataclass
class ParsedTestRun:
    status: str = "ERROR"  # PASSED | FAILED | ERROR
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: int = 0
    results: list[ParsedTestResult] = field(default_factory=list)
    raw_output: str = ""
    command: str = ""
    provider: str = ""
    parser: str = "text"
    exit_code: int = -1
    timed_out: bool = False
    notes: list[str] = field(default_factory=list)
    layout: dict = field(default_factory=dict)


class TestRunner:
    """Discovers and executes a project's tests in the sandbox."""

    def __init__(self, *, executor=None) -> None:  # noqa: ANN001
        self.executor = executor or get_executor()

    # --------------------------------------------------------------- discovery
    @staticmethod
    def discover(project_dir: Path) -> dict:
        """Locate runnable tests and work out where pytest should be invoked.

        Supports the common layouts:
          <project>/tests/test_*.py                    -> cwd=<project>, target=tests
          <project>/backend/tests/test_*.py            -> cwd=<project>/backend, target=tests
          <project>/**/test_*.py                       -> cwd=nearest package root
        """
        ignored = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
                   ".pytest_cache", "site-packages"}
        info: dict = {"pytest": False, "node": False, "test_dir": "", "test_files": [],
                      "frameworks": [], "cwd": ".", "targets": []}
        project_dir = Path(project_dir)

        candidates: list[Path] = []
        for path in sorted(project_dir.rglob("test_*.py")):
            if any(part in ignored for part in path.parts):
                continue
            candidates.append(path)
        for path in sorted(project_dir.rglob("*_test.py")):
            if any(part in ignored for part in path.parts):
                continue
            candidates.append(path)

        groups: dict[Path, list[Path]] = {}
        for path in candidates:
            parent = path.parent
            run_root = parent.parent if parent.name == "tests" else parent
            groups.setdefault(run_root, []).append(path)

        if groups:
            run_root = sorted(groups, key=lambda p: (-len(groups[p]), len(str(p))))[0]
            info["pytest"] = True
            info["frameworks"].append("pytest")
            info["test_files"] = [str(p.relative_to(project_dir)) for p in groups[run_root]][:50]
            info["cwd"] = str(run_root.relative_to(project_dir)) or "."
            test_dirs = sorted({p.parent.relative_to(run_root).as_posix()
                                for p in groups[run_root]})
            info["targets"] = test_dirs or ["."]
            info["test_dir"] = info["targets"][0]

        package_json = project_dir / "package.json"
        if package_json.exists():
            try:
                package = json.loads(package_json.read_text(encoding="utf-8"))
                if "test" in (package.get("scripts") or {}):
                    info["node"] = True
                    info["frameworks"].append("node")
            except (ValueError, OSError):
                pass
        return info

    # ------------------------------------------------------------------- build
    def build_command(self, project_dir: Path, *, target: str = "") -> tuple[list[str], Path]:
        """Return ``(command, cwd)`` for the discovered test layout."""
        discovery = self.discover(project_dir)
        if discovery["pytest"]:
            cwd = (Path(project_dir) / discovery["cwd"]).resolve()
            targets = [target.strip()] if target.strip() else (discovery["targets"] or ["tests"])
            return (
                ["python3", "-m", "pytest", *targets, "-v", "--tb=short",
                 "-p", "no:cacheprovider", "--color=no", "--no-header", "-rN"],
                cwd,
            )
        if discovery["node"]:
            return (["npm", "test", "--silent"], Path(project_dir).resolve())
        raise ExecutionError(
            "No runnable test suite was found in the project workspace. "
            "The Testing Agent must generate tests first.",
            detail={"workspace": str(project_dir)},
        )

    # --------------------------------------------------------------------- run
    def run(self, project_dir: Path, *, target: str = "", timeout: int | None = None) -> ParsedTestRun:
        project_dir = Path(project_dir).resolve()
        if not project_dir.exists():
            raise ExecutionError("Project workspace does not exist.", detail={"path": str(project_dir)})

        discovery = self.discover(project_dir)
        command, cwd = self.build_command(project_dir, target=target)
        logger.info("Running tests: %s (cwd=%s, layout=%s)",
                    " ".join(command), cwd, discovery.get("frameworks"))
        result: ExecutionResult = self.executor.run(command, cwd=cwd, timeout=timeout)

        combined = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        parsed = self.parse(combined, exit_code=result.exit_code, duration_ms=result.duration_ms)
        parsed.command = result.command
        parsed.provider = result.provider
        parsed.timed_out = result.timed_out
        parsed.raw_output = combined[-60_000:]
        parsed.layout = discovery
        if result.timed_out:
            parsed.status = "ERROR"
            parsed.notes.append(f"Execution timed out after {timeout or 'configured'} seconds.")
        if result.exit_code == 5:  # pytest: no tests collected
            parsed.status = "ERROR"
            parsed.notes.append("Pytest collected no tests (exit code 5).")
        if not parsed.results and parsed.total == 0:
            parsed.notes.append(
                "No individual test results could be parsed; see the raw output. "
                "This usually means test collection failed."
            )
        return parsed

    # ------------------------------------------------------------------- parse
    def parse(self, output: str, *, exit_code: int = 0, duration_ms: int = 0) -> ParsedTestRun:
        """Parse pytest-style verbose output into structured results."""
        parsed = ParsedTestRun(exit_code=exit_code, duration_ms=duration_ms, raw_output=output)

        json_results = self._try_json_report(output)
        if json_results is not None:
            parsed.parser = "json-report"
            parsed.results, counters = json_results
            parsed.passed = counters.get("passed", 0)
            parsed.failed = counters.get("failed", 0)
            parsed.skipped = counters.get("skipped", 0)
            parsed.errors = counters.get("errors", 0)
            parsed.total = sum(counters.values())
        else:
            for match in RESULT_LINE_RE.finditer(output):
                status = match.group("status")
                normalised = {
                    "PASSED": "PASSED", "FAILED": "FAILED", "ERROR": "ERROR",
                    "SKIPPED": "SKIPPED", "XFAIL": "SKIPPED", "XPASS": "PASSED",
                }[status]
                parsed.results.append(
                    ParsedTestResult(
                        name=f"{match.group('file')}::{match.group('name')}",
                        file_path=match.group("file"),
                        status=normalised,
                    )
                )
            # fall back to the summary line when verbose parsing found nothing
            counts = self._summary_counts(output)
            parsed.passed = counts.get("passed", 0)
            parsed.failed = counts.get("failed", 0)
            parsed.skipped = counts.get("skipped", 0)
            parsed.errors = counts.get("errors", 0)
            parsed.total = parsed.passed + parsed.failed + parsed.skipped + parsed.errors
            if parsed.results:
                self._attach_failure_messages(output, parsed)

        if parsed.total == 0 and parsed.results:
            parsed.total = len(parsed.results)

        if parsed.failed or parsed.errors or (exit_code != 0 and parsed.total == 0):
            parsed.status = "FAILED" if parsed.total else "ERROR"
        elif parsed.total and not parsed.failed and not parsed.errors:
            parsed.status = "PASSED"
        else:
            parsed.status = "ERROR" if exit_code != 0 else "PASSED"

        duration_match = DURATION_RE.search(output)
        if duration_match and not duration_ms:
            parsed.duration_ms = int(float(duration_match.group("seconds")) * 1000)
        return parsed

    # ---------------------------------------------------------------- internals
    @staticmethod
    def _summary_counts(output: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        # only inspect the final summary lines
        tail = "\n".join(line for line in output.splitlines()[-25:])
        for match in SUMMARY_RE.finditer(tail):
            kind = match.group("kind")
            kind = {"error": "errors", "errors": "errors", "warning": "warnings",
                    "warnings": "warnings"}.get(kind, kind)
            if kind in {"warnings"}:
                continue
            counts[kind] = max(counts.get(kind, 0), int(match.group("count")))
        return counts

    @staticmethod
    def _attach_failure_messages(output: str, parsed: ParsedTestRun) -> None:
        bodies = {m.group("name").strip(): m.group("body").strip()
                  for m in FAIL_SHORT_RE.finditer(output)}
        if not bodies:
            return
        for result in parsed.results:
            short = result.name.split("::")[-1]
            for key, body in bodies.items():
                if key.endswith(short) or short in key:
                    result.message = body[:1500]
                    break

    @staticmethod
    def _try_json_report(output: str) -> tuple[list[ParsedTestResult], dict[str, int]] | None:
        """Consume a pytest-json-report blob if the plugin emitted one inline."""
        marker = '{"created":'
        index = output.find(marker)
        if index == -1:
            return None
        try:
            data = json.loads(output[index:])
        except ValueError:
            return None
        results: list[ParsedTestResult] = []
        counters = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
        for test in data.get("tests", []):
            outcome = test.get("outcome", "failed")
            status = {"passed": "PASSED", "failed": "FAILED", "skipped": "SKIPPED",
                      "error": "ERROR"}.get(outcome, "FAILED")
            key = "errors" if status == "ERROR" else status.lower() + ("s" if status == "PASSED" else "")
            counters_key = {"PASSED": "passed", "FAILED": "failed", "SKIPPED": "skipped",
                            "ERROR": "errors"}[status]
            counters[counters_key] += 1
            results.append(
                ParsedTestResult(
                    name=f"{test.get('nodeid', '')}",
                    file_path=(test.get("nodeid") or "").split("::")[0],
                    status=status,
                    duration_ms=int(float(test.get("duration", 0)) * 1000),
                    message=((test.get("call") or {}).get("longrepr") or "")[:1500],
                )
            )
        return results, counters
