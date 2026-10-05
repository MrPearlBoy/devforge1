"""Sandboxed execution of generated test suites and static security scans.

Everything runs through :func:`_run` — ``subprocess.run`` with an argument
list (never ``shell=True``), a hard timeout and captured stdout/stderr —
inside the active project workspace only.
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


def _run(cmd: list[str], cwd: Path, timeout: float) -> RunResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return RunResult(proc.returncode, proc.stdout or "", proc.stderr or "", time.monotonic() - start)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="ignore") if isinstance(exc.stdout, (bytes, bytearray)) else (exc.stdout or "")
        err = exc.stderr.decode(errors="ignore") if isinstance(exc.stderr, (bytes, bytearray)) else (exc.stderr or "")
        return RunResult(124, out, err + f"\n[execution sandbox: timeout after {timeout:.0f}s]", time.monotonic() - start)
    except FileNotFoundError as exc:
        return RunResult(127, "", str(exc), time.monotonic() - start)


# --------------------------------------------------------------------------
# pytest
# --------------------------------------------------------------------------
def _count(pattern: str, output: str) -> int:
    m = re.search(pattern, output)
    return int(m.group(1)) if m else 0


def run_pytest(workspace: Path, timeout: float = 180) -> dict[str, Any]:
    """Execute ``pytest tests`` inside the workspace and parse the report."""
    cmd = [sys.executable, "-m", "pytest", "tests", "-q", "--tb=short", "-p", "no:cacheprovider"]
    r = _run(cmd, workspace, timeout)
    passed_c = _count(r"(\d+) passed", r.stdout)
    failed_c = _count(r"(\d+) failed", r.stdout)
    error_c = _count(r"(\d+) error", r.stdout)
    failures = [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith("FAILED")]

    summary = ""
    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    for s in reversed(lines):
        if s.startswith("=") and ("passed" in s or "failed" in s or "error" in s):
            summary = s.strip("=").strip()
            break
    if not summary and lines:
        # pytest -q prints a bare summary line, e.g. "25 passed in 0.03s"
        last = lines[-1]
        if any(k in last for k in ("passed", "failed", "error", "no tests ran")):
            summary = last
    if not summary:
        summary = f"pytest exited with code {r.exit_code}"

    output = r.stdout + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")
    passed = r.exit_code == 0 and failed_c == 0 and error_c == 0
    return {
        "passed": passed,
        "total": passed_c + failed_c + error_c,
        "passed_count": passed_c,
        "failed_count": failed_c,
        "error_count": error_c,
        "exit_code": r.exit_code,
        "duration_s": round(r.duration_s, 3),
        "summary": summary,
        "output": output[:60000],
        "failures": failures,
    }


# --------------------------------------------------------------------------
# Security scanning
# --------------------------------------------------------------------------
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret[_-]?key|password|passwd|access[_-]?token|auth[_-]?token|private[_-]?key)\b"
    r"\s*=\s*[\"']([^\"'\s]{8,})[\"']"
)
_SQL_INJECT_RE = re.compile(
    r"(?i)\bexecute\s*\(\s*(?:f[\"']|[\"'][^\"']*[?%][^\"']*[\"']\s*(?:%\s*\(|%\s*\w|\.format\s*\(|\+\s*\w))"
)


def _rel(path: str | Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def _attr_base(node: ast.AST, base: str) -> bool:
    """True when the call target is ``base.attr`` (e.g. pickle.loads)."""
    f = node.func
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == base


def _kw_true(node: ast.Call, arg: str) -> bool:
    for kw in node.keywords:
        if kw.arg == arg and isinstance(kw.value, ast.Constant) and kw.value.value is True:
            return True
    return False


def _kw_false(node: ast.Call, arg: str) -> bool:
    for kw in node.keywords:
        if kw.arg == arg and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return True
    return False


def ast_security_scan(src: Path) -> list[dict[str, Any]]:
    """Built-in AST + regex static analyzer (fallback when bandit is absent)."""
    findings: list[dict[str, Any]] = []
    root = src.parent  # workspace root (src = workspace/src)
    for py in sorted(src.rglob("*.py")):
        rel = _rel(py, root)
        text = py.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            findings.append(
                {
                    "severity": "HIGH",
                    "category": "syntax",
                    "message": f"unparseable Python ({exc.msg}) — cannot verify safety",
                    "file": rel,
                    "line": exc.lineno,
                }
            )
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name: Optional[str] = None
            if isinstance(f, ast.Name):
                name = f.id
            elif isinstance(f, ast.Attribute):
                name = f.attr
            if name is None:
                continue

            if name in ("eval", "exec") and isinstance(f, ast.Name):
                findings.append(
                    {"severity": "HIGH", "category": "unsafe-call", "message": f"dangerous dynamic code execution: {name}()", "file": rel, "line": node.lineno}
                )
            elif name == "system" and _attr_base(node, "os"):
                findings.append(
                    {"severity": "HIGH", "category": "shell-injection", "message": "os.system() can be exploited via shell metacharacters", "file": rel, "line": node.lineno}
                )
            elif name in ("Popen", "run", "call", "check_output") and _attr_base(node, "subprocess") and _kw_true(node, "shell"):
                findings.append(
                    {"severity": "HIGH", "category": "shell-injection", "message": "subprocess with shell=True", "file": rel, "line": node.lineno}
                )
            elif name in ("loads", "load") and _attr_base(node, "pickle"):
                findings.append(
                    {"severity": "HIGH", "category": "insecure-deserialization", "message": "pickle deserialization of untrusted data can execute arbitrary code", "file": rel, "line": node.lineno}
                )
            elif name in ("md5", "sha1") and _attr_base(node, "hashlib"):
                findings.append(
                    {"severity": "MEDIUM", "category": "weak-hash", "message": f"cryptographically weak hash: hashlib.{name}", "file": rel, "line": node.lineno}
                )
            elif name == "load" and _attr_base(node, "yaml"):
                has_safe = any(isinstance(kw.value, ast.Name) and kw.value.id in ("SafeLoader", "CSafeLoader") for kw in node.keywords if kw.arg == "Loader")
                if not has_safe:
                    findings.append(
                        {"severity": "MEDIUM", "category": "insecure-yaml", "message": "yaml.load() without SafeLoader", "file": rel, "line": node.lineno}
                    )
            elif name in ("get", "post", "put", "request", "delete") and _attr_base(node, "requests") and _kw_false(node, "verify"):
                findings.append(
                    {"severity": "MEDIUM", "category": "tls", "message": "TLS certificate verification disabled (verify=False)", "file": rel, "line": node.lineno}
                )

        for lineno, line in enumerate(text.splitlines(), 1):
            m = _SECRET_RE.search(line)
            if m:
                findings.append(
                    {
                        "severity": "HIGH",
                        "category": "hardcoded-secret",
                        "message": f"possible hardcoded secret assigned to '{m.group(1)}'",
                        "file": rel,
                        "line": lineno,
                    }
                )
            if _SQL_INJECT_RE.search(line):
                findings.append(
                    {
                        "severity": "HIGH",
                        "category": "sql-injection",
                        "message": "SQL query built with string interpolation — use parameterized queries",
                        "file": rel,
                        "line": lineno,
                    }
                )
    return findings


def _bandit_available() -> bool:
    try:
        import bandit  # noqa: F401

        return True
    except Exception:
        return False


def run_security_scan(workspace: Path, timeout: float = 120) -> dict[str, Any]:
    """Scan ``workspace/src`` with bandit when available, else the AST analyzer.

    ``clean`` means *no HIGH-severity findings*; MEDIUM/LOW are reported as
    informational and do not block the pipeline.
    """
    src = workspace / "src"
    findings: list[dict[str, Any]] = []
    raw = ""
    used_bandit = False

    if src.exists() and _bandit_available():
        r = _run([sys.executable, "-m", "bandit", "-r", str(src), "-f", "json", "-q"], workspace, timeout)
        try:
            data = json.loads(r.stdout)
            for res in data.get("results", []):
                findings.append(
                    {
                        "severity": res.get("issue_severity", "LOW"),
                        "category": f"bandit:{res.get('test_id', 'unknown')}",
                        "message": res.get("issue_text", ""),
                        "file": _rel(res.get("filename", ""), workspace),
                        "line": res.get("line_number"),
                    }
                )
            raw = json.dumps(data, indent=2)[:20000]
            used_bandit = True
        except (json.JSONDecodeError, ValueError):
            used_bandit = False

    if not used_bandit:
        findings = ast_security_scan(src) if src.exists() else []
        if findings:
            raw = "\n".join(
                f"[{f['severity']}] {f['file']}:{f.get('line') or '?'} ({f['category']}): {f['message']}"
                for f in findings
            )
        else:
            raw = "AST/regex security scan: no issues found."

    blocking = [f for f in findings if f["severity"] == "HIGH"]
    return {
        "clean": len(blocking) == 0,
        "tool": "bandit" if used_bandit else "ast-scanner",
        "findings": findings,
        "output": raw,
    }
