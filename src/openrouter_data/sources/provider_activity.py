from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

from openrouter_data.exceptions import ExtractionError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.utils import iter_next_f_objects, walk_json


# ---------------------------------------------------------------------------
# Provider configuration — add new competitors here with one line.
# Key   = OpenRouter URL slug (openrouter.ai/{key})
# Value = Human-readable display name used in charts
# ---------------------------------------------------------------------------
PROVIDER_SLUGS: dict[str, str] = {
    # Big Tech
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta-llama": "Meta (Llama)",
    "mistralai": "Mistral AI",
    "deepseek": "DeepSeek",
    "x-ai": "xAI (Grok)",
    "microsoft": "Microsoft",
    # Chinese AI ecosystem
    "z-ai": "智谱AI (Z.ai)",
    "moonshotai": "Moonshot AI",
    "qwen": "Alibaba (Qwen)",
    "minimax": "MiniMax",
    "xiaomi": "Xiaomi",
    "tencent": "Tencent",
    "stepfun": "StepFun",
}

PROVIDER_ACTIVITY_DATASET_ID = "provider_daily_activity"
SYNTHETIC_MODEL_BUCKETS = {"Others"}


class ProviderActivitySource(SourceExtractor):
    """Scrapes openrouter.ai/{provider} pages for daily per-model token data.

    Each provider page exposes a stacked-area chart with ~91 days of rolling
    history (trailing 3 months). The chart payload has the shape:
        { "data": [ { "x": "2026-01-16 00:00:00", "ys": { "provider/model": int, ... } } ] }

    This gives us exact token counts per model per day per provider — far more
    accurate than the Top-9 market share chart on /rankings.
    """

    name = "openrouter_provider_activity"
    BASE_URL = "https://openrouter.ai"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
        )

    def fetch_snapshots(self, provider_slugs: dict[str, str] | None = None) -> list[Snapshot]:
        """Fetch provider pages. Defaults to the full PROVIDER_SLUGS config."""
        slugs = provider_slugs or PROVIDER_SLUGS
        snapshots: list[Snapshot] = []
        for slug, display_name in slugs.items():
            url = f"{self.BASE_URL}/{slug}"
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                snapshots.append(
                    Snapshot(
                        name=f"provider_{slug}",
                        source_url=url,
                        body=response.text,
                    )
                )
            except Exception as exc:
                print(f"Warning: Failed to fetch provider page for {slug} ({display_name}): {exc}")
        return snapshots

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        records: list[DatasetRecord] = []

        for snapshot in snapshots:
            # Derive provider slug from snapshot name (e.g. "provider_z-ai" -> "z-ai")
            provider_slug = snapshot.name.removeprefix("provider_")
            provider_display = PROVIDER_SLUGS.get(provider_slug, provider_slug)

            chart = self._find_activity_chart(snapshot.body, provider_slug)
            if chart is None:
                print(f"Warning: No daily activity chart found for provider '{provider_slug}'")
                continue

            for point in chart.get("data", []):
                raw_date = point.get("x", "")
                # Dates come as "2026-01-16 00:00:00" — normalise to YYYY-MM-DD
                usage_date = raw_date.split(" ")[0] if raw_date else None
                if not usage_date:
                    continue

                ys: dict[str, Any] = point.get("ys", {})
                for model_slug, total_tokens_raw in ys.items():
                    total_tokens = float(total_tokens_raw or 0)
                    # Provider pages expose total tokens only (not split by prompt/completion)
                    records.append(
                        DatasetRecord(
                            dataset_id=PROVIDER_ACTIVITY_DATASET_ID,
                            source_url=snapshot.source_url,
                            source_run_id=context.run_id,
                            scraped_at=context.scraped_at_iso,
                            usage_date=usage_date,
                            model_permaslug=model_slug,
                            category_slug=provider_slug,    # provider identifier
                            entity_id=provider_slug,        # provider slug for joins
                            entity_name=provider_display,   # human-readable label
                            total_tokens=total_tokens,
                            prompt_tokens=0.0,              # not split on provider pages
                            completion_tokens=0.0,
                            request_count=None,
                            rank=None,
                        )
                    )

        return {PROVIDER_ACTIVITY_DATASET_ID: records}

    @staticmethod
    def validate_records(
        records: list[DatasetRecord],
        *,
        expected_providers: dict[str, str],
        scraped_at: datetime,
        min_days: int = 60,
        max_lag_days: int = 2,
        min_total_tokens: float = 1.0,
    ) -> dict[str, dict[str, Any]]:
        """Fail loudly when provider-page HTML/RSC changes produce bad extracts."""
        errors: list[str] = []
        if not records:
            raise ExtractionError("Provider activity extraction failed health checks: no records extracted")

        frame = pd.DataFrame([record.to_dict() for record in records])
        required_columns = {"entity_id", "usage_date", "model_permaslug", "total_tokens"}
        missing_columns = sorted(required_columns - set(frame.columns))
        if missing_columns:
            raise ExtractionError(
                "Provider activity extraction failed health checks: "
                f"missing columns {', '.join(missing_columns)}"
            )

        frame["entity_id"] = frame["entity_id"].astype("string")
        frame["model_permaslug"] = frame["model_permaslug"].astype("string")
        frame["usage_date_dt"] = pd.to_datetime(frame["usage_date"], errors="coerce").dt.date
        frame["total_tokens_numeric"] = pd.to_numeric(frame["total_tokens"], errors="coerce").fillna(0.0)

        present_providers = set(frame["entity_id"].dropna().astype(str).unique().tolist())
        missing_providers = sorted(set(expected_providers) - present_providers)
        if missing_providers:
            errors.append(f"missing providers: {', '.join(missing_providers)}")

        malformed_keys = frame["model_permaslug"].dropna().astype(str).map(
            lambda value: value not in SYNTHETIC_MODEL_BUCKETS and ("/" not in value or value.startswith("/"))
        )
        if bool(malformed_keys.any()):
            examples = frame.loc[malformed_keys[malformed_keys].index, "model_permaslug"].dropna().astype(str).head(5).tolist()
            errors.append(f"malformed model keys: {', '.join(examples)}")

        latest_allowed = scraped_at.date() - timedelta(days=max_lag_days)
        summary: dict[str, dict[str, Any]] = {}
        for provider_slug in sorted(present_providers & set(expected_providers)):
            provider_frame = frame[frame["entity_id"] == provider_slug].copy()
            dates = sorted(provider_frame["usage_date_dt"].dropna().unique().tolist())
            latest_date = dates[-1] if dates else None
            total_tokens = float(provider_frame["total_tokens_numeric"].sum())
            model_count = int(provider_frame["model_permaslug"].dropna().nunique())

            summary[provider_slug] = {
                "date_count": len(dates),
                "first_date": dates[0].isoformat() if dates else None,
                "latest_date": latest_date.isoformat() if latest_date else None,
                "model_count": model_count,
                "total_tokens": total_tokens,
            }

            if len(dates) < min_days:
                errors.append(f"{provider_slug}: only {len(dates)} dates extracted; expected at least {min_days}")
            if latest_date is None or latest_date < latest_allowed:
                latest_label = latest_date.isoformat() if latest_date else "none"
                errors.append(
                    f"{provider_slug}: latest date {latest_label} is older than allowed {latest_allowed.isoformat()}"
                )
            if total_tokens <= min_total_tokens:
                errors.append(f"{provider_slug}: total tokens {total_tokens:.0f} is not positive")
            if model_count < 1:
                errors.append(f"{provider_slug}: no model keys extracted")

        if errors:
            detail = "; ".join(errors[:12])
            if len(errors) > 12:
                detail += f"; ... {len(errors) - 12} more"
            raise ExtractionError(f"Provider activity extraction failed health checks: {detail}")

        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_activity_chart(self, html: str, provider_slug: str) -> dict[str, Any] | None:
        """Walk the Next.js RSC payload to find the stacked daily chart."""
        for obj in iter_next_f_objects(html):
            for node in walk_json(obj):
                if not isinstance(node, dict):
                    continue
                data = node.get("data")
                if not isinstance(data, list) or len(data) < 5:
                    continue
                first = data[0]
                if not isinstance(first, dict) or "x" not in first or "ys" not in first:
                    continue
                ys = first.get("ys", {})
                if not isinstance(ys, dict) or not ys:
                    continue
                # Provider pages: all model slugs should start with the provider prefix
                model_keys = list(ys.keys())
                if any(k.startswith(f"{provider_slug}/") for k in model_keys):
                    return node
                # Some providers (e.g. meta-llama) may use different prefix — accept if
                # no slash-less keys (i.e. not the market-share provider chart)
                if all("/" in k for k in model_keys):
                    return node
        return None
