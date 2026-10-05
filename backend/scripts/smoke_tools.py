"""Manual smoke check for the tool layer (run: python scripts/smoke_tools.py)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.workspace import WorkspaceService, diff_stats, unified_diff  # noqa: E402
from app.tools.executor.factory import executor_status, get_executor  # noqa: E402
from app.tools.llm.factory import get_llm_gateway  # noqa: E402
from app.tools.static_analyzer import StaticAnalyzer  # noqa: E402


def main() -> int:
    print("== LLM gateway ==")
    gateway = get_llm_gateway()
    print(json.dumps(gateway.info(), indent=2))
    embedding = gateway.embed(["JWT authentication for the login endpoint"])[0]
    print(f"embedding dim={len(embedding)} sample={embedding[:3]}")

    print("\n== Executor ==")
    print(json.dumps(executor_status(), indent=2, default=str))
    from app.core.config import settings

    sandbox_dir = settings.workspace_path / "_smoke"
    result = get_executor().run(["python3", "-c", "print('sandbox ok')"], cwd=sandbox_dir)
    print("exit:", result.exit_code, "| stdout:", result.stdout.strip(), "| ms:", result.duration_ms)
    blocked = False
    try:
        get_executor().run(["python3", "-c", "print('escape')"], cwd=Path("/tmp"))
    except Exception as exc:  # expected: outside workspace
        blocked = True
        print("outside-workspace execution blocked:", type(exc).__name__)
    assert blocked, "sandbox escaped the workspace!"
    denied = False
    try:
        get_executor().run(["curl", "http://example.com"], cwd=sandbox_dir)
    except Exception as exc:  # expected: not allow-listed
        denied = True
        print("non-allow-listed command blocked:", type(exc).__name__)
    assert denied, "allow-list not enforced"

    print("\n== Workspace ==")
    with tempfile.TemporaryDirectory() as tmp:
        workspace = WorkspaceService(root=Path(tmp))
        workspace.ensure_project("demo-project")
        workspace.write_text("demo-project", "src/auth.py", "def login(user):\n    return user\n")
        old = workspace.read_text("demo-project", "src/auth.py")[0]
        new = "def login(user, password):\n    return user\n"
        diff = unified_diff(old, new, "src/auth.py")
        print(diff)
        print("diff stats (additions, deletions):", diff_stats(diff))
        try:
            workspace.read_text("demo-project", "../../etc/passwd")
            print("SECURITY FAILURE: traversal was allowed")
            return 1
        except Exception as exc:
            print("traversal blocked:", type(exc).__name__)

    print("\n== Static analyzer ==")
    sample = {
        "src/config.py": 'API_KEY = "supersecretvalue123"\nDEBUG = True\nimport hashlib\n'
                        'hashlib.md5(b"x")\n',
        "src/db.py": 'cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")\n',
        "src/run.py": "import subprocess\nsubprocess.run(cmd, shell=True)\n",
        "requirements.txt": "flask==0.12\nrequests>=2.31\n",
        "frontend/App.tsx": "<div dangerouslySetInnerHTML={{__html: body}} />\n",
    }
    report = StaticAnalyzer().scan_files(sample)
    print("files scanned:", report.files_scanned, "| rules:", report.rules_run)
    print("counts:", report.counts)
    for finding in report.findings:
        print(f"  [{finding.severity:<8}] {finding.rule_id:<16} {finding.file_path}:{finding.line} "
              f"- {finding.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
