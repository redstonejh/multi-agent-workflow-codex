#!/usr/bin/env python3
"""Compatibility wrapper for the MAW CLI.

Installed usage provides the `maw` console script. Local checkout usage can
continue to run `python maw.py ...`.
"""
from __future__ import annotations

from maw_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
