#!/usr/bin/env python3
"""Emit normalized MAW code-graph JSON for HTML and CSS using stdlib parsers."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import web_checks


LOCAL_ASSET_TAGS = {
    "script": ("src",),
    "link": ("href",),
    "img": ("src",),
    "source": ("src", "srcset"),
    "iframe": ("src",),
    "form": ("action",),
}
TEMPLATE_VAR_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*}}|{%\s*(?:url|static)\s+['\"]([^'\"]+)['\"]")
ROUTE_RE = re.compile(r"\b(?:url_for|reverse)\(['\"]([^'\"]+)['\"]")


def emit(result: dict[str, Any], output: str | None) -> int:
    text = json.dumps(result, indent=2, sort_keys=True)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result.get("passed", True) else 1


def rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    clean = re.sub(r"[^A-Za-z0-9_.:-]+", "_", value).strip("_")[:40] or digest
    return f"{prefix}:{clean}:{digest}"


def iter_files(root: Path, suffixes: set[str]) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in suffixes else []
    ignored = {".git", "__pycache__", ".venv", "venv", "node_modules", "build", "dist"}
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes and not (set(path.parts) & ignored))


class GraphHTMLParser(HTMLParser):
    def __init__(self, module_id: str, rel: str) -> None:
        super().__init__(convert_charrefs=True)
        self.module_id = module_id
        self.rel = rel
        self.symbols: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    def add_symbol(self, symbol_id: str, name: str, kind: str, line: int, **extra: Any) -> None:
        if symbol_id in self._seen:
            return
        self._seen.add(symbol_id)
        item = {
            "id": symbol_id,
            "module_id": self.module_id,
            "name": name,
            "qualname": name,
            "kind": kind,
            "exported": True,
            "location": {"path": self.rel, "line": line, "end_line": line},
        }
        item.update(extra)
        self.symbols.append(item)

    def edge(self, kind: str, to: str, line: int, **metadata: Any) -> None:
        item: dict[str, Any] = {"type": kind, "from": self.module_id, "to": to, "location": {"path": self.rel, "line": line}}
        if metadata:
            item["metadata"] = metadata
        self.edges.append(item)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line = self.getpos()[0]
        attr = {name.lower(): "" if value is None else value for name, value in attrs}
        element_id = attr.get("id", "").strip()
        if element_id:
            sid = stable_id("dom", f"#{element_id}")
            self.add_symbol(sid, f"#{element_id}", "dom", line, selector=f"#{element_id}")
            self.edge("dom_ref", sid, line, selector=f"#{element_id}")
        for class_name in attr.get("class", "").split():
            sid = stable_id("dom", f".{class_name}")
            self.add_symbol(sid, f".{class_name}", "dom", line, selector=f".{class_name}")
            self.edge("dom_ref", sid, line, selector=f".{class_name}")
        for name in ("name", "data-testid", "data-test", "data-action"):
            value = attr.get(name, "").strip()
            if value:
                sid = stable_id("dom", f"[{name}={value}]")
                self.add_symbol(sid, f"[{name}={value}]", "dom", line, selector=f"[{name}={value}]")
                self.edge("dom_ref", sid, line, selector=f"[{name}={value}]", attribute=name)
        if tag.lower() in {"input", "textarea", "select"} and attr.get("name"):
            field = attr["name"].strip()
            sid = stable_id("form", field)
            self.add_symbol(sid, field, "form_field", line)
            self.edge("template_var", sid, line, form_field=field)
        for asset_attr in LOCAL_ASSET_TAGS.get(tag.lower(), ()):
            value = attr.get(asset_attr, "").strip()
            if not value:
                continue
            for ref in value.split(",") if asset_attr == "srcset" else [value]:
                clean = ref.strip().split()[0]
                sid = stable_id("asset", clean)
                self.add_symbol(sid, clean, "asset", line)
                self.edge("asset_ref", sid, line, attr=asset_attr, tag=tag.lower())


def template_edges(text: str, module_id: str, rel: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in TEMPLATE_VAR_RE.finditer(text):
        value = match.group(1) or match.group(2) or ""
        if not value:
            continue
        sid = stable_id("template", value)
        if sid not in seen:
            seen.add(sid)
            line = text[: match.start()].count("\n") + 1
            symbols.append({"id": sid, "module_id": module_id, "name": value, "qualname": value, "kind": "template_var", "exported": True, "location": {"path": rel, "line": line, "end_line": line}})
        edges.append({"type": "template_var", "from": module_id, "to": sid, "location": {"path": rel, "line": text[: match.start()].count("\n") + 1}})
    for match in ROUTE_RE.finditer(text):
        value = match.group(1)
        sid = stable_id("route", value)
        line = text[: match.start()].count("\n") + 1
        if sid not in seen:
            seen.add(sid)
            symbols.append({"id": sid, "module_id": module_id, "name": value, "qualname": value, "kind": "route", "exported": True, "location": {"path": rel, "line": line, "end_line": line}})
        edges.append({"type": "route_ref", "from": module_id, "to": sid, "location": {"path": rel, "line": line}})
    return symbols, edges


def css_graph(root: Path, path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    rel = rel_path(root, path)
    mid = f"css:{rel}"
    module = {"id": mid, "path": rel, "language": "css"}
    symbols: list[dict[str, Any]] = [{"id": mid, "module_id": mid, "name": rel, "qualname": rel, "kind": "module", "exported": True, "location": {"path": rel, "line": 1, "end_line": 1}}]
    edges: list[dict[str, Any]] = []
    for rule in web_checks.parse_css_rules(path):
        for selector in rule["selectors"]:
            sid = stable_id("css", selector)
            line = int(rule["declarations"][0]["line"]) if rule["declarations"] else 1
            tokens = re.findall(r"[#.][A-Za-z0-9_-]+|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_-]*", selector)
            symbols.append({"id": sid, "module_id": mid, "name": selector, "qualname": selector, "kind": "css_selector", "exported": True, "location": {"path": rel, "line": line, "end_line": line}, "token_signature": tokens})
            edges.append({"type": "css_ref", "from": mid, "to": sid, "location": {"path": rel, "line": line}, "metadata": {"selector": selector}})
    return module, symbols, edges


def graph_for(root: Path, lang: str = "auto", entrypoints: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    suffixes = {".html", ".htm", ".jinja", ".jinja2", ".j2", ".css"} if lang == "auto" else ({".css"} if lang == "css" else {".html", ".htm", ".jinja", ".jinja2", ".j2"})
    modules: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for path in iter_files(root, suffixes):
        rel = rel_path(root, path)
        if path.suffix.lower() == ".css":
            module, css_symbols, css_edges = css_graph(root, path)
            modules.append(module)
            symbols.extend(css_symbols)
            edges.extend(css_edges)
            continue
        mid = f"html:{rel}"
        modules.append({"id": mid, "path": rel, "language": "html"})
        symbols.append({"id": mid, "module_id": mid, "name": rel, "qualname": rel, "kind": "module", "exported": True, "location": {"path": rel, "line": 1, "end_line": 1}})
        text = path.read_text(encoding="utf-8")
        parser = GraphHTMLParser(mid, rel)
        parser.feed(text)
        parser.close()
        template_symbols, template_ref_edges = template_edges(text, mid, rel)
        symbols.extend(parser.symbols)
        symbols.extend(template_symbols)
        edges.extend(parser.edges)
        edges.extend(template_ref_edges)
    if entrypoints is None:
        entrypoints = sorted(symbol["id"] for symbol in symbols if symbol.get("kind") in {"dom", "css_selector", "route"} and symbol.get("exported") is True)
    return {
        "schema_version": 1,
        "language": "html-css" if lang == "auto" else lang,
        "root": str(root),
        "modules": sorted(modules, key=lambda item: item["id"]),
        "symbols": sorted(symbols, key=lambda item: item["id"]),
        "edges": sorted(edges, key=lambda item: (item["type"], item["from"], item["to"], item.get("location", {}).get("line", 0))),
        "entrypoints": sorted(entrypoints),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit normalized HTML/CSS code graph JSON.")
    parser.add_argument("path", help="HTML/CSS file or project root")
    parser.add_argument("--lang", choices=["auto", "html", "css"], default="auto")
    parser.add_argument("--entrypoint", action="append", dest="entrypoints")
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = graph_for(Path(args.path), args.lang, args.entrypoints)
        result["passed"] = True
    except Exception as exc:
        result = {"schema_version": 1, "passed": False, "status": "NEEDS-HUMAN", "errors": [str(exc)], "modules": [], "symbols": [], "edges": [], "entrypoints": []}
    return emit(result, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
