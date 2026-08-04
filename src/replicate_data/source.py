import json
import re
import ssl
import urllib.request
from typing import Dict, List, Any, Optional

DEFAULT_HEADERS = {
    "User-Agent": "alternative-data-replicate-scraper/1.0 (+https://github.com/Henrywzh/alternative-data)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_COLLECTIONS = [
    "language-models",
    "text-to-image",
    "flux",
    "text-to-video",
    "image-to-video",
    "speech-to-text",
    "text-to-speech",
    "ai-music-generation",
    "vision-models",
    "image-to-text",
    "embedding-models",
    "3d-models",
    "super-resolution",
    "image-editing",
    "official"
]

def _make_request(url: str, headers: Optional[Dict[str, str]] = None) -> str:
    ctx = ssl.create_default_context()

    req_headers = DEFAULT_HEADERS.copy()
    if headers:
        req_headers.update(headers)
        
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, context=ctx, timeout=20) as resp:
        return resp.read().decode("utf-8")

def parse_run_count(run_str: str) -> int:
    """Convert strings like '31.2M runs', '918.6K runs', '2.3M', '500' to integer count."""
    if not run_str:
        return 0
    clean = run_str.lower().replace("runs", "").replace(",", "").strip()
    try:
        if "m" in clean:
            val = float(clean.replace("m", "")) * 1_000_000
        elif "k" in clean:
            val = float(clean.replace("k", "")) * 1_000
        elif "b" in clean:
            val = float(clean.replace("b", "")) * 1_000_000_000
        else:
            val = float(clean)
        return int(val)
    except ValueError:
        return 0

def fetch_collections_list() -> List[str]:
    """Fetch all collection slugs from Replicate."""
    url = "https://replicate.com/collections"
    try:
        html = _make_request(url)
        found = set(re.findall(r'href=[\"\']/collections/([a-zA-Z0-9_\-]+)[\"\']', html))
        if found:
            return sorted(list(found))
    except Exception as e:
        print(f"[replicate_data] Warning fetching collections list: {e}")
    return DEFAULT_COLLECTIONS

def fetch_collection_models(collection_slug: str) -> Dict[str, Any]:
    """Fetch models inside a given Replicate collection."""
    url = f"https://replicate.com/collections/{collection_slug}"
    html = _make_request(url)
    
    models = []
    
    # 1. Parse JSON-LD structured items
    ld_jsons = re.findall(r'<script type=\"application/ld\+json\">(.*?)</script>', html, re.DOTALL)
    for ld in ld_jsons:
        try:
            data = json.loads(ld)
            graph = data.get("@graph", [])
            for item in graph:
                if item.get("@type") == "ItemList":
                    for el in item.get("itemListElement", []):
                        sw = el.get("item", {})
                        model_id = sw.get("@id", "").strip("/")
                        if model_id and "/" in model_id:
                            parts = model_id.split("/")
                            owner = parts[0]
                            name = parts[1]
                            models.append({
                                "slug": f"{owner}/{name}",
                                "owner": owner,
                                "name": name,
                                "description": sw.get("description", ""),
                                "url": f"https://replicate.com/{owner}/{name}",
                                "collection": collection_slug
                            })
        except Exception:
            pass
            
    # 2. Extract model hrefs and metadata via Regex fallback
    hrefs = set(re.findall(r'href=[\"\'](/[^/\"]+/[^/\"]+)[\"\']', html))
    excluded_paths = {'docs', 'pricing', 'blog', 'collections', 'enterprise', 'signin', 'explore', 'legal', 'terms', 'privacy', 'about'}
    
    for h in hrefs:
        parts = h.strip("/").split("/")
        if len(parts) == 2 and parts[0] not in excluded_paths:
            owner, name = parts[0], parts[1]
            slug = f"{owner}/{name}"
            if not any(m["slug"] == slug for m in models):
                models.append({
                    "slug": slug,
                    "owner": owner,
                    "name": name,
                    "description": "",
                    "url": f"https://replicate.com/{owner}/{name}",
                    "collection": collection_slug
                })

    return {
        "collection": collection_slug,
        "url": url,
        "total_models": len(models),
        "models": models
    }

def fetch_model_detail(owner: str, name: str) -> Dict[str, Any]:
    """Fetch deep detail for a specific model page on Replicate."""
    url = f"https://replicate.com/{owner}/{name}"
    html = _make_request(url)
    
    # Extract meta tags
    meta_runs = re.search(r'<meta name=[\"\']replicate:run_count[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html)
    meta_official = re.search(r'<meta name=[\"\']replicate:is_official[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html)
    meta_version_date = re.search(r'<meta name=[\"\']replicate:latest_version_created_at[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html)
    meta_desc = re.search(r'<meta name=[\"\']description[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html)
    
    # Parse run count
    run_count = int(meta_runs.group(1)) if meta_runs else 0
    if run_count == 0:
        # Search for runs text in body
        runs_text = re.search(r'([0-9\.\,]+[KMB]?\s*runs)', html, re.IGNORECASE)
        if runs_text:
            run_count = parse_run_count(runs_text.group(1))

    # Parse React component props for price and hardware
    react_props = re.findall(r'<script id=[\"\']react-component-props-[^\"\']+[\"\'] type=[\"\']application/json[\"\']>(.*?)</script>', html)
    hardware = "GPU"
    price = ""
    
    for rp in react_props:
        if "hardware" in rp or "price" in rp:
            try:
                pdata = json.loads(rp)
                if "hardware" in pdata and pdata["hardware"]:
                    hardware = pdata["hardware"]
                if "price" in pdata and pdata["price"]:
                    price = pdata["price"]
            except Exception:
                pass
                
    return {
        "slug": f"{owner}/{name}",
        "owner": owner,
        "name": name,
        "url": url,
        "run_count": run_count,
        "is_official": meta_official.group(1).lower() == "true" if meta_official else False,
        "latest_version_created_at": meta_version_date.group(1) if meta_version_date else "",
        "description": meta_desc.group(1) if meta_desc else "",
        "hardware": hardware,
        "price": price
    }
