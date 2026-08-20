from __future__ import annotations
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pandas as pd
import requests
sys.path.insert(0, "src")
from openrouter_data.utils import iter_next_f_objects, walk_json

BASE_DIR = Path("/Users/henrywzh/Quant/alternative-data-arr")
OUTPUT_PARQUET = BASE_DIR / "data" / "normalized" / "openrouter" / "cloud_infra_daily_activity.parquet"
OUTPUT_ECONOMICS = BASE_DIR / "data" / "normalized" / "marts" / "daily_cloud_infra_economics.parquet"

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})

def get_all_providers():
    resp = session.get("https://openrouter.ai/api/v1/providers", timeout=10)
    return resp.json().get("data", [])

def get_model_pricing():
    resp = session.get("https://openrouter.ai/api/v1/models", timeout=10)
    models = resp.json().get("data", [])
    pricing_map = {}
    for m in models:
        mid = m["id"]
        p = m.get("pricing", {})
        prompt_p = float(p.get("prompt", 0) or 0)
        comp_p = float(p.get("completion", 0) or 0)
        blended = (prompt_p + comp_p) / 2.0
        pricing_map[mid] = {
            "prompt": prompt_p,
            "completion": comp_p,
            "blended": blended,
            "name": m.get("name", mid)
        }
    return pricing_map

def fetch_single_provider(p):
    slug = p.get("slug")
    name = p.get("name")
    url = "https://openrouter.ai/provider/" + slug
    try:
        r = session.get(url, timeout=8)
        if r.status_code != 200:
            return None
        for obj in iter_next_f_objects(r.text):
            for node in walk_json(obj):
                if isinstance(node, dict) and isinstance(node.get("data"), list) and len(node["data"]) > 3:
                    first = node["data"][0]
                    if isinstance(first, dict) and "x" in first and "ys" in first:
                        return {
                            "slug": slug,
                            "name": name,
                            "hq": p.get("headquarters"),
                            "datacenters": p.get("datacenters"),
                            "chart_data": node["data"]
                        }
    except Exception:
        return None
    return None

def main():
    print("1. Fetching registered providers...")
    providers = get_all_providers()
    print("Total registered providers:", len(providers))
    print("2. Fetching pricing map...")
    pricing_map = get_model_pricing()
    print("Total models with pricing:", len(pricing_map))
    print("3. Scraping provider daily activity charts...")
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(fetch_single_provider, providers))
    valid = [r for r in results if r is not None]
    print("Providers with valid activity charts:", len(valid))
    raw_records = []
    economics_records = []
    for v in valid:
        slug = v["slug"]
        name = v["name"]
        hq = v.get("hq")
        datacenters = ",".join(v.get("datacenters") or []) if isinstance(v.get("datacenters"), list) else str(v.get("datacenters") or "")
        for pt in v["chart_data"]:
            raw_date = pt.get("x", "")
            usage_date = raw_date.split(" ")[0] if raw_date else None
            if not usage_date:
                continue
            ys = pt.get("ys", {})
            for model_slug, total_tokens_raw in ys.items():
                total_tokens = float(total_tokens_raw or 0)
                if total_tokens <= 0:
                    continue
                p_info = pricing_map.get(model_slug)
                if not p_info:
                    base_slug = "-".join(model_slug.split("-")[:-1])
                    p_info = pricing_map.get(base_slug, {"prompt": 0.000001, "completion": 0.000002, "blended": 0.0000015, "name": model_slug})
                prompt_p = p_info["prompt"]
                comp_p = p_info["completion"]
                blended_p = p_info["blended"]
                est_revenue = total_tokens * blended_p
                rec = {
                    "dataset_id": "cloud_infra_daily_activity",
                    "usage_date": usage_date,
                    "provider_slug": slug,
                    "provider_name": name,
                    "model_permaslug": model_slug,
                    "total_tokens": total_tokens,
                    "headquarters": hq,
                    "datacenters": datacenters,
                }
                raw_records.append(rec)
                econ_rec = {
                    "usage_date": usage_date,
                    "provider_slug": slug,
                    "provider_name": name,
                    "model_permaslug": model_slug,
                    "total_tokens": total_tokens,
                    "prompt_price": prompt_p,
                    "completion_price": comp_p,
                    "blended_price": blended_p,
                    "estimated_revenue": est_revenue,
                    "headquarters": hq,
                    "datacenters": datacenters,
                }
                economics_records.append(econ_rec)
    df_raw = pd.DataFrame(raw_records)
    df_econ = pd.DataFrame(economics_records)
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_ECONOMICS.parent.mkdir(parents=True, exist_ok=True)
    df_raw.to_parquet(OUTPUT_PARQUET, index=False)
    df_econ.to_parquet(OUTPUT_ECONOMICS, index=False)
    print("Done! Saved", OUTPUT_PARQUET, "and", OUTPUT_ECONOMICS)

if __name__ == "__main__":
    main()
