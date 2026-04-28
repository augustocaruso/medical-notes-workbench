#!/usr/bin/env python3
"""Force-publish dist/gemini-cli-extension to the gemini-cli-extension branch."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "dist" / "gemini-cli-extension"
BRANCH = os.environ.get("MNE_GEMINI_EXTENSION_BRANCH", "gemini-cli-extension")
REMOTE_NAME = "publish-origin"


def _run(cmd: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout)
        if proc.stderr:
            print(proc.stderr)
        raise SystemExit(proc.returncode)
    return proc.stdout.strip()


def _remote_url() -> str:
    if os.environ.get("MNE_GEMINI_EXTENSION_REMOTE_URL"):
        return os.environ["MNE_GEMINI_EXTENSION_REMOTE_URL"]
    if os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        repo = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GITHUB_TOKEN"]
        return f"https://x-access-token:{token}@github.com/{repo}.git"
    return _run(["git", "remote", "get-url", "origin"], cwd=ROOT)


def main() -> int:
    manifest = SOURCE_DIR / "gemini-extension.json"
    if not manifest.is_file():
        print(f"Missing {manifest}. Run the build script first.")
        return 1

    with tempfile.TemporaryDirectory(prefix="medical-notes-enricher-extension-") as tmp:
        work_dir = Path(tmp)
        shutil.copytree(SOURCE_DIR, work_dir, dirs_exist_ok=True)
        _run(["git", "init"], cwd=work_dir)
        _run(["git", "config", "user.name", "github-actions[bot]"], cwd=work_dir)
        _run(
            [
                "git",
                "config",
                "user.email",
                "41898282+github-actions[bot]@users.noreply.github.com",
            ],
            cwd=work_dir,
        )
        _run(["git", "add", "."], cwd=work_dir)
        _run(["git", "commit", "-m", "build: publicar extensao gemini cli"], cwd=work_dir)
        _run(["git", "branch", "-M", BRANCH], cwd=work_dir)
        _run(["git", "remote", "add", REMOTE_NAME, _remote_url()], cwd=work_dir)
        _run(["git", "push", "--force", REMOTE_NAME, f"{BRANCH}:refs/heads/{BRANCH}"], cwd=work_dir)

    print(f"Published {SOURCE_DIR} to branch {BRANCH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
