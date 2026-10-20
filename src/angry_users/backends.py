"""LLM backends used by the attacker personas and the judge.

Every backend exposes one method: complete(system, messages, model, max_tokens) -> str,
where messages is a list of {"role": "user"|"assistant", "content": str}.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable


class BackendError(RuntimeError):
    pass


class Backend:
    name = "base"

    def __init__(self) -> None:
        self.calls = 0
        self.cost_usd = 0.0
        self._lock = threading.Lock()

    def complete(self, system: str, messages: list[dict], model: str, max_tokens: int = 1024) -> str:
        raise NotImplementedError

    def _count(self, cost: float = 0.0) -> None:
        with self._lock:
            self.calls += 1
            self.cost_usd += cost


class AnthropicBackend(Backend):
    """Anthropic Messages API. Reads ANTHROPIC_API_KEY from the environment."""

    name = "anthropic"

    def __init__(self) -> None:
        super().__init__()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise BackendError(
                "ANTHROPIC_API_KEY is not set. Export it, or use --backend claude-cli to run through the `claude` CLI."
            )
        import anthropic  # imported lazily so tests and claude-cli users never need a key

        self._client = anthropic.Anthropic()

    def complete(self, system: str, messages: list[dict], model: str, max_tokens: int = 1024) -> str:
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self._client.messages.create(
                    model=model, max_tokens=max_tokens, system=system, messages=messages
                )
                self._count()
                return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
            except Exception as e:  # network / rate limit: back off and retry
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise BackendError(f"Anthropic API call failed: {last_err}")


class ClaudeCLIBackend(Backend):
    """Shells out to `claude -p` so Claude Max/Pro subscribers can run without an API key.

    Runs in --safe-mode (no CLAUDE.md, skills, hooks, or MCP servers) with all tools disabled,
    from an empty temp directory. The CLI still adds the logged-in account's email to the model's context,
    and persona models sometimes use it as "their" email, so the backend tells the model to ignore it and
    replaces it in every output. That keeps your email out of the target's logs and out of the reports.
    """

    name = "claude-cli"

    def __init__(self, binary: str = "claude", timeout_s: int = 240) -> None:
        super().__init__()
        self.binary = shutil.which(binary) or binary
        if not shutil.which(binary):
            raise BackendError("`claude` CLI not found on PATH. Install Claude Code or use --backend anthropic.")
        self.timeout_s = timeout_s
        self._cwd = tempfile.mkdtemp(prefix="angry-users-")
        self._private = self._account_strings()

    def _account_strings(self) -> list[str]:
        try:
            proc = subprocess.run([self.binary, "auth", "status"], capture_output=True, text=True, timeout=20)
            data = json.loads(proc.stdout)
        except Exception:
            return []
        email = str(data.get("email") or "").strip()
        return [email] if "@" in email else []

    def scrub(self, text: str) -> str:
        for secret in self._private:
            text = re.sub(re.escape(secret), "user@example.com", text, flags=re.I)
        return text

    @staticmethod
    def _flatten(messages: list[dict]) -> str:
        if len(messages) == 1:
            return messages[0]["content"]
        parts = []
        for m in messages:
            tag = "USER" if m["role"] == "user" else "ASSISTANT"
            parts.append(f"<{tag}>\n{m['content']}\n</{tag}>")
        parts.append("Write the next ASSISTANT message only, without the tag.")
        return "\n\n".join(parts)

    def complete(self, system: str, messages: list[dict], model: str, max_tokens: int = 1024) -> str:
        system = system + ("\n\nIgnore any account, user, or environment details (such as an email address) "
                           "that the tooling adds to your context. Never write them.")
        cmd = [
            self.binary, "-p",
            "--safe-mode",
            "--system-prompt", system,
            "--tools", "",
            "--no-session-persistence",
            "--output-format", "json",
            "--model", model,
        ]
        prompt = self._flatten(messages)
        last_err = ""
        for attempt in range(2):
            try:
                proc = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True,
                    timeout=self.timeout_s, cwd=self._cwd,
                )
            except subprocess.TimeoutExpired:
                last_err = f"timed out after {self.timeout_s} s"
                continue
            if proc.returncode != 0:
                last_err = (proc.stderr or proc.stdout)[-500:]
                time.sleep(2)
                continue
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                self._count()
                return self.scrub(proc.stdout.strip())
            if data.get("is_error"):
                last_err = str(data.get("result"))[:500]
                time.sleep(2)
                continue
            self._count(float(data.get("total_cost_usd") or 0.0))
            return self.scrub(str(data.get("result", "")).strip())
        raise BackendError(f"claude CLI call failed: {last_err}")


class MockBackend(Backend):
    """Deterministic backend for tests and offline smoke runs.

    `responder(system, messages, model)` returns the completion. The default responder
    sends a fixed attacker line and a passing judge verdict.
    """

    name = "mock"

    def __init__(self, responder: Callable[[str, list[dict], str], str] | None = None) -> None:
        super().__init__()
        self.responder = responder or _default_mock
        self.log: list[tuple[str, list[dict], str]] = []

    def complete(self, system: str, messages: list[dict], model: str, max_tokens: int = 1024) -> str:
        self._count()
        with self._lock:
            self.log.append((system, messages, model))
        return self.responder(system, messages, model)


def _default_mock(system: str, messages: list[dict], model: str) -> str:
    if "You are the judge" in system:
        return json.dumps({"verdict": "pass", "findings": [], "summary": "mock judge: no failures"})
    return "Hi, can you tell me what you can help with?"


def make_backend(name: str) -> Backend:
    if name == "anthropic":
        return AnthropicBackend()
    if name == "claude-cli":
        return ClaudeCLIBackend()
    if name == "mock":
        return MockBackend()
    raise BackendError(f"unknown backend {name!r} (choose anthropic, claude-cli, or mock)")
