# Install — make `/maw` available everywhere

The canonical copy of Multi-Agent Workflow lives **in this repo** (project
scope): the agents, the skill, the conventions, and the tools are all version-
controlled here. When you open Claude Code *inside this repo*, `/maw` and the
subagents work with no setup — Claude Code reads `.claude/` from the project.

To use `/maw` from **any** folder, install the agents and skill under **user
scope** (`~/.claude/`). You can copy them (simple) or symlink them (stays in sync
with this repo as you improve it).

> Requirements: Claude Code on a Pro/Max subscription, and a Python 3 interpreter
> for the `maw-tools/` scripts. If `python` isn't on PATH, `uv run` or `py` work
> too — the scripts are plain stdlib and interpreter-agnostic.

## Option A — copy (simplest)

### macOS / Linux
```bash
REPO="$(pwd)"            # run from the repo root
mkdir -p ~/.claude/agents ~/.claude/skills
cp "$REPO"/.claude/agents/*.md ~/.claude/agents/
cp -R "$REPO"/.claude/skills/maw ~/.claude/skills/
```

### Windows (PowerShell)
```powershell
$repo = (Get-Location).Path        # run from the repo root
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\agents" | Out-Null
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item "$repo\.claude\agents\*.md" "$env:USERPROFILE\.claude\agents\"
Copy-Item -Recurse -Force "$repo\.claude\skills\maw" "$env:USERPROFILE\.claude\skills\"
```

## Option B — symlink (stays in sync with the repo)

### macOS / Linux
```bash
REPO="$(pwd)"
mkdir -p ~/.claude/agents ~/.claude/skills
for f in "$REPO"/.claude/agents/*.md; do ln -sf "$f" ~/.claude/agents/; done
ln -sfn "$REPO/.claude/skills/maw" ~/.claude/skills/maw
```

### Windows (PowerShell, may require admin or Developer Mode)
```powershell
$repo = (Get-Location).Path
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\agents" | Out-Null
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Get-ChildItem "$repo\.claude\agents\*.md" | ForEach-Object {
  New-Item -ItemType SymbolicLink -Force -Path "$env:USERPROFILE\.claude\agents\$($_.Name)" -Target $_.FullName | Out-Null
}
New-Item -ItemType SymbolicLink -Force -Path "$env:USERPROFILE\.claude\skills\maw" -Target "$repo\.claude\skills\maw" | Out-Null
```

## The `maw-tools/` scripts

The agents reference `maw-tools/scaffold_run.py` and `maw-tools/checks.py` by
relative path. For global use, the simplest approach is to run `/maw` from a
folder where the repo is reachable, or copy `maw-tools/` alongside your work.
The scripts have **no third-party dependencies** — any Python 3 runs them.

> A future polish step (Phase 5) could put `maw-tools/` on PATH or ship a small
> launcher so the path is resolved automatically from any directory. `# MAW-TODO`

## Verify

From inside this repo, start Claude Code and run:
```
/maw add a docstring to the greet() function in examples/sample_app/greet.py and prove the test still passes
```
You should get a new folder under `runs/` with `memory.md`, `handoffs/`,
`artifacts/`, and a final acceptance verdict. See `examples/README.md` for a
worked run.
