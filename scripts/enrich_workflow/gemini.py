"""Gemini CLI seam for image enrichment."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from enrich_workflow.models import GeminiError, _DEFAULT_GEMINI_TIMEOUT_SECONDS


def _resolve_gemini_binary(binary: str) -> str:
    """Resolve o executável do Gemini CLI de forma portável.

    No Windows, o Gemini instalado por npm costuma existir como `gemini.cmd`
    em `%APPDATA%\npm`. `subprocess` com `shell=False` nem sempre resolve esse
    shim quando o config diz só `gemini`, então normalizamos antes de montar o
    comando.
    """
    expanded = os.path.expandvars(os.path.expanduser(binary))
    if _is_pathish(expanded):
        return expanded

    found = shutil.which(expanded)
    if found:
        return found

    if expanded.lower() in {"gemini", "gemini.cmd"}:
        for candidate in _npm_gemini_candidates():
            if candidate.is_file():
                return str(candidate)

    return expanded


def _is_pathish(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or (len(value) >= 2 and value[1] == ":")
    )


def _npm_gemini_candidates() -> list[Path]:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "gemini.cmd")
    prefix = os.environ.get("NPM_CONFIG_PREFIX")
    if prefix:
        prefix_path = Path(prefix)
        candidates.extend(
            [
                prefix_path / "gemini.cmd",
                prefix_path / "bin" / "gemini",
            ]
        )
    return candidates


def _invoke_gemini(
    cmd: list[str],
    *,
    timeout_seconds: int = _DEFAULT_GEMINI_TIMEOUT_SECONDS,
) -> str:
    """Roda o gemini CLI e devolve stdout. Levanta GeminiError em rc != 0.

    Seam pra teste: monkeypatch isso pra fingir respostas.
    """
    try:
        proc = subprocess.run(
            _subprocess_command(cmd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        raise GeminiError(
            f"gemini CLI excedeu timeout de {timeout_seconds}s"
        ) from e
    except FileNotFoundError as e:
        raise GeminiError(
            "gemini CLI não encontrado. Configure [gemini].binary com o caminho "
            "do executável, ou garanta que `gemini`/`gemini.cmd` esteja no PATH."
        ) from e
    except OSError as e:
        raise GeminiError(f"gemini CLI não pôde ser iniciado: {e}") from e
    if proc.returncode != 0:
        raise GeminiError(
            f"gemini CLI falhou (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def _subprocess_command(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    executable = cmd[0]
    suffix = Path(executable).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/d", "/s", "/c", *cmd]
    return cmd


def call_gemini(
    prompt: str,
    *,
    binary: str,
    model: str | None = None,
    include_dirs: list[Path] | None = None,
    skip_trust: bool = True,
    timeout_seconds: int = _DEFAULT_GEMINI_TIMEOUT_SECONDS,
) -> str:
    """Chama o gemini CLI em modo headless. Multimodal via `@arquivo` no
    próprio prompt + `--include-directories` pra dar acesso ao path."""
    cmd: list[str] = [_resolve_gemini_binary(binary)]
    if skip_trust:
        cmd.append("--skip-trust")
    if include_dirs:
        for d in include_dirs:
            cmd.extend(["--include-directories", str(d)])
    if model:
        cmd.extend(["-m", model])
    cmd.extend(["-p", prompt])
    return _invoke_gemini(cmd, timeout_seconds=timeout_seconds)


def call_gemini_json_with_retry(
    prompt: str,
    parser: Callable[[str], Any],
    *,
    binary: str,
    model: str | None = None,
    include_dirs: list[Path] | None = None,
    timeout_seconds: int = _DEFAULT_GEMINI_TIMEOUT_SECONDS,
    label: str,
) -> tuple[Any, str]:
    """Chama o Gemini e dá uma chance de autocorreção quando ele responde
    prose em vez do JSON contratado."""
    raw = call_gemini(
        prompt,
        binary=binary,
        model=model,
        include_dirs=include_dirs,
        timeout_seconds=timeout_seconds,
    )
    try:
        return parser(raw), raw
    except (json.JSONDecodeError, ValueError) as first_error:
        retry_prompt = (
            "Sua resposta anterior para a tarefa abaixo foi inválida: "
            f"{first_error}.\n\n"
            "Responda novamente com APENAS JSON válido, sem comentários, sem Markdown, "
            "sem texto antes ou depois.\n\n"
            "TAREFA ORIGINAL:\n"
            f"{prompt}\n\n"
            "RESPOSTA ANTERIOR INVÁLIDA:\n"
            f"{raw}"
        )
        retry_raw = call_gemini(
            retry_prompt,
            binary=binary,
            model=model,
            include_dirs=include_dirs,
            timeout_seconds=timeout_seconds,
        )
        try:
            return parser(retry_raw), retry_raw
        except (json.JSONDecodeError, ValueError) as retry_error:
            raise ValueError(
                f"{label} inválido após retry: {retry_error}"
            ) from retry_error
