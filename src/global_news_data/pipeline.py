from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from uuid import uuid4
import json
import pandas as pd

from .models import UnifiedNewsRecord
from .storage import NewsStorage
from .sources import GuardianClient, MarketauxClient, CurrentsClient, GdeltClient

logger = logging.getLogger(__name__)

def load_config(config_path: Path) -> dict[str, str]:
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip().strip("'").strip('"')
    return config

class NewsPipeline:
    def __init__(
        self,
        base_dir: Path,
        guardian_client: GuardianClient | None = None,
        marketaux_client: MarketauxClient | None = None,
        currents_client: CurrentsClient | None = None,
        gdelt_client: GdeltClient | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.storage = NewsStorage(base_dir)

        # Load API keys
        config_path = base_dir / ".config"
        self.config = load_config(config_path)

        self.guardian_client = guardian_client
        self.marketaux_client = marketaux_client
        self.currents_client = currents_client

        if self.guardian_client is None:
            g_key = self.config.get("GUARDIAN_API_KEY") or os.environ.get("GUARDIAN_API_KEY")
            if g_key:
                self.guardian_client = GuardianClient(api_key=g_key)
            else:
                logger.warning("GUARDIAN_API_KEY not found in .config or environment")

        if self.marketaux_client is None:
            m_key = self.config.get("MARKETAUX_API_KEY") or os.environ.get("MARKETAUX_API_KEY")
            if m_key:
                self.marketaux_client = MarketauxClient(api_key=m_key)
            else:
                logger.warning("MARKETAUX_API_KEY not found in .config or environment")

        if self.currents_client is None:
            c_key = self.config.get("CURRENTS_API_KEY") or os.environ.get("CURRENTS_API_KEY")
            if c_key:
                self.currents_client = CurrentsClient(api_key=c_key)
            else:
                logger.warning("CURRENTS_API_KEY not found in .config or environment")

        # GDELT requires no API key, so it's always available unless a test
        # explicitly overrides it with a fake/disabled client.
        self.gdelt_client = gdelt_client if gdelt_client is not None else GdeltClient()

    def run(self, query: str = "finance", limit: int = 5) -> dict[str, int]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        logger.info(f"Starting Global News Ingestion Run: {run_id}")

        records: list[UnifiedNewsRecord] = []
        fetched_counts = {"guardian": 0, "marketaux": 0, "currents": 0, "gdelt": 0}
        errors: dict[str, str] = {}
        fetched_at = datetime.now(timezone.utc).isoformat()

        # 1. Fetch Guardian news (honors free-text `query`, same as GDELT below;
        # Marketaux is symbol-driven and Currents' free-tier endpoint is category-driven)
        if self.guardian_client:
            try:
                logger.info("Fetching from Guardian API...")
                payload = self.guardian_client.fetch_articles(query=query, page_size=limit)
                self.storage.write_raw_payload(run_id, "guardian_payload", payload)

                results = payload.get("response", {}).get("results", [])
                for item in results:
                    article_id = item.get("id", "")
                    if not article_id:
                        logger.warning("Skipping Guardian article with missing id.")
                        continue
                    fields = item.get("fields", {})
                    body_text = fields.get("bodyText", "")

                    # Normalize date
                    pub_date = item.get("webPublicationDate", "")
                    try:
                        pub_date = pd.to_datetime(pub_date).isoformat()
                    except Exception:
                        pass

                    records.append(UnifiedNewsRecord(
                        article_id=article_id,
                        source="guardian",
                        published_at=pub_date,
                        title=item.get("webTitle", ""),
                        summary="",
                        body_text=body_text,
                        url=item.get("webUrl", ""),
                        entities=json.dumps([]),
                        sentiment_score=None,
                        language="en",
                        fetched_at=fetched_at
                    ))
                    fetched_counts["guardian"] += 1
                logger.info(f"Guardian fetched: {fetched_counts['guardian']} articles.")
            except Exception as e:
                logger.error(f"Error fetching from Guardian: {e}")
                errors["guardian"] = str(e)

        # 2. Fetch Marketaux news
        if self.marketaux_client:
            try:
                logger.info("Fetching from Marketaux API...")
                # Note: Marketaux handles symbol search. We search defaults or query terms
                payload = self.marketaux_client.fetch_news(limit=limit)
                self.storage.write_raw_payload(run_id, "marketaux_payload", payload)

                articles = payload.get("data", [])
                for item in articles:
                    article_id = item.get("uuid", "")
                    if not article_id:
                        logger.warning("Skipping Marketaux article with missing uuid.")
                        continue

                    # Process entities and compute average sentiment
                    entities = item.get("entities", [])
                    mapped_entities = []
                    sentiment_scores = []
                    for ent in entities:
                        score = ent.get("sentiment_score")
                        mapped_entities.append({
                            "symbol": ent.get("symbol"),
                            "name": ent.get("name"),
                            "sentiment_score": score
                        })
                        if score is not None:
                            sentiment_scores.append(float(score))

                    avg_sentiment = None
                    if sentiment_scores:
                        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores)

                    pub_date = item.get("published_at", "")
                    try:
                        pub_date = pd.to_datetime(pub_date).isoformat()
                    except Exception:
                        pass

                    records.append(UnifiedNewsRecord(
                        article_id=article_id,
                        source="marketaux",
                        published_at=pub_date,
                        title=item.get("title", ""),
                        summary=item.get("description", ""),
                        body_text=item.get("snippet", ""),
                        url=item.get("url", ""),
                        entities=json.dumps(mapped_entities),
                        sentiment_score=avg_sentiment,
                        language=item.get("language", "en"),
                        fetched_at=fetched_at
                    ))
                    fetched_counts["marketaux"] += 1
                logger.info(f"Marketaux fetched: {fetched_counts['marketaux']} articles.")
            except Exception as e:
                logger.error(f"Error fetching from Marketaux: {e}")
                errors["marketaux"] = str(e)

        # 3. Fetch Currents news
        if self.currents_client:
            try:
                logger.info("Fetching from Currents API...")
                payload = self.currents_client.fetch_latest(page_size=limit)
                self.storage.write_raw_payload(run_id, "currents_payload", payload)

                news = payload.get("news", [])
                for item in news:
                    article_id = str(item.get("id", "")).strip()
                    if not article_id:
                        logger.warning("Skipping Currents article with missing id.")
                        continue

                    pub_date = item.get("published", "")
                    try:
                        pub_date = pd.to_datetime(pub_date).isoformat()
                    except Exception:
                        pass

                    records.append(UnifiedNewsRecord(
                        article_id=article_id,
                        source="currents",
                        published_at=pub_date,
                        title=item.get("title", ""),
                        summary=item.get("description", ""),
                        body_text=None,
                        url=item.get("url", ""),
                        entities=json.dumps([]),
                        sentiment_score=None,
                        language=item.get("language", "en"),
                        fetched_at=fetched_at
                    ))
                    fetched_counts["currents"] += 1
                logger.info(f"Currents fetched: {fetched_counts['currents']} articles.")
            except Exception as e:
                logger.error(f"Error fetching from Currents: {e}")
                errors["currents"] = str(e)

        # 4. Fetch GDELT news (no API key required; global multilingual coverage)
        if self.gdelt_client:
            try:
                logger.info("Fetching from GDELT DOC API...")
                payload = self.gdelt_client.fetch_articles(query=query, max_records=limit)
                self.storage.write_raw_payload(run_id, "gdelt_payload", payload)

                articles = payload.get("articles", [])
                for item in articles:
                    url = item.get("url", "")
                    if not url:
                        logger.warning("Skipping GDELT article with missing url.")
                        continue

                    pub_date = item.get("seendate", "")
                    try:
                        pub_date = pd.to_datetime(pub_date).isoformat()
                    except Exception:
                        pass

                    records.append(UnifiedNewsRecord(
                        article_id=url,  # GDELT has no article id; the url is the natural unique key
                        source="gdelt",
                        published_at=pub_date,
                        title=item.get("title", ""),
                        summary="",
                        body_text=None,
                        url=url,
                        entities=json.dumps([]),
                        sentiment_score=None,
                        language=item.get("language", ""),
                        fetched_at=fetched_at
                    ))
                    fetched_counts["gdelt"] += 1
                logger.info(f"GDELT fetched: {fetched_counts['gdelt']} articles.")
            except Exception as e:
                logger.error(f"Error fetching from GDELT: {e}")
                errors["gdelt"] = str(e)

        # 5. Upsert to storage
        total_rows = 0
        if records:
            df = self.storage.upsert_records(records)
            total_rows = len(df)
            logger.info(f"News unified ingestion completed. Total records in DB: {total_rows}")

        return {
            "fetched": fetched_counts,
            "total_records_in_db": total_rows,
            "errors": errors,
        }
