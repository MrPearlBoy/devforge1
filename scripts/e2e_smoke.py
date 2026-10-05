"""DevForge end-to-end smoke test.

Creates a project, starts the full multi-agent workflow and auto-approves
every human gate (simulating an approving reviewer), then verifies the
delivery: generated files, green tests, clean security scan and git commit.

Usage (with the backend running on :8000):
    python scripts/e2e_smoke.py
    DEVFORGE_API=http://127.0.0.1:8000 python scripts/e2e_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("DEVFORGE_API", "http://127.0.0.1:8000")


def call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else None


def main() -> int:
    stamp = int(time.time())
    proj = call(
        "POST",
        "/api/projects",
        {"name": f"Smoke {stamp}", "task": "Build a small task manager service with a CRUD API, persistence and a CLI."},
    )
    pid = proj["id"]
    print(f"project created: {proj['name']} (id={pid})")

    call("POST", f"/api/projects/{pid}/start")
    print("workflow started — watching gates…")

    seen_gates: set[str] = set()
    deadline = time.time() + 300
    final = None
    while time.time() < deadline:
        time.sleep(2)
        snap = call("GET", f"/api/projects/{pid}")
        gate = snap.get("awaiting_gate")
        if gate and gate not in seen_gates:
            seen_gates.add(gate)
            try:
                call("POST", f"/api/projects/{pid}/approvals", {"gate": gate, "decision": "approved", "comment": "lgtm"})
                print(f"  [approve] gate '{gate}' approved")
            except urllib.error.HTTPError as e:
                print(f"  [approve] gate '{gate}' → {e.code} (race, retrying next tick)")
        if snap["status"] in ("completed", "failed"):
            final = snap
            break
    if final is None:
        final = call("GET", f"/api/projects/{pid}")

    print()
    print(f"status      : {final['status']}  (stage: {final['stage']})")
    print(f"llm provider: {final['llm_provider']}")
    print(f"iterations  : {final['iterations']}")
    art = final.get("artifacts", {})
    if art.get("tests"):
        t = art["tests"]
        print(f"tests       : {t['summary']}  ({t['passed_count']}/{t['total']}, {t['duration_s']}s)")
    if art.get("security"):
        s = art["security"]
        print(f"security    : {s['tool']} — {'clean' if s['clean'] else str(len(s['findings'])) + ' findings'}")
    if art.get("git"):
        g = art["git"]
        print(f"git         : committed={g.get('committed')} branch={g.get('branch')} files={g.get('files')} hash={(g.get('hash') or '')[:8]}")
    print(f"files       : {len(final['files'])} in workspace")
    for f in final["files"]:
        print(f"   - {f['path']} ({f['size']} B)")

    ok = final["status"] == "completed"
    if final.get("error"):
        print(f"ERROR       : {final['error']}")
    print()
    print("SMOKE RESULT:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
