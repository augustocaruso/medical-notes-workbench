"""Gemini CLI seam for image enrichment."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from enrich_workflow.models import GeminiError, _DEFAULT_GEMINI_TIMEOUT_SECONDS


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
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as e:
        raise GeminiError(
            f"gemini CLI excedeu timeout de {timeout_seconds}s"
        ) from e
    if proc.returncode != 0:
        raise GeminiError(
            f"gemini CLI falhou (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


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
    cmd: list[str] = [binary]
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
