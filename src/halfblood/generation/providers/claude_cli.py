"""Generation through a locally installed, already signed-in Claude Code CLI.

``claude -p`` runs one prompt headless and, with ``--json-schema``, returns the
validated object under ``structured_output``. That lets a person with a Claude
subscription generate annotations without an API key: the CLI owns its own
authentication, so this adapter never sees or forwards a credential.

The CLI is started with no tools, no MCP servers, no project settings and no
saved session, from an empty temporary directory, so the call is a single
stateless completion like every other provider here. As with every adapter,
the payload is re-validated locally against ``request.output_model``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from typing import Any

from pydantic import ValidationError

from halfblood.generation.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderTransientError,
    StructuredOutputError,
)
from halfblood.generation.providers.base import (
    GenerationRequest,
    GenerationResult,
    GenerationUsage,
    ProviderCapabilities,
)

DEFAULT_CLAUDE_CLI_MODEL = "opus"


class ClaudeCliProvider:
    """Adapter that shells out to ``claude -p --output-format json``."""

    def __init__(
        self,
        *,
        executable: str = "claude",
        timeout_seconds: float = 600.0,
        max_retries: int = 1,
    ) -> None:
        resolved = shutil.which(executable)
        if resolved is None:
            raise ProviderConfigurationError(
                f"claude-cli provider: '{executable}' was not found on PATH"
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

    def _command(self, request: GenerationRequest) -> list[str]:
        return [
            self._executable,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(dict(request.schema)),
            "--system-prompt",
            request.system_prompt,
            "--model",
            request.model,
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
        ]

    def _run_once(self, request: GenerationRequest) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="halfblood-claude-") as workdir:
            try:
                completed = subprocess.run(
                    self._command(request),
                    input=request.user_prompt,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    cwd=workdir,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderTransientError(
                    f"claude-cli timed out after {self._timeout_seconds:.0f}s"
                ) from exc
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            detail = (completed.stderr or completed.stdout).strip()[:300]
            raise ProviderTransientError(
                f"claude-cli exited {completed.returncode} without JSON: {detail}"
            ) from exc
        if not isinstance(payload, dict):
            raise ProviderError("claude-cli returned a non-object result")
        if payload.get("is_error"):
            message = str(payload.get("result") or payload.get("subtype") or "error")
            raise ProviderTransientError(f"claude-cli reported an error: {message[:300]}")
        return payload

    def complete(self, request: GenerationRequest) -> GenerationResult:
        started = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            try:
                payload = self._run_once(request)
                break
            except ProviderTransientError:
                if attempts > self._max_retries:
                    raise
        structured = payload.get("structured_output")
        if structured is None:
            raise StructuredOutputError("claude-cli returned no structured_output")
        try:
            parsed = request.output_model.model_validate(structured)
        except ValidationError as exc:
            raise StructuredOutputError(
                f"claude-cli payload failed local validation: {exc}"
            ) from exc
        usage = payload.get("usage") or {}
        input_tokens = sum(
            int(usage.get(key) or 0)
            for key in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        )
        return GenerationResult(
            parsed=parsed,
            request_id=payload.get("uuid"),
            finish_reason=str(payload.get("stop_reason") or "end_turn"),
            usage=GenerationUsage(
                input_tokens=input_tokens,
                output_tokens=int(usage.get("output_tokens") or 0),
            ),
            latency_seconds=time.monotonic() - started,
            structured_output_mode="json-schema",
            attempts=attempts,
        )
