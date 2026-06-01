"""Tiny text utilities — the target of the worked /maw example.

`normalize_whitespace` starts unimplemented; the /maw run's worker implements it
so the tests in test_textutil.py pass. No third-party dependencies.
"""
from __future__ import annotations


def normalize_whitespace(text: str) -> str:
    """Collapse all runs of whitespace to single spaces and strip the ends.

    Example: "  hello\\t world\\n" -> "hello world"
    """
    return " ".join(text.split())
