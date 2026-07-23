from __future__ import annotations

import json
import time

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-120b"

# Free-tier limits for openai/gpt-oss-120b (console.groq.com/docs/rate-limits).
# Groq rate limits apply at the ORG level, not per-key, so the key pool below
# only helps if those keys genuinely belong to separate orgs — it is not a
# substitute for pacing under these numbers.
GROQ_RPM = 30
GROQ_TPM = 8000
TPM_SAFETY_MARGIN = 0.85  # stay under this fraction of TPM to leave headroom for estimate error

# Keep each request's token footprint well under the per-minute budget so a
# single chunk can never blow the whole window on its own (~40 items x ~90
# tokens each + overhead stays comfortably inside the safety-margined TPM).
CHUNK_SIZE = 40

# Only title + one key stat ever reach the guard — no summary/body text —
# so this stage stays cheap regardless of how many items are ingested that day.
SYSTEM_PROMPT = (
    "You are a triage guard for an AI/LLM industry news feed. You are given a "
    "batch of items, each with only a title (or model id) and one key stat "
    "(upvotes/score/likes). Tag each item's importance as \"high\", "
    "\"medium\", or \"low\" based on how likely it signals a significant "
    "model release, capability jump, lab announcement, or notable industry "
    "event — not routine chatter, tutorials, or memes. "
    "Respond with ONLY a JSON object of this exact shape: "
    '{"tags": [{"item_id": "...", "importance": "high|medium|low", "reason": "<=12 words"}]}'
)


class _RateLimiter:
    """Paces requests against Groq's per-minute RPM/TPM budget.

    Token accounting uses the actual `usage.total_tokens` Groq reports back
    on each response (via `record`), not a guess — the pre-flight estimate
    passed to `wait_for_slot` only decides whether to wait before sending.
    """

    def __init__(self, tpm: int, rpm: int) -> None:
        self.tpm_budget = int(tpm * TPM_SAFETY_MARGIN)
        self.min_interval = 60.0 / rpm
        self._window_start = time.monotonic()
        self._window_tokens = 0
        self._last_request = 0.0

    def wait_for_slot(self, estimated_tokens: int) -> None:
        now = time.monotonic()
        gap = now - self._last_request
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)

        now = time.monotonic()
        if now - self._window_start >= 60:
            self._window_start = now
            self._window_tokens = 0
        if self._window_tokens + estimated_tokens > self.tpm_budget:
            sleep_for = 60 - (now - self._window_start)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._window_start = time.monotonic()
            self._window_tokens = 0

    def record(self, actual_tokens: int) -> None:
        self._window_tokens += actual_tokens
        self._last_request = time.monotonic()


class GroqGuard:
    def __init__(self, api_keys: list[str]) -> None:
        if not api_keys:
            raise RuntimeError("No GROQ_API_KEY configured")
        self.api_keys = api_keys
        self._limiter = _RateLimiter(GROQ_TPM, GROQ_RPM)

    def tag(self, candidates: list[dict]) -> dict[str, dict]:
        """candidates: [{item_id, title, key_stat}] -> {item_id: {importance, reason}}

        A chunk that fails outright (e.g. the whole key pool rate-limited)
        returns no tags for those items rather than raising — the caller
        defaults untagged items to "medium" so one bad chunk degrades the
        brief instead of losing the whole daily run.
        """
        tags: dict[str, dict] = {}
        for start in range(0, len(candidates), CHUNK_SIZE):
            try:
                tags.update(self._tag_chunk(candidates[start : start + CHUNK_SIZE]))
            except Exception as exc:
                print(f"WARNING: guard chunk [{start}:{start + CHUNK_SIZE}] failed, defaulting to medium: {exc}")
        return tags

    def _tag_chunk(self, candidates: list[dict]) -> dict[str, dict]:
        if not candidates:
            return {}
        user_payload = json.dumps(
            [{"item_id": c["item_id"], "title": c["title"], "key_stat": c["key_stat"]} for c in candidates]
        )
        body = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        # ~4 chars/token, plus headroom for the JSON tag output we expect back.
        estimated_tokens = (len(SYSTEM_PROMPT) + len(user_payload)) // 4 + 40 * len(candidates)

        last_exc: Exception | None = None
        # Two passes over the key pool: rotating keys handles a single
        # exhausted key, but a 429 on every key in one pass usually means an
        # org-wide limit, so the second pass waits it out before retrying.
        for attempt in range(2):
            if attempt:
                time.sleep(5)
            for key in self.api_keys:
                self._limiter.wait_for_slot(estimated_tokens)
                try:
                    resp = requests.post(
                        GROQ_URL,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json=body,
                        timeout=60,
                    )
                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", 5))
                        last_exc = RuntimeError(f"429 rate limited (Retry-After={retry_after}s)")
                        time.sleep(retry_after)
                        continue
                    resp.raise_for_status()
                    payload = resp.json()
                    self._limiter.record(payload.get("usage", {}).get("total_tokens", estimated_tokens))
                    content = payload["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    return {
                        t["item_id"]: {"importance": t.get("importance", "low"), "reason": t.get("reason", "")}
                        for t in parsed.get("tags", [])
                        if t.get("item_id")
                    }
                except Exception as exc:
                    last_exc = exc
                    continue
        raise RuntimeError(f"All Groq API keys failed on a chunk of {len(candidates)}: {last_exc}") from last_exc
