#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

function parseArgs(argv) {
  const args = { entrypoints: [] };
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i];
    if (item === "--path") args.path = argv[++i];
    else if (item === "--lang") args.lang = argv[++i];
    else if (item === "--output") args.output = argv[++i];
    else if (item === "--entrypoints-json") args.entrypoints = JSON.parse(argv[++i] || "[]");
  }
  return args;
}

function emit(data, output) {
  const text = JSON.stringify(data, null, 2);
  if (output) {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, text + "\n", "utf8");
  }
  process.stdout.write(text + "\n");
  process.exit(data.passed === true ? 0 : 1);
}

let ts;
try {
  ts = require("typescript");
} catch (error) {
  emit({
    schema_version: 1,
    passed: false,
    status: "NEEDS-HUMAN",
    errors: ["The TypeScript compiler API package is required for JS/TS graph generation"],
    modules: [],
    symbols: [],
    edges: [],
    entrypoints: []
  }, parseArgs(process.argv.slice(2)).output);
}

const args = parseArgs(process.argv.slice(2));
const root = path.resolve(args.path || ".");
const exts = new Set([".js", ".jsx", ".ts", ".tsx"]);

function walk(target) {
  if (!fs.existsSync(target)) return [];
  const stat = fs.statSync(target);
  if (stat.isFile()) return exts.has(path.extname(target)) ? [target] : [];
  const ignored = new Set([".git", "node_modules", "dist", "build", "coverage"]);
  const result = [];
  for (const name of fs.readdirSync(target).sort()) {
    if (ignored.has(name)) continue;
    result.push(...walk(path.join(target, name)));
  }
  return result;
}

function rel(file) {
  return path.relative(root, file).replace(/\\/g, "/") || path.basename(file);
}

function moduleId(file) {
  return rel(file).replace(/\.[^.]+$/, "").replace(/\//g, ".");
}

function hashText(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

function tokens(text) {
  return (text.match(/[A-Za-z_$][A-Za-z0-9_$]*|\d+|==|!=|<=|>=|[-+*/%<>]/g) || []);
}

function loc(source, node, file) {
  const pos = source.getLineAndCharacterOfPosition(node.getStart(source));
  const end = source.getLineAndCharacterOfPosition(node.getEnd());
  return { path: rel(file), line: pos.line + 1, end_line: end.line + 1 };
}

function nodeName(node) {
  if (!node) return "";
  if (ts.isIdentifier(node)) return node.text;
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  return "";
}

function firstStringArg(node) {
  if (!node.arguments || !node.arguments.length) return "";
  const arg = node.arguments[0];
  if (ts.isStringLiteral(arg) || ts.isNoSubstitutionTemplateLiteral(arg)) return arg.text;
  return "";
}

function stableId(prefix, value) {
  const digest = hashText(value).slice(0, 12);
  const clean = String(value).replace(/[^A-Za-z0-9_.:-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || digest;
  return `${prefix}:${clean}:${digest}`;
}

function build() {
  const files = walk(root);
  const modules = [];
  const symbols = [];
  const edges = [];
  const known = new Map();

  for (const file of files) {
    const text = fs.readFileSync(file, "utf8");
    const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    const mid = moduleId(file);
    modules.push({ id: mid, path: rel(file), language: args.lang || "ts" });
    symbols.push({ id: mid, module_id: mid, name: mid.split(".").pop(), qualname: mid, kind: "module", exported: true, location: { path: rel(file), line: 1, end_line: 1 } });

    function addSymbol(name, kind, node, stack) {
      const qualname = [...stack, name].join(".");
      const id = `${mid}:${qualname}`;
      const bodyText = node.getText(source);
      const item = {
        id,
        module_id: mid,
        name,
        qualname,
        kind,
        exported: !name.startsWith("_"),
        location: loc(source, node, file),
        normalized_body_hash: kind === "function" || kind === "method" || kind === "class" ? hashText(bodyText.replace(/\s+/g, " ")) : undefined,
        token_signature: kind === "function" || kind === "method" || kind === "class" ? tokens(bodyText) : undefined
      };
      symbols.push(item);
      known.set(name, id);
      known.set(qualname, id);
      return id;
    }

    function addSyntheticSymbol(name, kind, node, extra) {
      const id = stableId(kind === "route" ? "route" : "dom", name);
      if (!symbols.some(s => s.id === id)) {
        symbols.push({
          id,
          module_id: mid,
          name,
          qualname: name,
          kind,
          exported: true,
          location: loc(source, node, file),
          ...(extra || {})
        });
      }
      return id;
    }

    function target(name) {
      return known.get(name) || `external:${name}`;
    }

    function edge(type, from, to, node, metadata) {
      const item = { type, from, to, location: { path: rel(file), line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1 } };
      if (metadata) item.metadata = metadata;
      edges.push(item);
    }

    function visit(node, stack, current) {
      if (ts.isImportDeclaration(node)) {
        const spec = node.moduleSpecifier && node.moduleSpecifier.text ? node.moduleSpecifier.text : "";
        edge("import", current, spec, node);
      } else if (ts.isFunctionDeclaration(node) && node.name) {
        const id = addSymbol(node.name.text, stack.length ? "method" : "function", node, stack);
        ts.forEachChild(node, child => visit(child, [...stack, node.name.text], id));
        return;
      } else if (ts.isClassDeclaration(node) && node.name) {
        const id = addSymbol(node.name.text, "class", node, stack);
        if (node.heritageClauses) {
          for (const clause of node.heritageClauses) {
            for (const typeNode of clause.types) edge("inherit", id, target(nodeName(typeNode.expression)), typeNode);
          }
        }
        ts.forEachChild(node, child => visit(child, [...stack, node.name.text], id));
        return;
      } else if (ts.isMethodDeclaration(node) && node.name) {
        const name = nodeName(node.name);
        if (name) {
          const id = addSymbol(name, "method", node, stack);
          ts.forEachChild(node, child => visit(child, [...stack, name], id));
          return;
        }
      } else if (ts.isVariableStatement(node) && current === mid) {
        for (const decl of node.declarationList.declarations) {
          const name = nodeName(decl.name);
          if (name) addSymbol(name, "var", decl, stack);
          if (name && decl.initializer && ts.isIdentifier(decl.initializer)) edge("alias", current, target(decl.initializer.text), decl, { alias: name });
        }
      } else if (ts.isCallExpression(node)) {
        const name = nodeName(node.expression);
        if (name) {
          if (["eval", "Function", "setTimeout", "require"].includes(name)) edge("dynamic", current, `dynamic:${name}`, node, { dynamic_kind: name === "require" ? "dynamic_import" : "dynamic_dispatch" });
          edge("call", current, target(name), node);
          const value = firstStringArg(node);
          if (value && ["querySelector", "querySelectorAll", "$"].includes(name)) {
            const id = addSyntheticSymbol(value, "dom", node, { selector: value });
            edge("dom_ref", current, id, node, { selector: value });
          } else if (value && name === "getElementById") {
            const selector = `#${value}`;
            const id = addSyntheticSymbol(selector, "dom", node, { selector });
            edge("dom_ref", current, id, node, { selector });
          } else if (value && ["fetch", "get", "post", "put", "patch", "delete"].includes(name) && value.startsWith("/")) {
            const id = addSyntheticSymbol(value, "route", node, { method: name === "fetch" ? "GET" : name.toUpperCase() });
            edge("route_ref", current, id, node, { route: value, method: name === "fetch" ? "GET" : name.toUpperCase() });
          }
        }
      } else if (ts.isBinaryExpression(node) && ts.isIdentifier(node.left)) {
        edge("write_global", current, target(node.left.text), node);
      }
      ts.forEachChild(node, child => visit(child, stack, current));
    }
    ts.forEachChild(source, child => visit(child, [], mid));
  }

  const entrypoints = args.entrypoints && args.entrypoints.length ? args.entrypoints : symbols.filter(s => ["function", "class"].includes(s.kind) && s.exported).map(s => s.id).sort();
  return {
    schema_version: 1,
    language: args.lang || "ts",
    root,
    modules: modules.sort((a, b) => a.id.localeCompare(b.id)),
    symbols: symbols.sort((a, b) => a.id.localeCompare(b.id)),
    edges: edges.sort((a, b) => `${a.type}:${a.from}:${a.to}`.localeCompare(`${b.type}:${b.from}:${b.to}`)),
    entrypoints,
    passed: true
  };
}

try {
  emit(build(), args.output);
} catch (error) {
  emit({ schema_version: 1, passed: false, status: "NEEDS-HUMAN", errors: [String(error && error.message || error)], modules: [], symbols: [], edges: [], entrypoints: [] }, args.output);
}
