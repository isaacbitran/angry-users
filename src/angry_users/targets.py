"""Adapters for the agent under test.

Each target exposes send(message, session_id, history) -> str. `history` is the list of
prior {"role", "content"} turns in this conversation, for targets that are stateless.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import urllib.error
import urllib.request


class TargetError(RuntimeError):
    pass


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: float) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise TargetError(f"HTTP {e.code} from {url}: {detail}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TargetError(f"could not reach {url}: {e}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise TargetError(f"non-JSON response from {url}: {raw[:200]}") from e


def _dig(data, path: str):
    cur = data
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise TargetError(f"reply field {path!r} not found in response: {json.dumps(data)[:200]}")
    return cur


class Target:
    kind = "base"
    label = ""

    def send(self, message: str, session_id: str, history: list[dict]) -> str:
        raise NotImplementedError


class HttpTarget(Target):
    """POST {"message", "session_id"} -> {"reply"} (field names configurable)."""

    kind = "http"

    def __init__(self, url: str, headers: dict[str, str] | None = None, reply_field: str = "reply",
                 message_field: str = "message", session_field: str = "session_id", timeout: float = 120) -> None:
        self.url = url
        self.label = url
        self.headers = headers or {}
        self.reply_field = reply_field
        self.message_field = message_field
        self.session_field = session_field
        self.timeout = timeout

    def send(self, message: str, session_id: str, history: list[dict]) -> str:
        data = _post_json(self.url, {self.message_field: message, self.session_field: session_id},
                          self.headers, self.timeout)
        return str(_dig(data, self.reply_field))


class OpenAITarget(Target):
    """Any OpenAI chat-completions compatible endpoint (OpenAI, vLLM, Ollama, LiteLLM, OpenRouter...).

    The target is stateless, so the full conversation history is sent each turn, with an optional
    system prompt (the agent's real prompt) in front.
    """

    kind = "openai"

    def __init__(self, base_url: str, model: str, api_key: str | None = None, system_prompt: str | None = None,
                 headers: dict[str, str] | None = None, timeout: float = 120) -> None:
        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        self.url = url
        self.label = f"{url} ({model})"
        self.model = model
        self.system_prompt = system_prompt
        self.headers = dict(headers or {})
        if api_key:
            self.headers.setdefault("Authorization", f"Bearer {api_key}")
        self.timeout = timeout

    def send(self, message: str, session_id: str, history: list[dict]) -> str:
        msgs = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(history)
        msgs.append({"role": "user", "content": message})
        data = _post_json(self.url, {"model": self.model, "messages": msgs}, self.headers, self.timeout)
        return str(_dig(data, "choices.0.message.content"))


class CmdTarget(Target):
    """Runs a shell command once per turn: the user message goes to stdin, the reply comes from stdout.

    Environment passed to the command:
      ANGRY_USERS_SESSION_ID  stable id for the conversation (new id = new session)
      ANGRY_USERS_HISTORY     JSON list of prior {"role", "content"} turns
    """

    kind = "cmd"

    def __init__(self, command: str, timeout: float = 120, cwd: str | None = None) -> None:
        self.command = command
        self.label = command
        self.argv = shlex.split(command)
        self.timeout = timeout
        self.cwd = cwd

    def send(self, message: str, session_id: str, history: list[dict]) -> str:
        env = dict(os.environ)
        env["ANGRY_USERS_SESSION_ID"] = session_id
        env["ANGRY_USERS_HISTORY"] = json.dumps(history)
        try:
            proc = subprocess.run(self.argv, input=message, capture_output=True, text=True,
                                  timeout=self.timeout, env=env, cwd=self.cwd)
        except FileNotFoundError as e:
            raise TargetError(f"command not found: {self.argv[0]}") from e
        except subprocess.TimeoutExpired as e:
            raise TargetError(f"command timed out after {self.timeout} s") from e
        if proc.returncode != 0:
            raise TargetError(f"command exited {proc.returncode}: {proc.stderr[-300:]}")
        return proc.stdout.strip()


def make_target(target: str, adapter: str = "auto", *, headers: dict[str, str] | None = None,
                reply_field: str = "reply", model: str | None = None, api_key_env: str | None = None,
                system_prompt: str | None = None, timeout: float = 120) -> Target:
    if adapter == "auto":
        if target.startswith("cmd:"):
            adapter, target = "cmd", target[4:]
        elif target.startswith(("http://", "https://")):
            adapter = "openai" if model else "http"
        else:
            adapter = "cmd"
    if adapter == "http":
        return HttpTarget(target, headers=headers, reply_field=reply_field, timeout=timeout)
    if adapter == "openai":
        if not model:
            raise TargetError("--target-model is required for the openai adapter")
        key = os.environ.get(api_key_env) if api_key_env else None
        if api_key_env and not key:
            raise TargetError(f"{api_key_env} is not set")
        return OpenAITarget(target, model, api_key=key, system_prompt=system_prompt, headers=headers, timeout=timeout)
    if adapter == "cmd":
        return CmdTarget(target, timeout=timeout)
    raise TargetError(f"unknown adapter {adapter!r} (choose http, openai, cmd)")
