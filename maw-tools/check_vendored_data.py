#!/usr/bin/env python3
"""Fail when maw_cli/data drifts from the top-level runtime sources."""
from __future__ import annotations

import filecmp
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENDORED_ROOT = ROOT / "maw_cli" / "data"

MIRRORS = (
    (ROOT / "maw-tools", VENDORED_ROOT / "maw-tools", ("*.py",)),
    (ROOT / "templates" / "workflows", VENDORED_ROOT / "templates" / "workflows", ("*.json",)),
    (ROOT / "examples" / "ml_problems", VENDORED_ROOT / "examples" / "ml_problems", ("*.py", "hard_examples/*.json")),
    (ROOT / "examples" / "salvage_js_ts", VENDORED_ROOT / "examples" / "salvage_js_ts", ("*.*",)),
    (ROOT / "examples" / "salvage_topologies", VENDORED_ROOT / "examples" / "salvage_topologies", ("**/*.*",)),
    (ROOT / "packs", VENDORED_ROOT / "packs", ("**/*.*",)),
    (ROOT / "schemas", VENDORED_ROOT / "schemas", ("*.json",)),
)


def relative_files(root: Path, patterns: tuple[str, ...]) -> set[Path]:
    files: set[Path] = set()
    if not root.exists():
        return files
    for pattern in patterns:
        files.update(path.relative_to(root) for path in root.glob(pattern) if path.is_file())
    return files


def compare_mirror(source: Path, vendored: Path, patterns: tuple[str, ...]) -> list[dict[str, str]]:
    source_files = relative_files(source, patterns)
    vendored_files = relative_files(vendored, patterns)
    violations: list[dict[str, str]] = []

    for path in sorted(source_files - vendored_files):
        violations.append({"type": "missing_vendored_file", "source": str(source / path), "vendored": str(vendored / path)})
    for path in sorted(vendored_files - source_files):
        violations.append({"type": "extra_vendored_file", "source": str(source / path), "vendored": str(vendored / path)})
    for path in sorted(source_files & vendored_files):
        source_path = source / path
        vendored_path = vendored / path
        if not filecmp.cmp(source_path, vendored_path, shallow=False):
            violations.append({"type": "byte_drift", "source": str(source_path), "vendored": str(vendored_path)})

    return violations


def check() -> dict[str, object]:
    violations: list[dict[str, str]] = []
    mirrors: list[dict[str, object]] = []
    for source, vendored, patterns in MIRRORS:
        mirror_violations = compare_mirror(source, vendored, patterns)
        violations.extend(mirror_violations)
        mirrors.append(
            {
                "source": str(source),
                "vendored": str(vendored),
                "patterns": list(patterns),
                "source_files": len(relative_files(source, patterns)),
                "vendored_files": len(relative_files(vendored, patterns)),
                "violations": len(mirror_violations),
            }
        )
    return {"passed": not violations, "mirrors": mirrors, "violations": violations}


def main() -> int:
    result = check()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
