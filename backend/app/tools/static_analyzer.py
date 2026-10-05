"""Static analysis engine used by the Security Agent.

Design notes / honest limitations (also stated in the generated report):

* This is a **rule-based scanner** over project source, configuration and
  dependency manifests.  It is fast, dependency-free and explainable, which is
  what a teaching project needs — it is NOT a replacement for Semgrep,
  Bandit, CodeQL, ``pip-audit`` or GitHub Advanced Security.
* Dependency checks use a *small curated advisory table*, not a live CVE feed.
* Findings are heuristic: expect false positives, which is why every finding has
  a human triage status (OPEN / ACKNOWLEDGED / FIXED / FALSE_POSITIVE).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models.enums import Severity

MAX_FILE_BYTES = 300_000
SCANNABLE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yml", ".yaml", ".env", ".ini",
    ".cfg", ".toml", ".sql", ".sh", ".html", ".tf", ".dockerfile", ".txt", ".conf",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".pytest_cache", ".mypy_cache", "coverage"}


@dataclass
class Rule:
    rule_id: str
    category: str
    severity: Severity
    title: str
    description: str
    recommendation: str
    patterns: tuple[re.Pattern, ...]
    suffixes: tuple[str, ...] = ()
    file_names: tuple[str, ...] = ()
    #: Skip matches inside lines that look like documentation/placeholders.
    allow_placeholder: bool = True


@dataclass
class ScanFinding:
    rule_id: str
    severity: str
    category: str
    title: str
    description: str
    file_path: str
    line: int | None
    evidence: str
    recommendation: str
    detected_by: str = "security_agent:rules"

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line": self.line,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "detected_by": self.detected_by,
        }


@dataclass
class ScanReport:
    findings: list[ScanFinding] = field(default_factory=list)
    files_scanned: int = 0
    rules_run: int = 0
    skipped: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def tally(self) -> dict[str, int]:
        counts = {severity.value: 0 for severity in Severity}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        self.counts = counts
        return counts


PLACEHOLDER_HINTS = ("example", "placeholder", "your_", "your-", "yourpass", "changeme",
                     "change-me", "change_me", "xxxx", "dummy", "fake", "devforge-mock",
                     "test-only", "test_only", "<your", "${")

RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="SEC-SECRET-001",
        category="Secrets",
        severity=Severity.CRITICAL,
        title="Hardcoded credential or API key",
        description="A secret-looking value is assigned directly in source code.",
        recommendation=(
            "Move the value into an environment variable or secret manager and load it at "
            "runtime (e.g. os.environ[...] / settings). Rotate the exposed credential."
        ),
        patterns=(
            re.compile(r"""(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|"""
                       r"""client[_-]?secret|private[_-]?key|password)\s*[:=]\s*["']([^"']{8,})["']"""),
        ),
    ),
    Rule(
        rule_id="SEC-SECRET-002",
        category="Secrets",
        severity=Severity.CRITICAL,
        title="Cloud provider key pattern detected",
        description="Text matching a well-known cloud credential format was found.",
        recommendation="Revoke the key immediately, rotate it, and load credentials from the environment.",
        patterns=(
            re.compile(r"AKIA[0-9A-Z]{16}"),
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            re.compile(r"ghp_[A-Za-z0-9]{30,}"),
            re.compile(r"sk-[A-Za-z0-9]{20,}"),
        ),
    ),
    Rule(
        rule_id="SEC-CONF-001",
        category="Configuration",
        severity=Severity.HIGH,
        title="Debug mode enabled",
        description="Debug mode leaks stack traces and internal state to end users.",
        recommendation="Disable debug mode outside local development and rely on server-side logging.",
        patterns=(
            re.compile(r"(?i)\bdebug\s*[:=]\s*(?:true|1|True)\b"),
            re.compile(r"(?i)app\.run\([^)]*debug\s*=\s*True"),
        ),
    ),
    Rule(
        rule_id="SEC-CONF-002",
        category="Configuration",
        severity=Severity.HIGH,
        title="Permissive CORS configuration",
        description="Allowing every origin enables cross-site requests with credentials leaks.",
        recommendation="List explicit trusted origins and avoid wildcard origins with credentials.",
        patterns=(re.compile(r"""(?i)allow_origins\s*[:=]\s*\[?\s*["']\*["']"""),),
    ),
    Rule(
        rule_id="SEC-CONF-003",
        category="Configuration",
        severity=Severity.HIGH,
        title="JWT signing secret looks weak or default",
        description="A short or default-looking JWT secret allows token forgery.",
        recommendation="Use a 32+ byte random secret from the environment and rotate it regularly.",
        patterns=(
            re.compile(r"""(?i)(jwt[_-]?secret|secret[_-]?key)\s*[:=]\s*["']([^"']{1,31})["']"""),
        ),
    ),
    Rule(
        rule_id="SEC-EXEC-001",
        category="Injection",
        severity=Severity.HIGH,
        title="Shell invocation with shell=True",
        description="Passing shell=True with dynamic input enables command injection.",
        recommendation="Pass an argument list and keep shell=False; validate any user input used in commands.",
        patterns=(re.compile(r"subprocess\.(?:run|call|check_output|Popen)\([^)]*shell\s*=\s*True"),),
    ),
    Rule(
        rule_id="SEC-EXEC-002",
        category="Injection",
        severity=Severity.HIGH,
        title="Dynamic code evaluation",
        description="eval()/exec() on non-constant input executes arbitrary code.",
        recommendation="Avoid eval/exec; use a parser, an explicit dispatch table or a sandboxed evaluator.",
        patterns=(re.compile(r"\b(?:eval|exec)\s*\(\s*(?!['\"])"),),
    ),
    Rule(
        rule_id="SEC-SQL-001",
        category="Injection",
        severity=Severity.CRITICAL,
        title="SQL built by string concatenation",
        description="Concatenating or f-formatting SQL invites SQL injection.",
        recommendation="Use parameterised queries / ORM bind parameters everywhere.",
        patterns=(
            re.compile(r"""(?i)(execute|executemany)\s*\(\s*(f["']|["'][^"']*["']\s*\+|["'][^"']*%s?["']\s*%)"""),
            re.compile(r"(?i)select\s+.*\bfrom\b.*[\"']\s*\+\s*\w+"),
            re.compile(r'(?i)(?:cursor|db|conn)\.execute\(\s*f["\']'),
        ),
    ),
    Rule(
        rule_id="SEC-XSS-001",
        category="Client-side",
        severity=Severity.HIGH,
        title="Unsanitised HTML rendering",
        description="Rendering raw HTML from data can execute injected scripts.",
        recommendation="Render text nodes, or sanitise with a vetted library (e.g. DOMPurify) before insertion.",
        patterns=(
            re.compile(r"dangerouslySetInnerHTML"),
            re.compile(r"\.innerHTML\s*="),
            re.compile(r"document\.write\("),
        ),
    ),
    Rule(
        rule_id="SEC-AUTH-001",
        category="Authentication",
        severity=Severity.HIGH,
        title="Password handled without hashing",
        description="Passwords appear to be compared or stored in plaintext.",
        recommendation="Hash passwords with bcrypt/argon2 and compare with a constant-time verify function.",
        patterns=(
            re.compile(r"(?i)password\s*==\s*\w+"),
            re.compile(r"""(?i)password\s*[:=]\s*["'][^"']{6,}["']"""),
        ),
    ),
    Rule(
        rule_id="SEC-AUTH-002",
        category="Authentication",
        severity=Severity.MEDIUM,
        title="Token issued with no expiry",
        description="Tokens without an expiry remain valid indefinitely if leaked.",
        recommendation="Always set an ``exp`` claim and keep the lifetime short.",
        patterns=(re.compile(r"(?i)jwt\.encode\((?!.*\bexp\b)[^)]*\)"),),
    ),
    Rule(
        rule_id="SEC-CRYPTO-001",
        category="Cryptography",
        severity=Severity.HIGH,
        title="Weak hashing algorithm",
        description="MD5/SHA-1 are unsuitable for integrity or password storage.",
        recommendation="Use SHA-256+ for integrity and bcrypt/argon2 for passwords.",
        patterns=(re.compile(r"(?i)hashlib\.(md5|sha1)\("),),
    ),
    Rule(
        rule_id="SEC-CRYPTO-002",
        category="Cryptography",
        severity=Severity.MEDIUM,
        title="Insecure randomness for secrets",
        description="random module is predictable; it must not generate tokens or keys.",
        recommendation="Use the secrets module or os.urandom for security-relevant values.",
        patterns=(re.compile(r"(?i)(token|secret|password|salt|nonce)\s*[:=]\s*random\.\w+\("),),
    ),
    Rule(
        rule_id="SEC-PATH-001",
        category="File handling",
        severity=Severity.MEDIUM,
        title="File path built from request data",
        description="Untrusted path fragments enable directory traversal.",
        recommendation="Resolve the path against a fixed base directory and reject anything escaping it.",
        patterns=(
            re.compile(r"open\(\s*(?:f[\"'][^\"']*\{)?(?:request|params|query|input|user_)\w*"),
            re.compile(r"os\.path\.join\([^)]*(request|params|query|input)"),
        ),
    ),
    Rule(
        rule_id="SEC-LOG-001",
        category="Logging",
        severity=Severity.LOW,
        title="Sensitive value written to logs",
        description="Logging credentials leaks them into log storage and tooling.",
        recommendation="Log identifiers, never secrets; redact before logging.",
        patterns=(
            re.compile(r"(?i)(log(ger)?\.\w+|print)\s*\(.*(password|token|secret|api_key)"),
        ),
    ),
    Rule(
        rule_id="SEC-DOCKER-001",
        category="Deployment",
        severity=Severity.MEDIUM,
        title="Container configured with elevated privileges",
        description="Privileged containers or root users weaken isolation.",
        recommendation="Drop privileges (USER nonroot), avoid --privileged and trim capabilities.",
        patterns=(
            re.compile(r"(?i)^\s*USER\s+root\b", re.MULTILINE),
            re.compile(r"(?i)--privileged"),
        ),
        file_names=("dockerfile", "docker-compose.yml", "docker-compose.yaml"),
        allow_placeholder=False,
    ),
    Rule(
        rule_id="SEC-DEP-001",
        category="Dependencies",
        severity=Severity.LOW,
        title="Unpinned dependency range",
        description="Floating version ranges can silently pull in vulnerable releases.",
        recommendation="Pin dependencies (or use a lockfile) and update them deliberately.",
        patterns=(re.compile(r"^[A-Za-z0-9_.\-]+\s*(?:>=|~=|\^|>)\s*[0-9]"),),
        file_names=("requirements.txt", "requirements-dev.txt", "package.json"),
        allow_placeholder=False,
    ),
    Rule(
        rule_id="SEC-CORS-001",
        category="Configuration",
        severity=Severity.MEDIUM,
        title="Credentials with wildcard origin",
        description="allow_credentials with '*' origin is rejected by browsers and hints at a misconfiguration.",
        recommendation="Use explicit origins when credentials are enabled.",
        patterns=(re.compile(r"""(?is)allow_credentials\s*=\s*True.{0,120}?["']\*["']"""),),
    ),
)

#: Minimal curated advisory table (documented as NOT a live CVE feed).
INSECURE_DEPENDENCIES: tuple[tuple[str, str, Severity, str], ...] = (
    ("django", "<2.2", Severity.HIGH, "Multiple known vulnerabilities in unsupported Django releases."),
    ("flask", "<1.0", Severity.HIGH, "Old Flask releases ship vulnerable Werkzeug/Jinja pins."),
    ("jinja2", "<3.1.4", Severity.HIGH, "CVE-2024-34064 sandbox escape via xmlattr."),
    ("pyyaml", "<5.4", Severity.HIGH, "CVE-2020-14343 arbitrary code execution via yaml.load."),
    ("requests", "<2.31.0", Severity.MEDIUM, "CVE-2023-32681 proxy credential leak."),
    ("urllib3", "<1.26.18", Severity.MEDIUM, "CVE-2023-45803 request body leak on redirect."),
    ("pillow", "<10.3.0", Severity.MEDIUM, "Older Pillow releases have buffer overflow issues."),
    ("cryptography", "<41.0.0", Severity.MEDIUM, "Older releases include vulnerable OpenSSL builds."),
    ("lodash", "<4.17.21", Severity.HIGH, "Prototype pollution / command injection advisories."),
    ("axios", "<1.6.0", Severity.MEDIUM, "SSRF and request smuggling advisories."),
    ("express", "<4.19.2", Severity.MEDIUM, "Open redirect advisory in older Express 4.x."),
    ("jsonwebtoken", "<9.0.0", Severity.HIGH, "Insecure default verification in older releases."),
)


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", text or "")
    return tuple(int(p) for p in parts[:4]) or (0,)


def _is_placeholder(line: str) -> bool:
    lowered = line.lower()
    return any(hint in lowered for hint in PLACEHOLDER_HINTS)


class StaticAnalyzer:
    """Rule-based static analysis over a dictionary of project files."""

    def __init__(self, rules: tuple[Rule, ...] = RULES) -> None:
        self.rules = rules

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _applicable(rule: Rule, path: str) -> bool:
        """Decide whether a rule applies to a file (by name, or by suffix)."""
        lowered = path.lower()
        filename = lowered.rsplit("/", 1)[-1]
        suffix = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
        if rule.file_names:
            return filename in rule.file_names
        if rule.suffixes:
            return suffix in rule.suffixes
        if suffix:
            return suffix in SCANNABLE_SUFFIXES
        return filename in {".env", "dockerfile", "makefile"}

    def scan_files(self, files: dict[str, str]) -> ScanReport:
        report = ScanReport(rules_run=len(self.rules))
        for path, content in files.items():
            if any(part in SKIP_DIRS for part in path.split("/")):
                report.skipped.append(path)
                continue
            if len(content) > MAX_FILE_BYTES:
                report.skipped.append(path)
                continue
            report.files_scanned += 1
            report.findings.extend(self._scan_file(path, content))
        report.findings.extend(self._scan_dependencies(files))
        # de-duplicate identical findings, keep stable ordering by severity
        seen: set[tuple] = set()
        unique: list[ScanFinding] = []
        for finding in report.findings:
            key = (finding.rule_id, finding.file_path, finding.line)
            if key in seen:
                continue
            seen.add(key)
            unique.append(finding)
        order = {s.value: i for i, s in enumerate(Severity)}
        unique.sort(key=lambda f: (order.get(f.severity, 9), f.file_path, f.line or 0))
        report.findings = unique
        report.tally()
        return report

    def _scan_file(self, path: str, content: str) -> list[ScanFinding]:
        findings: list[ScanFinding] = []
        lines = content.splitlines()
        for rule in self.rules:
            if not self._applicable(rule, path):
                continue
            for pattern in rule.patterns:
                for match in pattern.finditer(content):
                    line_number = content[:match.start()].count("\n") + 1
                    snippet = (lines[line_number - 1] if 0 < line_number <= len(lines) else "").strip()
                    if rule.allow_placeholder and _is_placeholder(snippet):
                        continue
                    findings.append(
                        ScanFinding(
                            rule_id=rule.rule_id,
                            severity=rule.severity.value,
                            category=rule.category,
                            title=rule.title,
                            description=rule.description,
                            file_path=path,
                            line=line_number,
                            evidence=snippet[:400] or match.group(0)[:400],
                            recommendation=rule.recommendation,
                        )
                    )
        return findings

    def _scan_dependencies(self, files: dict[str, str]) -> list[ScanFinding]:
        findings: list[ScanFinding] = []
        for path, content in files.items():
            lowered = path.lower().rsplit("/", 1)[-1]
            if lowered not in {"requirements.txt", "package.json", "requirements-dev.txt"}:
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", "//")):
                    continue
                for name, max_version, severity, note in INSECURE_DEPENDENCIES:
                    if re.search(rf"""(?i)["']?{re.escape(name)}["']?\s*[:=]?\s*["']?[<~^=]*\s*[0-9]""", stripped):
                        pinned = re.search(r"[0-9]+(?:\.[0-9]+)*", stripped)
                        if pinned and _version_tuple(pinned.group(0)) >= _version_tuple(max_version):
                            continue
                        findings.append(
                            ScanFinding(
                                rule_id="SEC-DEP-003",
                                severity=severity.value,
                                category="Dependencies",
                                title=f"Outdated dependency: {name}",
                                description=f"{note} (flagged when below {max_version}).",
                                file_path=path,
                                line=line_number,
                                evidence=stripped[:200],
                                recommendation=(
                                    f"Upgrade {name} to a supported release and re-run the scan. "
                                    "Verify with `pip-audit` / `npm audit` in a live environment."
                                ),
                                detected_by="security_agent:dependency-heuristics",
                            )
                        )
                        break
        return findings
