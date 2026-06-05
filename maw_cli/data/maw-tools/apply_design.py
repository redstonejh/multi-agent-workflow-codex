#!/usr/bin/env python3
"""Apply reusable MAW design-language packs to web projects."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "packs"
MARKER_START = "<!-- MAW-DESIGN: liquid-glass start -->"
MARKER_END = "<!-- MAW-DESIGN: liquid-glass end -->"


def web_entrypoints(target: Path) -> list[Path]:
    if target.is_file() and target.suffix.lower() in {".html", ".htm"}:
        return [target]
    if not target.is_dir():
        return []
    ignored = {".git", "node_modules", "build", "dist", ".venv", "venv"}
    return sorted(path for path in target.rglob("*.htm*") if not (set(path.parts) & ignored))


def copy_kit(pack: Path, target: Path) -> Path:
    destination = (target if target.is_dir() else target.parent) / "assets" / "liquid-glass"
    destination.mkdir(parents=True, exist_ok=True)
    for source in sorted((pack / "kit").iterdir()):
        if source.is_file():
            shutil.copy2(source, destination / source.name)
    return destination


def relative_href(html: Path, asset: Path) -> str:
    return Path(*asset.relative_to(html.parent).parts).as_posix() if asset.is_relative_to(html.parent) else asset.as_posix()


def wire_html(html: Path, kit_dir: Path) -> bool:
    text = html.read_text(encoding="utf-8")
    block = "\n".join(
        [
            MARKER_START,
            f'<link rel="stylesheet" href="{relative_href(html, kit_dir / "glass-kit.css")}">',
            f'<script defer src="{relative_href(html, kit_dir / "background.js")}"></script>',
            f'<script defer src="{relative_href(html, kit_dir / "liquid-glass-webgl.js")}"></script>',
            MARKER_END,
        ]
    )
    if MARKER_START in text and MARKER_END in text:
        before, rest = text.split(MARKER_START, 1)
        _old, after = rest.split(MARKER_END, 1)
        updated = before + block + after
    elif "</head>" in text:
        updated = text.replace("</head>", block + "\n</head>", 1)
    else:
        updated = block + "\n" + text
    changed = updated != text
    if changed:
        html.write_text(updated, encoding="utf-8")
    return changed


def apply(pack_name: str, target: Path, photo: str, surface_class: str) -> dict[str, object]:
    if pack_name != "liquid-glass":
        return {"passed": False, "status": "NEEDS-HUMAN", "errors": [f"unknown design pack: {pack_name}"]}
    pack = PACKS / pack_name
    entries = web_entrypoints(target)
    if not entries:
        return {"passed": False, "status": "NEEDS-HUMAN", "errors": [f"target is not a detected web/HTML project: {target}"]}
    kit_dir = copy_kit(pack, target)
    changed = [str(path) for path in entries if wire_html(path, kit_dir)]
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    return {
        "passed": True,
        "pack": pack_name,
        "target": str(target),
        "kit_dir": str(kit_dir),
        "wired_html": [str(path) for path in entries],
        "changed_html": changed,
        "photo_selector": photo,
        "surface_class": surface_class,
        "api": manifest.get("api", {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a MAW design-language pack to a web target.")
    parser.add_argument("pack")
    parser.add_argument("target")
    parser.add_argument("--photo", default="[data-liquid-glass-photo]")
    parser.add_argument("--surface-class", default="glass")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = apply(args.pack, Path(args.target), args.photo, args.surface_class)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
