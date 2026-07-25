#!/usr/bin/env bash
# Run all HK retail/F&B store-count scrapers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${1:-data}"
DATE="${2:-$(date +%Y-%m-%d)}"

echo "Running HK retail store-count scrapers for $DATE"
echo "=========================================="
echo ""

for scraper in \
    "Chow Tai Fook (周大福)|scrape_ctf_stores.py" \
    "Chow Sang Sang (周生生)|scrape_chowsangsang_stores.py" \
    "Fairwood (大快活)|scrape_fairwood_stores.py" \
    "Sa Sa (莎莎)|scrape_sasa_stores.py" \
    "Luk Fook (六福珠宝)|scrape_lukfook_stores.py" \
    "Café de Coral (大家乐)|scrape_cafedecoral_stores.py" \
    "Giordano (佐丹奴)|scrape_giordano_stores.py" \
    "Bossini (堡狮龙)|scrape_bossini_stores.py"; do
    
    name="${scraper%%|*}"
    script="${scraper##*|}"
    echo "$name"
    python3 "$SCRIPT_DIR/$script" --data-dir "$DATA_DIR" --date "$DATE" 2>&1
    echo ""
done

echo "=========================================="
echo "All scrapers completed."
