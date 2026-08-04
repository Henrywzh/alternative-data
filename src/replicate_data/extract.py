from typing import Dict, List, Any
import pandas as pd

def extract_models_catalog(
    raw_collections_data: List[Dict[str, Any]],
    model_details: Dict[str, Dict[str, Any]],
    scraped_at: str,
) -> pd.DataFrame:
    """Normalize raw collection and model detail data into a clean DataFrame."""
    records = []
    seen_slugs = set()
    snapshot_date = scraped_at.split("T", 1)[0]

    for col_data in raw_collections_data:
        col_slug = col_data.get("collection", "")
        for m in col_data.get("models", []):
            slug = m.get("slug", "")
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            detail = model_details.get(slug, {})
            records.append({
                "snapshot_date": snapshot_date,
                "slug": slug,
                "owner": m.get("owner", ""),
                "name": m.get("name", ""),
                "collection": col_slug,
                "run_count": detail.get("run_count", 0),
                "is_official": detail.get("is_official", False),
                "latest_version_created_at": detail.get("latest_version_created_at", ""),
                "hardware": detail.get("hardware", "GPU"),
                "price": detail.get("price", ""),
                "description": detail.get("description") or m.get("description", ""),
                "url": m.get("url", f"https://replicate.com/{slug}"),
                "scraped_at": scraped_at,
            })

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(by="run_count", ascending=False).reset_index(drop=True)
    return df

def extract_collections_summary(raw_collections_data: List[Dict[str, Any]], scraped_at: str) -> pd.DataFrame:
    """Extract collection-level statistics (total models per category)."""
    records = []
    snapshot_date = scraped_at.split("T", 1)[0]
    for col in raw_collections_data:
        records.append({
            "snapshot_date": snapshot_date,
            "collection_slug": col.get("collection", ""),
            "total_models": col.get("total_models", 0),
            "url": col.get("url", ""),
            "scraped_at": scraped_at,
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values(by="total_models", ascending=False).reset_index(drop=True)
    return df
