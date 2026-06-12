"""
e2_runtime_snapshot.py -- test-only helper: E2 runtime snapshots.

Used by the E2 test suites to assert the runtime-aware guarantee

    "a test must not create or mutate real-repo E2 runtime artifacts"

instead of the pre-live-trial absence guarantee ("runtime paths must
never exist").  Legitimate runtime artifacts from real dry-run use are
tolerated; any test-created change to them fails the comparison.

Snapshots contain only relative paths, sizes, and content hashes --
never file content -- so assertion diffs stay secret-free.

This file is a helper, not a test module (it does not match the
test*.py discovery pattern).
"""

import hashlib
from pathlib import Path

E2_RUNTIME_PATHS = (
    "inbox/e2",
    "inbox/e2/approved",
    "inbox/e2/rejected",
    "inbox/e2/expired",
    "outbox/e2",
    "outbox/e2/reports",
    "state/e2-registry.json",
    "state/e2-history",
)

SNAPSHOT_MISMATCH_MESSAGE = (
    "E2 runtime snapshot changed: the test created or mutated real-repo "
    "runtime artifacts")


def _file_record(file: Path):
    data = file.read_bytes()
    return (len(data), hashlib.sha256(data).hexdigest())


def snapshot_e2_runtime(root) -> dict:
    """Stable snapshot of the real-repo E2 runtime namespace.

    Maps each known runtime path to None (absent), a ("file", size,
    sha256) record, or a ("dir", ((relative_path, (size, sha256)), ...))
    record covering every file beneath it.  Deterministic; file content
    is never stored or echoed."""
    root = Path(root)
    snapshot = {}
    for rel in E2_RUNTIME_PATHS:
        target = root / rel
        if target.is_file():
            snapshot[rel] = ("file",) + _file_record(target)
        elif target.is_dir():
            files = {}
            for child in sorted(target.rglob("*")):
                if child.is_file():
                    files[child.relative_to(root).as_posix()] = (
                        _file_record(child))
            snapshot[rel] = ("dir", tuple(sorted(files.items())))
        else:
            snapshot[rel] = None
    return snapshot
