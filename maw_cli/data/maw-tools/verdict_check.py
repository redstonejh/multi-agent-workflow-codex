#!/usr/bin/env python3
"""Verify run.md declares the same final verdict as acceptance-result.json."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import anti_gaming_check
import salvage_check


ACCEPTANCE_RESULT = "acceptance-result.json"
VALID_VERDICTS = {"SHIP", "NO-SHIP", "NEEDS-HUMAN"}
VERDICT_RE = r"(NO-SHIP|NEEDS-HUMAN|SHIP)"
EXPLICIT_VERDICT_RE = re.compile(rf"(?m)^\s*(?:Final verdict|Verdict|Acceptance verdict|Acceptance result)\s*:\s*{VERDICT_RE}\b")
LEADING_VERDICT_RE = re.compile(rf"(?m)^\s*{VERDICT_RE}(?:\s*$|[\s:.-])")
FINAL_SUMMARY_RE = re.compile(r"(?m)^## Final result summary\s*$")
SECTION_RE = re.compile(r"(?m)^## ")


def violation(kind: str, message: str, **extra: Any) -> dict[str, Any]:
    item = {"type": kind, "message": message}
    item.update(extra)
    return item


def acceptance_artifact_path(run_dir: Path) -> Path:
    return run_dir / "artifacts" / ACCEPTANCE_RESULT


def final_summary(text: str) -> str:
    match = FINAL_SUMMARY_RE.search(text)
    if not match:
        return text
    start = match.end()
    next_section = SECTION_RE.search(text, start)
    end = next_section.start() if next_section else len(text)
    return text[start:end]


def unique_verdicts(matches: list[str]) -> list[str]:
    result: list[str] = []
    for match in matches:
        if match not in result:
            result.append(match)
    return result


def extract_declared_verdict(text: str) -> tuple[str | None, list[str]]:
    search_areas = [final_summary(text), text]
    for area in search_areas:
        explicit = unique_verdicts([match.group(1) for match in EXPLICIT_VERDICT_RE.finditer(area)])
        if len(explicit) == 1:
            return explicit[0], explicit
        if len(explicit) > 1:
            return None, explicit

        leading = unique_verdicts([match.group(1) for match in LEADING_VERDICT_RE.finditer(area)])
        if len(leading) == 1:
            return leading[0], leading
        if len(leading) > 1:
            return None, leading
    return None, []


def load_artifact_verdict(path: Path) -> tuple[str | None, list[dict[str, Any]]]:
    if not path.is_file():
        return None, [violation("missing_acceptance_artifact", f"missing acceptance artifact: {path}", artifact=str(path))]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [violation("invalid_acceptance_artifact", f"invalid acceptance artifact JSON: {exc}", artifact=str(path))]
    except OSError as exc:
        return None, [violation("read_error", f"could not read acceptance artifact: {exc}", artifact=str(path))]
    if not isinstance(data, dict):
        return None, [violation("invalid_acceptance_artifact", "acceptance artifact must be a JSON object", artifact=str(path))]
    verdict = data.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        return None, [violation("missing_artifact_verdict", "acceptance artifact is missing a verdict", artifact=str(path))]
    if verdict not in VALID_VERDICTS:
        return None, [violation("invalid_artifact_verdict", f"invalid acceptance artifact verdict: {verdict}", artifact=str(path), artifact_verdict=verdict)]
    return verdict, []


def load_run_verdict(path: Path) -> tuple[str | None, list[dict[str, Any]]]:
    if not path.is_file():
        return None, [violation("missing_run_md", f"missing run.md: {path}", run_md=str(path))]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [violation("read_error", f"could not read run.md: {exc}", run_md=str(path))]
    verdict, candidates = extract_declared_verdict(text)
    if verdict is None and candidates:
        return None, [
            violation(
                "ambiguous_declared_verdict",
                "run.md declares multiple final verdicts",
                run_md=str(path),
                run_verdicts=candidates,
            )
        ]
    if verdict is None:
        return None, [violation("missing_declared_verdict", "run.md does not declare a final verdict", run_md=str(path))]
    return verdict, []


def check_run(run_dir: Path) -> dict[str, Any]:
    artifact_path = acceptance_artifact_path(run_dir)
    run_md = run_dir / "run.md"
    artifact_verdict, artifact_errors = load_artifact_verdict(artifact_path)
    run_verdict, run_errors = load_run_verdict(run_md)
    violations = [*artifact_errors, *run_errors]

    if artifact_verdict is not None and run_verdict is not None and artifact_verdict != run_verdict:
        violations.append(
            violation(
                "verdict_mismatch",
                f"run.md final verdict {run_verdict} does not match acceptance artifact verdict {artifact_verdict}",
                artifact_verdict=artifact_verdict,
                run_verdict=run_verdict,
            )
        )

    anti_gaming = anti_gaming_check.check_run(run_dir)
    salvage_gates = salvage_check.check_run(run_dir)
    if not anti_gaming.get("passed"):
        violations.append(
            violation(
                "anti_gaming_hard_gates_failed",
                "anti-gaming hard gates failed; final verdict cannot be SHIP",
                anti_gaming=anti_gaming,
            )
        )
    if artifact_verdict == "SHIP" and not anti_gaming.get("passed"):
        violations.append(
            violation(
                "ship_with_failed_anti_gaming_gates",
                "acceptance artifact declares SHIP despite failed anti-gaming hard gates",
                artifact_verdict=artifact_verdict,
            )
        )
    if not salvage_gates.get("passed"):
        violations.append(
            violation(
                "salvage_hard_gates_failed",
                "salvage hard gates failed; final verdict cannot be SHIP",
                salvage_gates=salvage_gates,
            )
        )
    if artifact_verdict == "SHIP" and not salvage_gates.get("passed"):
        violations.append(
            violation(
                "ship_with_failed_salvage_gates",
                "acceptance artifact declares SHIP despite failed salvage hard gates",
                artifact_verdict=artifact_verdict,
            )
        )

    return {
        "check": "final_verdict_matches_acceptance_artifact",
        "run": str(run_dir),
        "artifact": str(artifact_path),
        "artifact_verdict": artifact_verdict,
        "run_verdict": run_verdict,
        "anti_gaming": anti_gaming,
        "salvage_gates": salvage_gates,
        "passed": not violations,
        "violations": violations,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify run.md final verdict matches artifacts/acceptance-result.json.")
    parser.add_argument("run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = check_run(Path(args.run))
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
