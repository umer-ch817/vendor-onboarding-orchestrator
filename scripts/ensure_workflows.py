"""Make sure the four n8n workflows exist and are published.

Importing a workflow **deactivates** it until n8n restarts. So this must never
run blindly on every start: it first asks n8n what it already has, and only
imports what is missing. Otherwise a normal startup would take every workflow
offline for no reason, which is exactly the kind of thing that makes a demo
mysteriously stop working.

Usage:  python scripts/ensure_workflows.py
Exit code 0 = all four present (or successfully installed).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# File stem -> the display name n8n knows it by.
WORKFLOWS = {
    "case_orchestrator": "Vendor Onboarding - Case Orchestrator",
    "document_intake": "Vendor Onboarding - Document Intake",
    "sla_escalation": "Vendor Onboarding - SLA Escalation",
    "error_handler": "Vendor Onboarding - Error Handler",
}

CONTAINER_WORKFLOW_DIR = "/home/node/.n8n/workflows"


def _normalise(name: str) -> str:
    """Compare names without fighting over dash characters.

    The workflow titles use an em dash; a terminal, a Windows console and a
    Python source file can each render that differently. Collapsing every dash
    to a hyphen means the comparison is about the words, not the punctuation.
    """
    return (
        name.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2012", "-")
        .strip()
        .lower()
    )


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _n8n(*args: str) -> subprocess.CompletedProcess:
    return _run(["docker", "compose", "exec", "-T", "n8n", "n8n", *args])


def _listed_workflows() -> dict[str, str] | None:
    """Return {normalised name: id} or None if n8n could not be reached."""
    result = _n8n("list:workflow")
    if result.returncode != 0:
        return None
    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        workflow_id, _, name = line.partition("|")
        name = name.strip()
        if name:
            found[_normalise(name)] = workflow_id.strip()
    return found


def main() -> int:
    # n8n can still be booting; give it a chance before giving up.
    found = None
    for _ in range(15):
        found = _listed_workflows()
        if found is not None:
            break
        time.sleep(2)

    if found is None:
        print("  [!!] Could not reach n8n to check its workflows.")
        print("       Start it with: docker compose up -d")
        return 1

    missing = [
        stem for stem, name in WORKFLOWS.items() if _normalise(name) not in found
    ]

    if not missing:
        print(f"  [ok] All {len(WORKFLOWS)} n8n workflows already installed")
        return 0

    print(f"  [..] Installing {len(missing)} missing workflow(s)...")
    for stem in missing:
        result = _n8n(
            "import:workflow",
            f"--input={CONTAINER_WORKFLOW_DIR}/{stem}.json",
        )
        if result.returncode != 0:
            print(f"  [!!] Failed to import {stem}")
            print(f"       {result.stderr.strip()[:300]}")
            return 1
        print(f"       imported {stem}")

    # Publishing only takes effect after a restart.
    found = _listed_workflows() or {}
    for name in WORKFLOWS.values():
        workflow_id = found.get(_normalise(name))
        if workflow_id:
            _n8n("publish:workflow", f"--id={workflow_id}")

    print("  [..] Restarting n8n so the workflows go live...")
    _run(["docker", "compose", "restart", "n8n"])

    for _ in range(20):
        time.sleep(2)
        found = _listed_workflows()
        if found is not None:
            break

    still_missing = [
        stem for stem, name in WORKFLOWS.items()
        if not found or _normalise(name) not in found
    ]
    if still_missing:
        print(f"  [!!] Still missing after install: {', '.join(still_missing)}")
        return 1

    print(f"  [ok] All {len(WORKFLOWS)} n8n workflows installed and live")
    return 0


if __name__ == "__main__":
    sys.exit(main())
