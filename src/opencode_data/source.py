from __future__ import annotations

import json
import re
import ssl
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

# Marker present in opencode.ai's hydration bootstrap and data-payload
# scripts (SolidJS's HydrationScript machinery), used to pick the relevant
# <script> tags by content instead of by a brittle fixed position. Verified
# against the live page: of 4 script tags, this marker selects exactly the
# hydration-setup script and the self.$R data script, in order.
_HYDRATION_MARKER = "_$HY"

_NODE_TIMEOUT_SECONDS = 30


def fetch_html(url: str, timeout: int = 30) -> str:
    """Fetch HTML content from a URL."""
    ctx = ssl.create_default_context()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def parse_solid_hydration(html: str) -> list[Any]:
    """Parse SolidJS hydrated $R state array from pre-rendered HTML using Node.js."""
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    hydration_scripts = [s for s in scripts if _HYDRATION_MARKER in s]
    if len(hydration_scripts) < 2:
        raise ValueError(
            f"Expected at least 2 hydration-related script tags (containing "
            f"'{_HYDRATION_MARKER}'), found {len(hydration_scripts)} of {len(scripts)} "
            "total script tags. The page structure may have changed."
        )

    joined_scripts = "\n".join(hydration_scripts)
    js_code = f"""
global.window = global;
global.self = global;
global.localStorage = {{ getItem: () => null }};
global.document = {{
    documentElement: {{ style: {{ setProperty: () => {{}}, removeProperty: () => {{}} }}, dataset: {{}} }},
    addEventListener: () => {{}}
}};

{joined_scripts}

let extracted = [];
if (self.$R) {{
    for (let i = 0; i < self.$R.length; i++) {{
        let item = self.$R[i];
        if (item && item.p && item.p.v) {{
            extracted.push({{ idx: i, value: item.p.v }});
        }}
    }}
}}
console.log(JSON.stringify(extracted));
"""

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(js_code)
        tmp_path = Path(tmp.name)

    try:
        res = subprocess.run(
            ["node", str(tmp_path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=_NODE_TIMEOUT_SECONDS,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    return json.loads(res.stdout)


def extract_home_payload(html: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Extract (statsHome, catalog) from the home page HTML.

    catalog (models+labs metadata: limits, cost, modalities, benchmarks) is
    no longer always present in this page's hydration state as of 2026-08-06
    -- it appears to have moved off the home page entirely (not found in any
    script tag, hydrated or not, confirmed live). stats_home (usage/market/
    leaderboard/users/country -- everything the page visibly renders) is
    unaffected. Treat catalog as optional so a genuine upstream removal of
    one payload doesn't block the rest of the daily scrape; the caller
    degrades the catalog/benchmark datasets specifically, not the whole run.
    """
    extracted = parse_solid_hydration(html)
    stats_home = None
    catalog = None

    for item in extracted:
        val = item.get("value")
        if isinstance(val, dict):
            if "updatedAt" in val and "market" in val and "usage" in val:
                stats_home = val
            elif "models" in val and "labs" in val:
                catalog = val

    if not stats_home:
        raise ValueError("Could not find statsHome in hydrated HTML state.")

    return stats_home, catalog


def extract_model_payload(html: str) -> dict[str, Any]:
    """Extract model stats from either historical or current page hydration."""
    extracted = parse_solid_hydration(html)
    for item in extracted:
        val = item.get("value")
        if isinstance(val, dict):
            if "totals" in val and "tokenMix" in val and "slug" in val:
                return val
            stats = val.get("stats")
            if (
                isinstance(stats, dict)
                and "totals" in stats
                and "tokenMix" in stats
                and "slug" in stats
            ):
                return stats

    raise ValueError("Could not find model deepdive payload in model page HTML state.")
