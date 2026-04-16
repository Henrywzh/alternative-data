import requests
import re
import json

url = "https://openrouter.ai/models?order=most-popular"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers)
html = resp.text

# Next.js payload search
matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
slugs = []

for m in matches:
    # Look for patterns like "openai/gpt-4o"
    # Slugs in OpenRouter are usually lowercase maker-id/model-slug
    found = re.findall(r'([a-z0-9-]+/[a-z0-9-.]+)', m)
    for f in found:
        if "/" in f and not f.startswith("assets/") and not f.startswith("next/"):
            slugs.append(f)

# unique in order
unique_slugs = []
for s in slugs:
    if s not in unique_slugs:
        unique_slugs.append(s)

print(json.dumps(unique_slugs[:60], indent=2))
