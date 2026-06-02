#!/usr/bin/env python3
"""Deterministic stdlib-only checks for front-end/UI MAW workflows."""
from __future__ import annotations

import argparse
import json
import math
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urlparse


VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
CONTROL_TAGS = {"button", "input", "select", "textarea"}
LOCAL_ASSET_ATTRS = {
    "audio": ("src",),
    "embed": ("src",),
    "iframe": ("src",),
    "img": ("src",),
    "link": ("href",),
    "script": ("src",),
    "source": ("src", "srcset"),
    "track": ("src",),
    "video": ("poster", "src"),
}
URL_RE = re.compile(r"url\((?P<quote>['\"]?)(?P<url>[^)'\"]+)(?P=quote)\)")
HEX_RE = re.compile(r"^#?(?P<value>[0-9a-fA-F]{6})$")
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
CSS_RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}", re.DOTALL)
CSS_DECL_RE = re.compile(r"(?P<property>[-_a-zA-Z][-_a-zA-Z0-9]*)\s*:\s*(?P<value>[^;]+)")
DEFAULT_ALLOWED_CSS_VALUES = {
    "0",
    "auto",
    "border-box",
    "bold",
    "inherit",
    "initial",
    "none",
    "normal",
    "solid",
    "transparent",
    "unset",
}


def emit(result: dict) -> int:
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("passed") else 1


def is_external(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme or parsed.netloc or value.startswith(("mailto:", "tel:", "data:", "javascript:")))


def clean_local_ref(value: str) -> str:
    path, _fragment = urldefrag(value.strip())
    return path


def parse_attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {name.lower(): "" if value is None else value for name, value in attrs}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_hex(value: str) -> str:
    match = HEX_RE.match(value)
    if not match:
        raise ValueError(f"invalid hex color: {value}")
    return "#" + match.group("value").lower()


def normalize_css_value(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip()).lower()
    if HEX_RE.match(text):
        return normalize_hex(text)
    return text


def strip_css_comments(text: str) -> str:
    return CSS_COMMENT_RE.sub("", text)


def parse_css_rules(path: Path) -> list[dict]:
    text = strip_css_comments(read_text(path))
    rules: list[dict] = []
    for match in CSS_RULE_RE.finditer(text):
        selectors = [selector.strip() for selector in match.group("selectors").split(",") if selector.strip()]
        declarations = []
        for decl in CSS_DECL_RE.finditer(match.group("body")):
            declarations.append(
                {
                    "property": decl.group("property").strip().lower(),
                    "value": decl.group("value").strip(),
                    "line": text[: match.start()].count("\n") + 1,
                }
            )
        rules.append({"selectors": selectors, "declarations": declarations, "source_file": str(path)})
    return rules


def css_property_value(path: Path, selector: str, property_name: str) -> str | None:
    wanted = property_name.strip().lower()
    value: str | None = None
    for rule in parse_css_rules(path):
        if selector in rule["selectors"]:
            for decl in rule["declarations"]:
                if decl["property"] == wanted:
                    value = decl["value"]
    return value


def flatten_token_values(value: object) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            values.update(flatten_token_values(item))
    elif isinstance(value, list):
        for item in value:
            values.update(flatten_token_values(item))
    elif isinstance(value, (str, int, float)):
        values.add(normalize_css_value(str(value)))
    return values


def token_value_allowed(value: str, allowed: set[str]) -> bool:
    normalized = normalize_css_value(value)
    if normalized in allowed:
        return True
    if normalized.startswith("var("):
        token_name = normalized[4:-1].strip()
        return token_name in allowed
    parts = [part for part in re.split(r"\s+", normalized) if part]
    return len(parts) > 1 and all(part in allowed for part in parts)


def relative_luminance(hex_color: str) -> float:
    color = normalize_hex(hex_color)[1:]
    values = [int(color[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    adjusted = []
    for value in values:
        if value <= 0.04045:
            adjusted.append(value / 12.92)
        else:
            adjusted.append(math.pow((value + 0.055) / 1.055, 2.4))
    return (0.2126 * adjusted[0]) + (0.7152 * adjusted[1]) + (0.0722 * adjusted[2])


def contrast_ratio(foreground: str, background: str) -> float:
    fg = relative_luminance(foreground)
    bg = relative_luminance(background)
    lighter = max(fg, bg)
    darker = min(fg, bg)
    return (lighter + 0.05) / (darker + 0.05)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict] = []
        self.stack: list[dict] = []
        self.unclosed: list[dict] = []
        self.duplicate_ids: list[dict] = []
        self.ids: dict[str, dict] = {}
        self.anchors: set[str] = set()
        self.labels_for: set[str] = set()
        self.open_labels = 0
        self.heading_levels: list[tuple[int, int]] = []
        self.html_lang = False
        self.title = False
        self.viewport = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        attr_map = parse_attrs(attrs)
        element = {
            "tag": name,
            "attrs": attr_map,
            "line": self.getpos()[0],
            "text": "",
            "wrapped_label": self.open_labels > 0,
        }
        self.elements.append(element)

        element_id = attr_map.get("id", "")
        if element_id:
            if element_id in self.ids:
                self.duplicate_ids.append({"id": element_id, "line": element["line"], "first_line": self.ids[element_id]["line"]})
            else:
                self.ids[element_id] = element
            self.anchors.add(element_id)

        anchor_name = attr_map.get("name", "")
        if name == "a" and anchor_name:
            self.anchors.add(anchor_name)

        if name == "label":
            self.open_labels += 1
            label_for = attr_map.get("for", "")
            if label_for:
                self.labels_for.add(label_for)

        if name == "html" and attr_map.get("lang", "").strip():
            self.html_lang = True
        if name == "title":
            self.title = True
        if name == "meta" and attr_map.get("name", "").lower() == "viewport":
            self.viewport = True
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            level = int(name[1])
            if 1 <= level <= 6:
                self.heading_levels.append((level, element["line"]))

        if name not in VOID_TAGS:
            self.stack.append(element)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name == "label" and self.open_labels > 0:
            self.open_labels -= 1
        if name in VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == name:
                unclosed = self.stack[index + 1 :]
                for element in unclosed:
                    self.unclosed.append({"tag": element["tag"], "line": element["line"]})
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1]["text"] += data

    def close(self) -> None:
        super().close()
        for element in self.stack:
            self.unclosed.append({"tag": element["tag"], "line": element["line"]})


def parse_page(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(read_text(path))
    parser.close()
    return parser


def cmd_contrast(args: argparse.Namespace) -> int:
    try:
        ratio = contrast_ratio(args.foreground, args.background)
    except ValueError as exc:
        return emit({"check": "contrast", "passed": False, "errors": [str(exc)]})
    threshold = 3.0 if args.large else 4.5
    return emit(
        {
            "check": "contrast",
            "foreground": normalize_hex(args.foreground),
            "background": normalize_hex(args.background),
            "large": args.large,
            "ratio": round(ratio, 6),
            "threshold": threshold,
            "passed": ratio >= threshold,
        }
    )


def a11y_violations(path: Path) -> list[dict]:
    page = parse_page(path)
    violations: list[dict] = []
    if not page.html_lang:
        violations.append({"type": "missing_html_lang", "message": "html element is missing lang"})
    if not page.title:
        violations.append({"type": "missing_title", "message": "document is missing title"})
    if not page.viewport:
        violations.append({"type": "missing_viewport", "message": "document is missing viewport meta"})

    for element in page.elements:
        tag = element["tag"]
        attrs = element["attrs"]
        if tag == "img" and "alt" not in attrs:
            violations.append({"type": "img_missing_alt", "line": element["line"], "message": "img missing alt"})
        if tag in CONTROL_TAGS:
            input_type = attrs.get("type", "").lower()
            if tag == "input" and input_type == "hidden":
                continue
            has_name = bool(
                attrs.get("aria-label", "").strip()
                or attrs.get("aria-labelledby", "").strip()
                or attrs.get("title", "").strip()
                or element.get("wrapped_label")
            )
            element_id = attrs.get("id", "")
            if element_id and element_id in page.labels_for:
                has_name = True
            if tag == "button" and element.get("text", "").strip():
                has_name = True
            if not has_name:
                violations.append({"type": "control_missing_label", "tag": tag, "line": element["line"], "message": f"{tag} missing accessible label"})

    previous = 0
    for level, line in page.heading_levels:
        if previous and level > previous + 1:
            violations.append({"type": "skipped_heading_level", "line": line, "message": f"heading jumps from h{previous} to h{level}"})
        previous = level
    return violations


def cmd_a11y(args: argparse.Namespace) -> int:
    path = Path(args.html)
    violations = a11y_violations(path)
    return emit({"check": "a11y", "file": str(path), "passed": not violations, "violation_count": len(violations), "violations": violations})


def html_asset_refs(path: Path, page: PageParser) -> list[str]:
    refs: list[str] = []
    for element in page.elements:
        attrs = element["attrs"]
        for attr in LOCAL_ASSET_ATTRS.get(element["tag"], ()):
            value = attrs.get(attr, "").strip()
            if not value:
                continue
            if attr == "srcset":
                for item in value.split(","):
                    refs.append(item.strip().split()[0])
            else:
                refs.append(value)
        style = attrs.get("style", "")
        for match in URL_RE.finditer(style):
            refs.append(match.group("url").strip())
    for match in URL_RE.finditer(read_text(path)):
        refs.append(match.group("url").strip())
    return refs


def css_asset_refs(path: Path) -> list[str]:
    refs: list[str] = []
    if path.suffix.lower() != ".css":
        return refs
    for match in URL_RE.finditer(read_text(path)):
        refs.append(match.group("url").strip())
    return refs


def resolved_asset_paths(html_path: Path) -> list[Path]:
    page = parse_page(html_path)
    refs = html_asset_refs(html_path, page)
    paths: list[Path] = []
    seen: set[Path] = set()
    for ref in refs:
        local = clean_local_ref(ref)
        if not local or local.startswith("#") or is_external(local):
            continue
        candidate = (html_path.parent / local).resolve()
        if candidate not in seen:
            seen.add(candidate)
            paths.append(candidate)
        if candidate.is_file() and candidate.suffix.lower() == ".css":
            for css_ref in css_asset_refs(candidate):
                css_local = clean_local_ref(css_ref)
                if not css_local or is_external(css_local):
                    continue
                css_candidate = (candidate.parent / css_local).resolve()
                if css_candidate not in seen:
                    seen.add(css_candidate)
                    paths.append(css_candidate)
    return paths


def cmd_budget(args: argparse.Namespace) -> int:
    html_path = Path(args.html)
    page = parse_page(html_path)
    files = [html_path] + [path for path in resolved_asset_paths(html_path) if path.is_file()]
    file_bytes = [{"path": str(path), "bytes": path.stat().st_size} for path in files]
    total_bytes = sum(item["bytes"] for item in file_bytes)
    asset_count = max(0, len(files) - 1)
    violations = []
    if total_bytes > args.max_bytes:
        violations.append({"type": "byte_budget_exceeded", "actual": total_bytes, "limit": args.max_bytes})
    if len(page.elements) > args.max_elements:
        violations.append({"type": "element_budget_exceeded", "actual": len(page.elements), "limit": args.max_elements})
    if asset_count > args.max_assets:
        violations.append({"type": "asset_budget_exceeded", "actual": asset_count, "limit": args.max_assets})
    return emit(
        {
            "check": "budget",
            "file": str(html_path),
            "passed": not violations,
            "total_bytes": total_bytes,
            "element_count": len(page.elements),
            "asset_count": asset_count,
            "limits": {"max_bytes": args.max_bytes, "max_elements": args.max_elements, "max_assets": args.max_assets},
            "files": file_bytes,
            "violations": violations,
        }
    )


def cmd_links(args: argparse.Namespace) -> int:
    html_path = Path(args.html)
    page = parse_page(html_path)
    violations: list[dict] = []
    refs: list[dict] = []
    for element in page.elements:
        attrs = element["attrs"]
        href = attrs.get("href", "").strip()
        if href and not is_external(href):
            local, fragment = urldefrag(href)
            if local:
                target = html_path.parent / local
                refs.append({"type": "internal_link", "target": str(target)})
                if not target.is_file():
                    violations.append({"type": "missing_internal_link", "line": element["line"], "target": href})
            if fragment:
                target_page = html_path if not local else html_path.parent / local
                if target_page == html_path and fragment not in page.anchors:
                    violations.append({"type": "missing_anchor", "line": element["line"], "target": href})

    for ref in html_asset_refs(html_path, page):
        local = clean_local_ref(ref)
        if not local or local.startswith("#") or is_external(local):
            continue
        target = html_path.parent / local
        refs.append({"type": "asset", "target": str(target)})
        if not target.is_file():
            violations.append({"type": "missing_asset", "target": ref})

    for asset in resolved_asset_paths(html_path):
        if asset.is_file():
            for ref in css_asset_refs(asset):
                local = clean_local_ref(ref)
                if not local or is_external(local):
                    continue
                target = asset.parent / local
                refs.append({"type": "css_asset", "target": str(target)})
                if not target.is_file():
                    violations.append({"type": "missing_css_asset", "source": str(asset), "target": ref})

    return emit({"check": "links", "file": str(html_path), "passed": not violations, "reference_count": len(refs), "violations": violations})


def cmd_markup(args: argparse.Namespace) -> int:
    path = Path(args.html)
    page = parse_page(path)
    violations = []
    violations.extend({"type": "unclosed_tag", **item} for item in page.unclosed)
    violations.extend({"type": "duplicate_id", **item} for item in page.duplicate_ids)
    return emit({"check": "markup", "file": str(path), "passed": not violations, "violation_count": len(violations), "violations": violations})


def cmd_style(args: argparse.Namespace) -> int:
    path = Path(args.css)
    value = css_property_value(path, args.selector, args.property)
    reason = "value found" if value is not None else "selector/property not found"
    return emit(
        {
            "check": "style",
            "passed": value is not None,
            "selector": args.selector,
            "property": args.property,
            "value": value,
            "source_file": str(path),
            "reason": reason,
        }
    )


def target_value(path: Path, selector: str | None, property_name: str | None) -> str | None:
    if selector or property_name:
        if not selector or not property_name:
            return None
        return css_property_value(path, selector, property_name)
    return read_text(path)


def cmd_changed(args: argparse.Namespace) -> int:
    before_path = Path(args.before)
    after_path = Path(args.after)
    before = target_value(before_path, args.selector, args.property)
    after = target_value(after_path, args.selector, args.property)
    target = {
        "before_file": str(before_path),
        "after_file": str(after_path),
        "selector": args.selector,
        "property": args.property,
    }
    expected = args.expected
    passed = True
    reason = "target changed"
    if before is None:
        passed = False
        reason = "target not found in before snapshot"
    elif after is None:
        passed = False
        reason = "target not found in after file"
    elif before == after:
        passed = False
        reason = "target did not change"
    elif expected is not None and normalize_css_value(after) != normalize_css_value(expected):
        passed = False
        reason = "target changed to unexpected value"
    elif expected is not None:
        reason = "target changed to expected value"
    return emit({"check": "changed", "passed": passed, "target": target, "before": before, "after": after, "expected": expected, "reason": reason})


def cmd_tokens(args: argparse.Namespace) -> int:
    token_path = Path(args.token_file)
    token_data = json.loads(read_text(token_path))
    allowed = flatten_token_values(token_data) | DEFAULT_ALLOWED_CSS_VALUES
    drift_items: list[dict] = []
    css_files = [Path(path) for path in args.css_files]
    for css_file in css_files:
        for rule in parse_css_rules(css_file):
            for decl in rule["declarations"]:
                if not token_value_allowed(decl["value"], allowed):
                    drift_items.append(
                        {
                            "source_file": str(css_file),
                            "selectors": rule["selectors"],
                            "property": decl["property"],
                            "value": decl["value"],
                            "line": decl["line"],
                        }
                    )
    return emit(
        {
            "check": "tokens",
            "passed": not drift_items,
            "token_file": str(token_path),
            "css_files": [str(path) for path in css_files],
            "drift_count": len(drift_items),
            "drift_items": drift_items,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic front-end/UI checks.")
    sub = parser.add_subparsers(dest="command", required=True)

    contrast = sub.add_parser("contrast", help="check WCAG contrast ratio between two hex colors")
    contrast.add_argument("--foreground", required=True)
    contrast.add_argument("--background", required=True)
    contrast.add_argument("--large", action="store_true")
    contrast.set_defaults(func=cmd_contrast)

    a11y = sub.add_parser("a11y", help="check static HTML accessibility signals")
    a11y.add_argument("html")
    a11y.set_defaults(func=cmd_a11y)

    budget = sub.add_parser("budget", help="check local page byte, element, and asset budgets")
    budget.add_argument("html")
    budget.add_argument("--max-bytes", type=int, default=100_000)
    budget.add_argument("--max-elements", type=int, default=500)
    budget.add_argument("--max-assets", type=int, default=30)
    budget.set_defaults(func=cmd_budget)

    links = sub.add_parser("links", help="check internal links, anchors, and local assets")
    links.add_argument("html")
    links.set_defaults(func=cmd_links)

    markup = sub.add_parser("markup", help="check duplicate ids and unclosed tags")
    markup.add_argument("html")
    markup.set_defaults(func=cmd_markup)

    style = sub.add_parser("style", help="extract a selector/property value from CSS")
    style.add_argument("css")
    style.add_argument("--selector", required=True)
    style.add_argument("--property", required=True)
    style.set_defaults(func=cmd_style)

    changed = sub.add_parser("changed", help="verify a file or selector/property target changed from a snapshot")
    changed.add_argument("--before", required=True)
    changed.add_argument("--after", required=True)
    changed.add_argument("--selector")
    changed.add_argument("--property")
    changed.add_argument("--expected")
    changed.set_defaults(func=cmd_changed)

    tokens = sub.add_parser("tokens", help="check CSS values against a design token file")
    tokens.add_argument("--token-file", required=True)
    tokens.add_argument("css_files", nargs="+")
    tokens.set_defaults(func=cmd_tokens)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
