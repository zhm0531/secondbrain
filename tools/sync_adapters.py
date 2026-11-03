#!/usr/bin/env python3
"""Keep the per-agent adapter copies byte-identical to the shared sources.

SecondBrain ships one core and one MCP stdio server.  Each agent integration
(Codex plugin, DeepSeek Harness bundle) must be self-contained, because both
distribution channels install *only* the adapter directory.  So the shared
files are copied into each adapter instead of imported across directories.

That copy is generated, never hand-edited:

    integrations/shared/secondbrain_mcp_server.py  ->  codex-plugin/mcp/
                                                   ->  integrations/deepseek-harness/.../scripts/
    skills/secondbrain/**                          ->  codex-plugin/skills/secondbrain/**

Usage:
    python tools/sync_adapters.py          # rewrite the copies
    python tools/sync_adapters.py --check  # exit 1 if any copy has drifted
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SHARED_MCP = ROOT / "integrations" / "shared" / "secondbrain_mcp_server.py"
MCP_TARGETS = (
    ROOT / "codex-plugin" / "mcp" / "secondbrain_mcp_server.py",
    ROOT / "integrations" / "deepseek-harness" / "dsh-secondbrain-bridge" / "scripts" / "secondbrain_mcp_server.py",
)

SHARED_SKILL = ROOT / "skills" / "secondbrain"
SKILL_TARGETS = (ROOT / "codex-plugin" / "skills" / "secondbrain",)

SKIP_NAMES = {".DS_Store", "Thumbs.db"}
SKIP_DIRS = {"__pycache__"}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_files(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_NAMES or SKIP_DIRS & set(path.parts):
            continue
        files[path.relative_to(root).as_posix()] = _digest(path)
    return files


def plan() -> list[tuple[Path, Path]]:
    return [(SHARED_MCP, target) for target in MCP_TARGETS]


def drift() -> list[str]:
    problems: list[str] = []
    for source, target in plan():
        if not target.exists():
            problems.append(f"missing: {target.relative_to(ROOT)}")
        elif _digest(source) != _digest(target):
            problems.append(f"out of date: {target.relative_to(ROOT)}")
    canonical = _skill_files(SHARED_SKILL)
    for target in SKILL_TARGETS:
        current = _skill_files(target) if target.exists() else {}
        for name, digest in canonical.items():
            if name not in current:
                problems.append(f"missing: {(target / name).relative_to(ROOT)}")
            elif current[name] != digest:
                problems.append(f"out of date: {(target / name).relative_to(ROOT)}")
        for name in sorted(set(current) - set(canonical)):
            problems.append(f"extra (not in shared skill): {(target / name).relative_to(ROOT)}")
    return problems


def sync() -> None:
    for source, target in plan():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        print(f"copied {source.relative_to(ROOT)} -> {target.relative_to(ROOT)}")
    for target in SKILL_TARGETS:
        # Mirror instead of delete+recreate: Windows/OneDrive may keep a handle on
        # the directory (WinError 5 on rmtree), while overwriting files is safe.
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            SHARED_SKILL,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*SKIP_DIRS, *SKIP_NAMES),
        )
        canonical = set(_skill_files(SHARED_SKILL))
        for path in sorted(target.rglob("*"), reverse=True):
            if not path.is_file() or path.name in SKIP_NAMES or SKIP_DIRS & set(path.parts):
                continue
            if path.relative_to(target).as_posix() not in canonical:
                path.unlink()
        print(f"copied {SHARED_SKILL.relative_to(ROOT)} -> {target.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift instead of writing")
    args = parser.parse_args(argv)

    if args.check:
        problems = drift()
        if problems:
            print("adapter copies are out of sync with the shared sources:")
            for item in problems:
                print(f"  - {item}")
            print("run: python tools/sync_adapters.py")
            return 1
        print("adapters in sync")
        return 0

    sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
