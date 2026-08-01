#!/usr/bin/env bash
# Master batch runner for all 11 verified HK & Mainland retail store scrapers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Use the interpreter provided by PATH (for example by actions/setup-python),
# rather than assuming the developer's local pyenv shim layout.
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Running HK retail store-count scrapers for $(date +%Y-%m-%d)"
echo "=========================================="

for scraper in \
    "Chow Tai Fook (周大福)|scrape_ctf_stores.py" \
    "Chow Sang Sang (周生生)|scrape_chowsangsang_stores.py" \
    "Fairwood (大快活)|scrape_fairwood_stores.py" \
    "Sa Sa (莎莎)|scrape_sasa_stores.py" \
    "Luk Fook (六福珠宝)|scrape_lukfook_stores.py" \
    "Café de Coral (大家乐)|scrape_cafedecoral_stores.py" \
    "Giordano (佐丹奴)|scrape_giordano_stores.py" \
    "Bossini (堡狮龙)|scrape_bossini_stores.py" \
    "Lao Pu Gold (老铺黄金)|scrape_laopugold_stores.py" \
    "POP MART (泡泡玛特)|scrape_popmart_stores.py" \
    "Tai Hing Group (太兴集团)|scrape_taihing_stores.py"; do

    name="${scraper%%|*}"
    script="${scraper##*|}"

    echo ""
    echo "$name"
    "$PYTHON_BIN" "scripts/$script"
done

echo ""
echo "=========================================="
echo "All 11 verified store scrapers completed successfully."
