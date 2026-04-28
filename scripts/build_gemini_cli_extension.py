#!/usr/bin/env python3
"""Build the Gemini CLI extension bundle under dist/gemini-cli-extension."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "gemini-cli-extension"
SOURCE = ROOT / "gemini-cli-extension"


def _project_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', text)
    if not match:
        raise RuntimeError("Could not find project version in pyproject.toml")
    return match.group(1)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".DS_Store",
            ".claude",
            "*.egg-info",
        ),
    )


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    version = _project_version()
    manifest = {
        "name": "medical-notes-enricher",
        "version": version,
        "description": (
            "Gemini CLI extension for enriching medical Markdown notes "
            "with locally downloaded Obsidian image embeds."
        ),
        "contextFileName": "GEMINI.md",
    }
    (DIST / "gemini-extension.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for filename in (
        "README.md",
        "pyproject.toml",
        "config.example.toml",
        ".env.example",
        "package.json",
    ):
        _copy_file(ROOT / filename, DIST / filename)

    _copy_file(SOURCE / "GEMINI.md", DIST / "GEMINI.md")
    _copy_tree(SOURCE / "commands", DIST / "commands")
    _copy_tree(SOURCE / "skills", DIST / "skills")
    _copy_tree(ROOT / "src", DIST / "src")

    (DIST / "scripts").mkdir()
    _copy_file(ROOT / "scripts" / "run_agent.py", DIST / "scripts" / "run_agent.py")

    print(f"Built Gemini CLI extension: {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
