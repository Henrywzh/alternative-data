import requests
import json
import re

url = "https://openrouter.ai/openai/gpt-4o-mini/activity"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers)
html = resp.text

matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html)
with open("scratch/activity_payload.txt", "w") as f:
    for m in matches:
        if "activity" in m or "categories" in m:
            # unescape the string
            m_unescaped = bytes(m, "utf-8").decode("unicode_escape")
            f.write(m_unescaped + "\n")
