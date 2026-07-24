#!/usr/bin/env python3
"""
Client for the TAMU AI gateway (https://chat-api.tamu.ai/openai).

OpenAI-compatible on the surface, but with enough gateway-specific behavior that
a plain OpenAI snippet will fail in confusing ways. This module encodes what was
established by probing the live API -- see ../references/quirks.md.

Use as a module (sys.path does not expand "~", hence expanduser):

    import os, sys
    sys.path.insert(0, os.path.expanduser("~/.claude/skills/tamu-ai/scripts"))
    from tamu_ai import chat, list_models, run_batch, extract_json

    print(chat([{"role": "user", "content": "hi"}], model="protected.gpt-5.4-mini"))

Or as a CLI:

    python3 tamu_ai.py --check
    python3 tamu_ai.py --list-models
    python3 tamu_ai.py --chat "explain lapse rate in one sentence"

The API key is NEVER stored in this file. It is resolved from, in order:
  1. $TAMU_AI_API_KEY
  2. ~/.config/tamu-ai/api-key
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = "https://chat-api.tamu.ai/openai"
KEY_FILE = Path.home() / ".config" / "tamu-ai" / "api-key"

# No default model on purpose: pick per task. See ../references/models.md.
# These two are the well-characterized endpoints of the speed/judgment tradeoff.
FAST_MODEL = "protected.gpt-5.4-mini"     # ~1.0 s/call, all standard params work
JUDGMENT_MODEL = "protected.Claude Sonnet 4.6"  # ~2.5 s/call, strong rubric adherence

DEFAULT_TIMEOUT = 180
DEFAULT_WORKERS = 8


class TamuAIError(Exception):
    """Any TAMU AI failure. `.retryable` says whether trying again could help."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


# ---------------------------------------------------------------------------
# Key resolution -- never writes, never echoes
# ---------------------------------------------------------------------------

def resolve_key() -> str:
    """Find the API key. Raises with instructions rather than prompting."""
    key = os.environ.get("TAMU_AI_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    raise TamuAIError(
        "No TAMU AI API key found.\n"
        "  Set it for this shell:   export TAMU_AI_API_KEY='sk-...'\n"
        f"  Or save it once:         mkdir -p {KEY_FILE.parent} && "
        f"printf %s 'sk-...' > {KEY_FILE} && chmod 600 {KEY_FILE}\n"
        "  Get a key from chat.tamu.ai -> Settings -> API Key."
    )


def _headers(api_key=None) -> dict:
    return {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key or resolve_key()}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Model-family parameter guards
# ---------------------------------------------------------------------------

def is_thinking_model(model: str) -> bool:
    """Claude models on this gateway run with extended thinking always enabled."""
    m = model.lower()
    return "claude" in m or "haiku" in m or "opus" in m or "sonnet" in m


# Params that Bedrock rejects outright when thinking is on. Dropping them with a
# warning beats surfacing an opaque BedrockException from three layers down.
_THINKING_BANNED = {
    "temperature": "may only be 1 when thinking is enabled",
    "top_p": "must be >= 0.95 or unset",
    "max_tokens": "must exceed the thinking budget",
    "max_completion_tokens": "must exceed the thinking budget",
}


def _guard_params(model: str, params: dict, quiet: bool = False) -> dict:
    """Strip params a thinking model rejects; raise on ones that fail silently."""
    if not is_thinking_model(model):
        return params

    # response_format is the dangerous one: the gateway ACCEPTS it and then
    # returns an empty {} instead of erroring. Silently dropping it would leave
    # the caller believing they have guaranteed JSON. Refuse loudly instead.
    if "response_format" in params:
        raise TamuAIError(
            f"response_format is silently broken on {model}: the gateway accepts "
            "it and returns an empty {} instead of your content.\n"
            "  Fix: ask for JSON in the prompt text instead, and parse the reply "
            "with extract_json() (it tolerates ```json fences, which Claude adds).\n"
            f"  Or use a GPT model ({FAST_MODEL}), where response_format works."
        )

    cleaned = dict(params)
    for name, why in _THINKING_BANNED.items():
        if name in cleaned:
            if name == "temperature" and cleaned[name] == 1:
                continue  # temperature=1 is the one allowed value
            cleaned.pop(name)
            if not quiet:
                print(f"  [tamu_ai] dropped {name!r} for {model} ({why})",
                      file=sys.stderr)
    return cleaned


# ---------------------------------------------------------------------------
# Response checking -- three distinct failure shapes
# ---------------------------------------------------------------------------

def _check_response(resp) -> dict:
    """Validate a gateway response and return its parsed body.

    The gateway fails in three different ways and only one looks like an error
    to normal code:
      1. HTTP 200 with {"error": {...}}   <- upstream/LiteLLM errors
      2. HTTP 4xx with {"detail": "..."}  <- gateway rejections
      3. transport timeouts               <- handled by the caller's retry loop
    """
    try:
        payload = resp.json() if resp.content else {}
    except ValueError:
        payload = {}

    if isinstance(payload, dict) and "error" in payload:
        err = payload["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        # Upstream 429/5xx surfaced inside a 200 body is still worth retrying.
        retryable = any(s in msg.lower() for s in ("rate limit", "429", "timeout",
                                                   "overloaded", "503", "502"))
        raise TamuAIError(f"gateway error: {msg}", retryable=retryable)

    if isinstance(payload, dict) and "detail" in payload:
        raise TamuAIError(f"gateway rejected request: {payload['detail']}",
                          retryable=False)

    if resp.status_code >= 400:
        raise TamuAIError(f"HTTP {resp.status_code}: {resp.text[:300]}",
                          retryable=resp.status_code >= 500 or resp.status_code == 429)

    return payload


# ---------------------------------------------------------------------------
# Core calls
# ---------------------------------------------------------------------------

def list_models(api_key=None, timeout=30) -> list[str]:
    """Every model id available to this key. The roster changes -- always check."""
    resp = requests.get(f"{BASE_URL}/models", headers=_headers(api_key), timeout=timeout)
    payload = _check_response(resp)
    return sorted(m["id"] for m in payload.get("data", []))


def chat_raw(messages, model, api_key=None, session=None, retries=4,
             timeout=DEFAULT_TIMEOUT, quiet=False, **params) -> dict:
    """One chat completion; returns the full response JSON (including `usage`)."""
    body = {"model": model, "messages": messages, "stream": False,
            **_guard_params(model, params, quiet)}
    headers = _headers(api_key)
    poster = (session or requests).post

    last = None
    for attempt in range(retries):
        try:
            return _check_response(
                poster(f"{BASE_URL}/chat/completions", headers=headers,
                       json=body, timeout=timeout))
        except TamuAIError as exc:
            last = exc
            if not exc.retryable:
                raise
        except requests.RequestException as exc:
            last = TamuAIError(f"{type(exc).__name__}: {exc}", retryable=True)
        if attempt < retries - 1:
            time.sleep(2**attempt + 0.5)
    raise last or TamuAIError("unknown failure")


def chat(messages, model, **kwargs) -> str:
    """One chat completion; returns just the reply text.

    `messages` may also be a plain string, treated as a single user turn.
    """
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    payload = chat_raw(messages, model, **kwargs)
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise TamuAIError(f"unexpected response shape: {str(payload)[:300]}") from exc


def extract_json(text: str) -> dict:
    """Parse JSON out of a model reply.

    Claude models on this gateway wrap JSON in ```json fences; GPT models don't.
    This tolerates both, plus stray prose around the object.
    """
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"[\{\[].*[\}\]]", text, flags=re.DOTALL)
    if not match:
        raise TamuAIError(f"no JSON found in reply: {text[:200]!r}")
    return json.loads(match.group(0))


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

class _Cache:
    """Thread-safe JSON cache so a re-run never re-pays for finished work."""

    def __init__(self, path, enabled=True):
        self.path = Path(path) if path else None
        self.enabled = enabled and self.path is not None
        self.lock = threading.Lock()
        self.data = {}
        self.dirty = False
        if self.enabled and self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {}

    def get(self, key):
        if not self.enabled:
            return None
        with self.lock:
            return self.data.get(key)

    def put(self, key, value):
        if not self.enabled:
            return
        with self.lock:
            self.data[key] = value
            self.dirty = True

    def save(self):
        if not self.enabled or not self.dirty:
            return
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data), encoding="utf-8")
            tmp.replace(self.path)
            self.dirty = False


def run_batch(items, build_messages, model, workers=DEFAULT_WORKERS,
              cache_path=None, prompt_version=1, parse=None, api_key=None,
              progress_every=25, quiet=False, **params):
    """Run one chat call per item, in parallel, with retry + resume.

    items          : any sequence; each element is passed to build_messages
    build_messages : item -> messages list (or a plain string)
    parse          : optional reply -> value transform, e.g. extract_json
    cache_path     : JSON file; results are keyed by (prompt_version, model,
                     messages), so a re-run costs nothing for finished items and
                     editing a prompt invalidates only what actually changed
    returns        : (results, failures) where results is a list aligned with
                     `items` (None where the call failed) and failures is a list
                     of (index, item, error_string)

    Failures are RETURNED, not raised: one bad item must never discard a long run.
    """
    items = list(items)
    cache = _Cache(cache_path, enabled=cache_path is not None)
    results = [None] * len(items)
    failures = []
    done = 0
    lock = threading.Lock()
    session = requests.Session()
    key = api_key or resolve_key()
    t0 = time.time()

    def work(idx_item):
        idx, item = idx_item
        messages = build_messages(item)
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        ck = hashlib.sha256(json.dumps(
            [prompt_version, model, messages, sorted(params.items())],
            sort_keys=True, default=str).encode()).hexdigest()
        hit = cache.get(ck)
        if hit is not None:
            return idx, item, hit, None
        try:
            reply = chat(messages, model, api_key=key, session=session,
                         quiet=True, **params)
            value = parse(reply) if parse else reply
            cache.put(ck, value)
            return idx, item, value, None
        except Exception as exc:  # noqa: BLE001 - collected, not raised
            return idx, item, None, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(work, pair) for pair in enumerate(items)]
        for fut in as_completed(futures):
            idx, item, value, err = fut.result()
            with lock:
                done += 1
                if err:
                    failures.append((idx, item, err))
                else:
                    results[idx] = value
                if not quiet and (done % progress_every == 0 or done == len(items)):
                    rate = done / max(time.time() - t0, 1e-3)
                    print(f"  {done}/{len(items)} done ({rate:.1f}/s, "
                          f"{len(failures)} failed)", flush=True)
                if done % 50 == 0:
                    cache.save()
    cache.save()
    return results, failures


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="TAMU AI client", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--chat", metavar="TEXT", help="send one message")
    ap.add_argument("--check", action="store_true",
                    help="verify the key, list models, and do one round-trip")
    ap.add_argument("-m", "--model", default=FAST_MODEL)
    ap.add_argument("--system", help="optional system prompt")
    args = ap.parse_args()

    try:
        if args.check:
            models = list_models()
            print(f"Key OK. {len(models)} models available.")
            print(f"Round-trip on {args.model}:")
            print("  " + chat("Reply with exactly: ok", args.model).strip()[:200])
            return 0
        if args.list_models:
            for m in list_models():
                print(m)
            return 0
        if args.chat:
            msgs = ([{"role": "system", "content": args.system}] if args.system else [])
            msgs.append({"role": "user", "content": args.chat})
            print(chat(msgs, args.model))
            return 0
        ap.print_help()
        return 0
    except TamuAIError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
