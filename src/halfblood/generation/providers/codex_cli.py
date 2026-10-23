"""Generation through a locally installed, already signed-in OpenAI Codex CLI.

``codex exec --output-schema`` runs one prompt headless and constrains the final
message to a JSON Schema. Like ``claude-cli``, the CLI owns its own
authentication (a ChatGPT sign-in is enough), so this adapter never sees a
credential. Its main use is an independent, non-Anthropic eval judge.

The CLI runs in a read-only sandbox, from an empty temporary directory, with
stdin closed (``codex exec`` otherwise waits on stdin under a non-tty driver).
As with every adapter, the payload is re-validated locally.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from halfblood.generation.errors import (
    ProviderConfigurationError,
    ProviderTransientError,
    StructuredOutputError,
)
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)

# "default" leaves the model to the user's ~/.codex/config.toml; pinning a model
# can fail on ChatGPT-account sign-in.
DEFAULT_CODEX_CLI_MODEL = "default"


def _usage_from_events(stdout: str) -> GenerationUsage:
    input_tokens = output_tokens = 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
    return GenerationUsage(input_tokens=input_tokens, output_tokens=output_tokens)


class CodexCliProvider:
    """Adapter that shells out to ``codex exec --output-schema``."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        timeout_seconds: float = 600.0,
        max_retries: int = 1,
    ) -> None:
        resolved = shutil.which(executable)
        if resolved is None:
            raise ProviderConfigurationError(
                f"codex-cli provider: '{executable}' was not found on PATH"
            )
        self._executable = resolved
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, max_retries)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_tool_calling=False,
            supports_json_schema=True,
            supports_strict_json_schema=True,
        )

    def _command(self, request: GenerationRequest, workdir: Path) -> list[str]:
        command = [
            self._executable,
            "exec",
            "-s",
            "read-only",
            "--skip-git-repo-check",
            "--json",
            "--output-schema",
            str(workdir / "schema.json"),
            "--output-last-message",
            str(workdir / "last.json"),
        ]
        if request.model and request.model != DEFAULT_CODEX_CLI_MODEL:
            command += ["-m", request.model]
        prompt = f"{request.system_prompt}\n\n{request.user_prompt}"
        return [*command, prompt]

    def _run_once(self, request: GenerationRequest) -> tuple[str, GenerationUsage]:
        with tempfile.TemporaryDirectory(prefix="halfblood-codex-") as tmp:
            workdir = Path(tmp)
            (workdir / "schema.json").write_text(json.dumps(dict(request.schema)))
            try:
                completed = subprocess.run(
                    self._command(request, workdir),
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    cwd=workdir,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderTransientError(
                    f"codex-cli timed out after {self._timeout_seconds:.0f}s"
                ) from exc
            last = workdir / "last.json"
            message = last.read_text() if last.exists() else ""
        if completed.returncode != 0 or not message.strip():
            detail = (completed.stderr or completed.stdout).strip()[-300:]
            raise ProviderTransientError(
                f"codex-cli exited {completed.returncode} without a final message: {detail}"
            )
        return message, _usage_from_events(completed.stdout)

    def complete(self, request: GenerationRequest) -> GenerationResult:
        started = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            try:
                message, usage = self._run_once(request)
                break
            except ProviderTransientError:
                if attempts > self._max_retries:
                    raise
        try:
            payload: Any = json.loads(message)
            parsed = request.output_model.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise StructuredOutputError(
                f"codex-cli payload failed local validation: {exc}"
            ) from exc
        return GenerationResult(
            parsed=parsed,
            request_id=None,
            finish_reason="end_turn",
            usage=usage,
            latency_seconds=time.monotonic() - started,
            structured_output_mode="json-schema",
            attempts=attempts,
        )
