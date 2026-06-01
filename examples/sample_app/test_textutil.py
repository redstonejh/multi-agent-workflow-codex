"""Plain-stdlib tests for textutil — runnable with `python test_textutil.py`.

Exits 0 if all tests pass, 1 otherwise (so maw-tools/checks.py `test` can gate
on it without needing pytest installed).
"""
import sys

from textutil import normalize_whitespace

CASES = [
    ("  hello\t world\n", "hello world"),
    ("already clean", "already clean"),
    ("\n\n  lots   of\tgaps  ", "lots of gaps"),
    ("", ""),
    ("   ", ""),
    ("one", "one"),
]


def run() -> int:
    failures = []
    for raw, expected in CASES:
        try:
            got = normalize_whitespace(raw)
        except Exception as e:  # noqa: BLE001 - a raised exception is a test failure
            failures.append(f"{raw!r}: raised {e!r}")
            continue
        if got != expected:
            failures.append(f"{raw!r}: expected {expected!r}, got {got!r}")

    if failures:
        print(f"FAIL — {len(failures)}/{len(CASES)} cases failed:")
        for f in failures:
            print("  -", f)
        return 1
    print(f"PASS — all {len(CASES)} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(run())
