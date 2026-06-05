#!/usr/bin/env python3
"""Deterministic design-pack parity checks for adopted glass CSS."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "packs" / "liquid-glass"
CLASSES = (".glass", ".glass-strong", ".glass-control", ".glass-popover")
PSEUDOS = ("", "::before")
PROPERTIES = (
    "background",
    "backdrop-filter",
    "-webkit-backdrop-filter",
    "border",
    "border-color",
    "box-shadow",
    "filter",
    "opacity",
)
CSS_IMPORT_RE = re.compile(r"@import\s+url\([\"']?(.*?)[\"']?\)\s*;")
RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]+)\}", re.S)
COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
VAR_RE = re.compile(r"var\((--[A-Za-z0-9_-]+)(?:,\s*([^)]+))?\)")
TOKEN_RE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;]+);")
BG_RE = re.compile(r'html\[data-background="([^"]+)"\]\s*\{(?P<body>[^{}]+)\}', re.S)


def sha256_dir(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def strip_comments(text: str) -> str:
    return COMMENT_RE.sub("", text)


def declarations(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        result[name.strip()] = " ".join(value.split())
    return result


def read_css_graph(entry: Path, seen: set[Path] | None = None) -> str:
    seen = seen or set()
    entry = entry.resolve()
    if entry in seen or not entry.is_file():
        return ""
    seen.add(entry)
    text = entry.read_text(encoding="utf-8")
    chunks = []
    for match in CSS_IMPORT_RE.finditer(text):
        chunks.append(read_css_graph((entry.parent / match.group(1)).resolve(), seen))
    chunks.append(CSS_IMPORT_RE.sub("", text))
    return "\n".join(chunks)


def palette_names(tokens_css: str) -> list[str]:
    names = [match.group(1) for match in BG_RE.finditer(tokens_css)]
    return ["default", *names]


def root_tokens(tokens_css: str, palette: str) -> dict[str, str]:
    stripped = strip_comments(tokens_css)
    root_match = re.search(r":root\s*\{(?P<body>.*?)\}", stripped, re.S)
    tokens = {match.group(1): " ".join(match.group(2).split()) for match in TOKEN_RE.finditer(root_match.group("body") if root_match else "")}
    if palette != "default":
        for match in BG_RE.finditer(stripped):
            if match.group(1) == palette:
                tokens.update({item.group(1): " ".join(item.group(2).split()) for item in TOKEN_RE.finditer(match.group("body"))})
                break
    return tokens


def resolve_vars(value: str, tokens: dict[str, str]) -> str:
    previous = None
    current = value
    for _ in range(12):
        if current == previous:
            break
        previous = current
        current = VAR_RE.sub(lambda m: tokens.get(m.group(1), (m.group(2) or "")).strip(), current)
    return " ".join(current.split())


def selector_matches(selector: str, cls: str, pseudo: str, photo: bool) -> bool:
    selector = " ".join(selector.strip().split())
    if not selector:
        return False
    if "has-photo-background" in selector and not photo:
        return False
    if "has-photo-background" not in selector and photo and selector.startswith("body.has-photo-background"):
        return False
    base = cls + pseudo
    if pseudo:
        return re.search(rf"(?<![\w-]){re.escape(base)}(?![\w-])", selector) is not None
    if "::" in selector:
        return False
    return re.search(rf"(?<![\w-]){re.escape(cls)}(?![\w-])", selector) is not None


def computed_surfaces(kit_dir: Path, palette: str) -> dict[str, dict[str, str]]:
    css = read_css_graph(kit_dir / "glass-kit.css")
    tokens_css = (kit_dir / "tokens.css").read_text(encoding="utf-8")
    tokens = root_tokens(tokens_css, palette)
    photo = palette.startswith("photo-") or palette == "solar-system"
    surfaces: dict[str, dict[str, str]] = {}
    for cls in CLASSES:
        for pseudo in PSEUDOS:
            key = cls + pseudo
            props: dict[str, str] = {}
            for rule in RULE_RE.finditer(strip_comments(css)):
                selectors = [item.strip() for item in rule.group("selectors").split(",")]
                if any(selector_matches(selector, cls, pseudo, photo) for selector in selectors):
                    for name, value in declarations(rule.group("body")).items():
                        if name in PROPERTIES:
                            props[name] = resolve_vars(value, tokens)
            surfaces[key] = props
    return surfaces


def make_reference(kit_dir: Path) -> dict[str, Any]:
    tokens_css = (kit_dir / "tokens.css").read_text(encoding="utf-8")
    return {
        "schema_version": 1,
        "pack": "liquid-glass",
        "kit_sha256": sha256_dir(kit_dir),
        "properties": list(PROPERTIES),
        "palettes": {palette: computed_surfaces(kit_dir, palette) for palette in palette_names(tokens_css)},
    }


def find_kit(target: Path) -> Path | None:
    candidates = [
        target / "assets" / "liquid-glass",
        target.parent / "assets" / "liquid-glass" if target.is_file() else target / "liquid-glass",
        target,
    ]
    for candidate in candidates:
        if (candidate / "glass-kit.css").is_file() and (candidate / "tokens.css").is_file():
            return candidate
    return None


def compare(reference: dict[str, Any], kit_dir: Path) -> dict[str, Any]:
    diffs: list[dict[str, str]] = []
    for palette, expected_surfaces in reference.get("palettes", {}).items():
        actual_surfaces = computed_surfaces(kit_dir, palette)
        for surface, expected_props in expected_surfaces.items():
            actual_props = actual_surfaces.get(surface, {})
            for prop, expected in expected_props.items():
                actual = actual_props.get(prop, "")
                if actual != expected:
                    diffs.append({"palette": palette, "surface": surface, "property": prop, "expected": expected, "actual": actual})
    return {
        "check": "design_parity",
        "pack": "liquid-glass",
        "target_kit": str(kit_dir),
        "reference_kit_sha256": reference.get("kit_sha256"),
        "target_kit_sha256": sha256_dir(kit_dir),
        "diff_count": len(diffs),
        "diffs": diffs[:100],
        "passed": not diffs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare adopted liquid-glass CSS against the frozen reference.")
    parser.add_argument("target", nargs="?", help="target project or liquid-glass kit directory")
    parser.add_argument("--reference", default=str(PACK / "reference" / "reference-render.json"))
    parser.add_argument("--make-reference", action="store_true")
    parser.add_argument("--kit", default=str(PACK / "kit"))
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.make_reference:
        result = make_reference(Path(args.kit))
    else:
        if not args.target:
            raise SystemExit("target is required unless --make-reference is used")
        kit = find_kit(Path(args.target))
        if kit is None:
            result = {"check": "design_parity", "passed": False, "status": "NEEDS-HUMAN", "errors": [f"liquid-glass kit not found in target: {args.target}"]}
        else:
            reference = json.loads(Path(args.reference).read_text(encoding="utf-8"))
            result = compare(reference, kit)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("passed") is True or args.make_reference else 1


if __name__ == "__main__":
    raise SystemExit(main())
