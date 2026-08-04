import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from replicate_data.source import parse_run_count, fetch_collection_models, fetch_model_detail
from replicate_data.extract import extract_models_catalog, extract_collections_summary
from replicate_data.storage import save_normalized_dataset

def test_parse_run_count():
    assert parse_run_count("31.2M runs") == 31_200_000
    assert parse_run_count("918.6K runs") == 918_600
    assert parse_run_count("1.5B runs") == 1_500_000_000
    assert parse_run_count("500") == 500
    assert parse_run_count("") == 0

def test_extract_models_catalog():
    raw_col = [{
        "collection": "language-models",
        "models": [
            {"slug": "deepseek-ai/deepseek-r1", "owner": "deepseek-ai", "name": "deepseek-r1", "url": "https://replicate.com/deepseek-ai/deepseek-r1", "description": "Reasoning model"}
        ]
    }]
    details = {
        "deepseek-ai/deepseek-r1": {
            "run_count": 31200000,
            "is_official": True,
            "latest_version_created_at": "2026-05-05T20:11:10Z",
            "hardware": "CPU",
            "price": "$0.0001/sec",
            "description": "Reasoning model"
        }
    }
    df = extract_models_catalog(raw_col, details, scraped_at="2026-08-04T12:00:00+00:00")
    assert len(df) == 1
    assert df.iloc[0]["slug"] == "deepseek-ai/deepseek-r1"
    assert df.iloc[0]["run_count"] == 31200000
    assert df.iloc[0]["is_official"] == True
    assert df.iloc[0]["snapshot_date"] == "2026-08-04"

def test_extract_collections_summary():
    raw_col = [
        {"collection": "language-models", "total_models": 44, "url": "https://replicate.com/collections/language-models"},
        {"collection": "text-to-image", "total_models": 86, "url": "https://replicate.com/collections/text-to-image"}
    ]
    df = extract_collections_summary(raw_col, scraped_at="2026-08-04T12:00:00+00:00")
    assert len(df) == 2
    assert df.iloc[0]["collection_slug"] == "text-to-image"
    assert df.iloc[0]["total_models"] == 86


_COLLECTION_TEST_HTML = """
<html><body>
<script type="application/ld+json">
{"@graph": [{"@type": "ItemList", "itemListElement": [
    {"item": {"@id": "/deepseek-ai/deepseek-r1", "name": "DeepSeek R1", "description": "Reasoning model"}}
]}]}
</script>
<a href="/deepseek-ai/deepseek-r1">DeepSeek R1</a>
<a href="/some-owner/some-extra-model">Extra Model</a>
<a href="/docs/getting-started">Docs</a>
<a href="/blog/announcement">Blog</a>
<a href="/pricing">Pricing</a>
</body></html>
"""


def test_fetch_collection_models_combines_jsonld_and_href_fallback_and_excludes_nav_links():
    with patch("replicate_data.source._make_request", return_value=_COLLECTION_TEST_HTML):
        data = fetch_collection_models("language-models")
    slugs = {m["slug"] for m in data["models"]}
    assert slugs == {"deepseek-ai/deepseek-r1", "some-owner/some-extra-model"}
    # deepseek-ai/deepseek-r1 comes from JSON-LD (with its description), not
    # duplicated by the href fallback.
    assert data["total_models"] == 2
    ld_entry = next(m for m in data["models"] if m["slug"] == "deepseek-ai/deepseek-r1")
    assert ld_entry["description"] == "Reasoning model"


_MODEL_DETAIL_TEST_HTML = """
<html><head>
<meta name="replicate:run_count" content="31200000" />
<meta name="replicate:is_official" content="true" />
<meta name="replicate:latest_version_created_at" content="2026-05-05T20:11:10Z" />
<meta name="description" content="Reasoning model" />
</head><body>
<script id="react-component-props-abc" type="application/json">{"hardware": "A100", "price": "$0.0001/sec"}</script>
</body></html>
"""


def test_fetch_model_detail_parses_meta_tags_and_react_props():
    with patch("replicate_data.source._make_request", return_value=_MODEL_DETAIL_TEST_HTML):
        detail = fetch_model_detail("deepseek-ai", "deepseek-r1")
    assert detail["run_count"] == 31200000
    assert detail["is_official"] is True
    assert detail["hardware"] == "A100"
    assert detail["price"] == "$0.0001/sec"


def test_save_normalized_dataset_preserves_prior_days_on_upsert():
    """Regression test for the original blind-overwrite bug in storage.py."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        day1 = pd.DataFrame([{"snapshot_date": "2026-08-03", "slug": "deepseek-ai/deepseek-r1", "run_count": 100}])
        save_normalized_dataset(base_dir, day1, "replicate_model_catalog")

        day2 = pd.DataFrame([{"snapshot_date": "2026-08-04", "slug": "deepseek-ai/deepseek-r1", "run_count": 150}])
        save_normalized_dataset(base_dir, day2, "replicate_model_catalog")

        stored = pd.read_csv(base_dir / "data" / "normalized" / "replicate" / "replicate_model_catalog.csv")
        assert sorted(stored["snapshot_date"].tolist()) == ["2026-08-03", "2026-08-04"]
        assert sorted(stored["run_count"].tolist()) == [100, 150]
