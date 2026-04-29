#!/usr/bin/env python3
"""Build the Medical Notes Workbench Gemini CLI extension bundle."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "gemini-cli-extension"
SOURCE = ROOT / "extension"


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
        "name": "medical-notes-workbench",
        "version": version,
        "description": (
            "Gemini CLI workbench for creating, organizing, and processing "
            "medical Markdown notes for Obsidian."
        ),
        "contextFileName": "GEMINI.md",
        "settings": [
            {
                "name": "SerpAPI key",
                "envVar": "SERPAPI_KEY",
                "description": (
                    "Optional Google Images search key. Get one at "
                    "https://serpapi.com/ by creating an account and copying "
                    "the API key from your dashboard. Leave blank to use only "
                    "Wikimedia."
                ),
                "sensitive": True,
            }
        ],
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
    for dirname in ("commands", "skills", "agents", "knowledge", "hooks", "policies", "mcp"):
        src_dir = SOURCE / dirname
        if src_dir.exists():
            _copy_tree(src_dir, DIST / dirname)
    docs_dir = ROOT / "docs"
    if docs_dir.exists():
        _copy_tree(docs_dir, DIST / "docs")
    _copy_tree(ROOT / "src", DIST / "src")

    (DIST / "scripts").mkdir()
    extension_scripts = SOURCE / "scripts"
    if extension_scripts.exists():
        _copy_tree(extension_scripts, DIST / "scripts")
    _copy_file(ROOT / "scripts" / "run_agent.py", DIST / "scripts" / "run_agent.py")

    print(f"Built Gemini CLI extension: {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
