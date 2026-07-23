from __future__ import annotations

import json

import requests

CLOUDFLARE_URL_TEMPLATE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/qwen/qwen3-30b-a3b-fp8"

# Full text only reaches this stage for guard-survivors ("high" importance)
# plus rule-flagged trending models — the expensive step never sees the
# full daily candidate pool.
SYSTEM_PROMPT = (
    "You are an AI-industry analyst producing a concise daily brief for a "
    "quant researcher tracking AI/LLM developments. You are given a small "
    "set of pre-filtered high-importance items with full text. For each "
    "item, write 1-2 sentences on why it matters (model capability, "
    "competitive positioning, or market signal). Then write a 2-3 sentence "
    "overall summary highlighting the single most important development, "
    "cross-referencing items that reinforce each other. "
    "Respond with ONLY a JSON object of this exact shape: "
    '{"items": [{"item_id": "...", "headline": "...", "analysis": "..."}], '
    '"overall_summary": "..."}'
)


class CloudflareEngine:
    def __init__(self, account_id: str, api_key: str) -> None:
        if not account_id or not api_key:
            raise RuntimeError("Missing CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_KEY")
        self.account_id = account_id
        self.api_key = api_key

    def analyze(self, items: list[dict]) -> dict:
        """items: [{item_id, title, text}] -> {items: [...], overall_summary}"""
        if not items:
            return {"items": [], "overall_summary": "No high-importance items today."}

        url = CLOUDFLARE_URL_TEMPLATE.format(account_id=self.account_id)
        body = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(items)},
            ],
        }
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=90,
        )
        resp.raise_for_status()
        result = resp.json()
        if not result.get("success", True):
            raise RuntimeError(f"Cloudflare Workers AI error: {result.get('errors')}")

        # Workers AI parses the model's JSON reply server-side and returns it
        # here already as a dict (reasoning trace is kept separate, in
        # result.choices[0].message.reasoning_content).
        response = result["result"]["response"]
        if isinstance(response, dict):
            return response
        return json.loads(response)
