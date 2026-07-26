# HK Financials Database V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a free, reproducible financials database for the 174-company Hong Kong V1 universe using yfinance and AkShare observations, HKEX filing metadata, point-in-time availability estimates, canonical financial facts, broker forecasts and consensus snapshots.

**Architecture:** Source adapters write immutable, source-specific long-form observations to partitioned Parquet files committed to Git. A generated local DuckDB database reads those Parquet datasets, selects canonical financial facts without deleting conflicting source values, and exposes simple annual, interim, latest-fundamentals and consensus-revision views. HKEX is used for announcement metadata and PDF links only; V1 does not parse financial values from PDFs.

**Tech Stack:** Python 3.11, pandas, pyarrow, yfinance, AkShare, requests, DuckDB, pytest, GitHub Actions, Parquet.

## Global Constraints

- The security universe is the 174 unique HK tickers in `docs/asia-markets/v1-hk-equities.md`.
- V1 covers all 174 securities in every scheduled run; individual failures produce partial status and never abort the remaining tickers.
- Daily prices are outside this project and remain in independently fetched yfinance Parquet datasets.
- Existing alternative-data datasets remain separate and are not copied into the financials database.
- yfinance is the primary automated source for historical financial statements and dividends.
- AkShare supplements current/short-history financial indicators, dividends, broker-level forecasts and aggregate consensus.
- HKEX ingestion stores announcement metadata and PDF URLs only. It does not download or parse financial values from PDFs.
- Every source value is retained as an observation. Canonical facts are derived and never overwrite source observations.
- Point-in-time policy is the practical hybrid model: store exact announcement dates where available, official report-publication dates where matchable, and conservative fallback availability dates otherwise.
- Consensus is an independent, non-blocking V1 module. Missing analyst coverage must not fail financial-statement ingestion.
- Source Parquet snapshots and freshness manifests are committed to Git. `data/databases/hk_financials.duckdb` is generated locally and ignored by Git.
- GitHub Actions cadence: HKEX metadata daily; yfinance financial statements weekly; AkShare financials and consensus weekly; company metadata monthly; HSI/HSTECH source checks weekly.
- Only free data sources and existing repository credentials are allowed.
- Automated tests must mock network calls; the default pytest suite must not depend on live yfinance, AkShare or HKEX availability.

---

## File and Module Map

### New production files

```text
src/hk_financials/
  __init__.py                 Public package version and exports
  cli.py                      Local and GitHub Actions command entry point
  config.py                   Paths, source priorities and quality thresholds
  schemas.py                  Dataset columns, dtypes and validation contracts
  universe.py                 Parse and validate the 174-security reference universe
  normalize.py                Ticker, period, currency and metric normalization
  storage.py                  Partitioned Parquet and manifest persistence
  availability.py             Point-in-time available_at and quality assignment
  canonical.py                Source reconciliation and conflict selection
  duckdb_builder.py           Rebuild generated DuckDB and research views
  quality.py                  Coverage, duplicate, null and conflict checks
  pipeline.py                 Fault-isolated orchestration and run manifests
  sources/
    __init__.py
    yfinance_financials.py    Statements, company metadata and dividends
    yfinance_consensus.py     Aggregated estimates/EPS trend where available
    akshare_financials.py     HK indicators and dividend supplements
    akshare_forecasts.py      Broker rows and aggregate consensus
    hkex_filings.py           Announcement/report metadata and PDF URLs
```

### New tests and fixtures

```text
tests/test_hk_financials_universe.py
tests/test_hk_financials_normalize.py
tests/test_hk_financials_storage.py
tests/test_hk_financials_yfinance.py
tests/test_hk_financials_akshare.py
tests/test_hk_financials_hkex.py
tests/test_hk_financials_availability.py
tests/test_hk_financials_canonical.py
tests/test_hk_financials_duckdb.py
tests/test_hk_financials_pipeline.py
tests/fixtures/hk_financials/
  yfinance_income.json
  yfinance_balance.json
  yfinance_cashflow.json
  yfinance_estimates.json
  akshare_indicators.json
  akshare_broker_forecasts.json
  hkex_title_search.json
```

### New data outputs

```text
data/reference/hk_financials/securities.parquet
data/processed/hk_financials/observations/source=yfinance/snapshot_date=YYYY-MM-DD/*.parquet
data/processed/hk_financials/observations/source=akshare/snapshot_date=YYYY-MM-DD/*.parquet
data/processed/hk_financials/dividends/source=SOURCE/snapshot_date=YYYY-MM-DD/*.parquet
data/processed/hk_financials/broker_forecasts/source=akshare/snapshot_date=YYYY-MM-DD/*.parquet
data/processed/hk_financials/consensus_snapshots/source=SOURCE/snapshot_date=YYYY-MM-DD/*.parquet
data/processed/hk_financials/hkex_filings/snapshot_date=YYYY-MM-DD/*.parquet
data/processed/hk_financials/index_source_checks/snapshot_date=YYYY-MM-DD/*.parquet
data/processed/hk_financials/runs/RUN_ID/manifest.json
data/processed/hk_financials/freshness_manifest.json
data/databases/hk_financials.duckdb
```

### Modified repository files

```text
pyproject.toml
requirements.txt
.gitignore
.github/workflows/hk-financials-weekly.yml
.github/workflows/hk-financials-hkex-daily.yml
docs/asia-markets/README.md
docs/asia-markets/database/README.md
```

## Dataset Contracts

### `financial_observations`

```text
observation_id: string
run_id: string
ticker: string
security_id: string
fiscal_period_end: date
period_type: annual | interim | quarterly | ttm | unknown
statement_type: income | balance_sheet | cash_flow | financial_indicator
metric_raw: string
metric: string
value: double
currency: string
unit_scale: double
source: yfinance | akshare
source_updated_at: timestamp nullable
announcement_date: date nullable
available_at: timestamp
point_in_time_quality: high | medium | low
raw_payload_hash: string
fetched_at: timestamp
```

### `broker_forecasts`

```text
forecast_id: string
run_id: string
ticker: string
fiscal_year: integer
broker_name: string
net_income_forecast: double nullable
eps_forecast: double nullable
dividend_per_share_forecast: double nullable
rating: string nullable
target_price: double nullable
currency: string
broker_updated_at: date nullable
source: akshare_etnet
fetched_at: timestamp
```

### `consensus_snapshots`

```text
consensus_id: string
run_id: string
ticker: string
snapshot_date: date
fiscal_year: integer
eps_avg: double nullable
eps_low: double nullable
eps_high: double nullable
net_income_avg: double nullable
net_income_low: double nullable
net_income_high: double nullable
dividend_per_share_avg: double nullable
target_price_avg: double nullable
rating_avg: double nullable
num_brokers: integer nullable
source: akshare_etnet | yfinance
fetched_at: timestamp
```

### `hkex_filings`

```text
filing_id: string
run_id: string
ticker: string
news_id: string
announcement_date: date
announcement_time: time nullable
document_type: annual_report | interim_report | results_announcement | other
title: string
language: EN | TC | SC
pdf_url: string
file_size: string nullable
fetched_at: timestamp
```

### `canonical_financial_facts`

```text
canonical_id: string
ticker: string
fiscal_period_end: date
period_type: string
statement_type: string
metric: string
value: double
currency: string
available_at: timestamp
point_in_time_quality: high | medium | low
canonical_source: string
selected_observation_id: string
source_count: integer
conflict_status: none | within_tolerance | material
generated_at: timestamp
```

---

### Task 1: Add the package, DuckDB dependency and machine-readable universe

**Files:**
- Create: `src/hk_financials/__init__.py`
- Create: `src/hk_financials/config.py`
- Create: `src/hk_financials/universe.py`
- Create: `tests/test_hk_financials_universe.py`
- Create: `data/reference/hk_financials/securities.parquet`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `load_v1_universe(markdown_path: Path) -> pd.DataFrame`
- Produces: `write_reference_universe(markdown_path: Path, output_path: Path) -> Path`
- Output columns: `ticker`, `security_id`, `name_en`, `name_zh`, `current_index_membership`, `theme`, `is_active`

- [ ] **Step 1: Write the failing universe tests**

```python
from pathlib import Path

from hk_financials.universe import load_v1_universe


def test_v1_universe_has_174_unique_bilingual_securities():
    frame = load_v1_universe(Path("docs/asia-markets/v1-hk-equities.md"))
    assert len(frame) == 174
    assert frame["ticker"].is_unique
    assert frame["ticker"].str.fullmatch(r"\d{4}\.HK").all()
    assert frame["name_en"].notna().all()
    assert frame["name_zh"].notna().all()


def test_v1_universe_contains_minimax_zai_and_samsonite():
    frame = load_v1_universe(Path("docs/asia-markets/v1-hk-equities.md"))
    assert {"0100.HK", "2513.HK", "1910.HK"} <= set(frame["ticker"])
```

- [ ] **Step 2: Run the tests and confirm the module does not exist**

Run: `pytest tests/test_hk_financials_universe.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'hk_financials'`.

- [ ] **Step 3: Add the dependency and configuration**

Add `duckdb>=1.1,<2` to both dependency files. Add this generated database path to `.gitignore`:

```gitignore
data/databases/hk_financials.duckdb
data/databases/hk_financials.duckdb.wal
```

Create `config.py` with repository-relative defaults:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_MARKDOWN = REPO_ROOT / "docs/asia-markets/v1-hk-equities.md"
REFERENCE_DIR = REPO_ROOT / "data/reference/hk_financials"
PROCESSED_DIR = REPO_ROOT / "data/processed/hk_financials"
DATABASE_PATH = REPO_ROOT / "data/databases/hk_financials.duckdb"

MIN_ANNUAL_ANY_STATEMENT_COVERAGE = 0.80
MIN_THREE_STATEMENT_COVERAGE = 0.70
MATERIAL_CONFLICT_RELATIVE_TOLERANCE = 0.005
```

- [ ] **Step 4: Implement Markdown universe parsing**

Parse table rows matching `| 0005.HK | English | 中文 | ... |`, merge repeated theme membership into a semicolon-delimited value, and create `security_id = "HKEX:" + ticker_without_suffix`.

```python
def load_v1_universe(markdown_path: Path) -> pd.DataFrame:
    rows = parse_markdown_equity_rows(markdown_path.read_text(encoding="utf-8"))
    frame = pd.DataFrame(rows)
    grouped = (
        frame.groupby(["ticker", "name_en", "name_zh"], as_index=False)
        .agg(
            current_index_membership=("index_membership", merge_values),
            theme=("theme", merge_values),
        )
    )
    grouped["security_id"] = "HKEX:" + grouped["ticker"].str.removesuffix(".HK")
    grouped["is_active"] = True
    return grouped[
        ["ticker", "security_id", "name_en", "name_zh",
         "current_index_membership", "theme", "is_active"]
    ]
```

- [ ] **Step 5: Generate and validate the reference Parquet**

Run:

```bash
python -c "from hk_financials.universe import write_reference_universe; from hk_financials.config import UNIVERSE_MARKDOWN, REFERENCE_DIR; write_reference_universe(UNIVERSE_MARKDOWN, REFERENCE_DIR / 'securities.parquet')"
```

Expected: `data/reference/hk_financials/securities.parquet` with 174 rows.

- [ ] **Step 6: Run the focused tests**

Run: `pytest tests/test_hk_financials_universe.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml requirements.txt .gitignore src/hk_financials tests/test_hk_financials_universe.py data/reference/hk_financials/securities.parquet
git commit -m "feat(hk-financials): add V1 security universe"
```

---

### Task 2: Define schemas and normalization contracts

**Files:**
- Create: `src/hk_financials/schemas.py`
- Create: `src/hk_financials/normalize.py`
- Create: `tests/test_hk_financials_normalize.py`

**Interfaces:**
- Produces: `normalize_ticker(value: str) -> str`
- Produces: `normalize_period_type(source: str, raw_label: str, period_end: date) -> str`
- Produces: `normalize_metric(statement_type: str, metric_raw: str) -> str`
- Produces: `make_observation_id(row: Mapping[str, object]) -> str`
- Produces constants: `FINANCIAL_OBSERVATION_COLUMNS`, `BROKER_FORECAST_COLUMNS`, `CONSENSUS_COLUMNS`, `HKEX_FILING_COLUMNS`

- [ ] **Step 1: Write normalization tests**

```python
def test_normalize_ticker():
    assert normalize_ticker("700") == "0700.HK"
    assert normalize_ticker("00700") == "0700.HK"
    assert normalize_ticker("0700.HK") == "0700.HK"


def test_normalize_metrics_across_sources():
    assert normalize_metric("income", "Total Revenue") == "revenue"
    assert normalize_metric("income", "营业总收入") == "revenue"
    assert normalize_metric("cash_flow", "Free Cash Flow") == "free_cash_flow"


def test_observation_id_is_deterministic():
    row = {
        "ticker": "0700.HK",
        "fiscal_period_end": "2025-12-31",
        "statement_type": "income",
        "metric": "revenue",
        "source": "yfinance",
        "fetched_at": "2026-07-26T10:00:00Z",
    }
    assert make_observation_id(row) == make_observation_id(row)
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/test_hk_financials_normalize.py -v`

Expected: FAIL because the normalization functions do not exist.

- [ ] **Step 3: Implement schema constants and metric mappings**

Define explicit mappings for the initial canonical metrics:

```python
METRIC_ALIASES = {
    ("income", "Total Revenue"): "revenue",
    ("income", "Operating Revenue"): "revenue",
    ("income", "Gross Profit"): "gross_profit",
    ("income", "Operating Income"): "operating_income",
    ("income", "Net Income"): "net_income",
    ("income", "Basic EPS"): "basic_eps",
    ("income", "Diluted EPS"): "diluted_eps",
    ("balance_sheet", "Total Assets"): "total_assets",
    ("balance_sheet", "Total Debt"): "total_debt",
    ("balance_sheet", "Cash And Cash Equivalents"): "cash_and_equivalents",
    ("balance_sheet", "Stockholders Equity"): "shareholders_equity",
    ("cash_flow", "Operating Cash Flow"): "operating_cash_flow",
    ("cash_flow", "Capital Expenditure"): "capital_expenditure",
    ("cash_flow", "Free Cash Flow"): "free_cash_flow",
}
```

Unknown metrics use `snake_case(metric_raw)` instead of being discarded.

- [ ] **Step 4: Implement deterministic IDs**

Use SHA-256 over canonical JSON with sorted keys. Include `fetched_at` for immutable observation IDs; exclude it for canonical IDs.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_hk_financials_normalize.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hk_financials/schemas.py src/hk_financials/normalize.py tests/test_hk_financials_normalize.py
git commit -m "feat(hk-financials): define observation schemas"
```

---

### Task 3: Add partitioned Parquet storage and run manifests

**Files:**
- Create: `src/hk_financials/storage.py`
- Create: `tests/test_hk_financials_storage.py`

**Interfaces:**
- Produces: `write_partitioned_snapshot(dataset: str, source: str, snapshot_date: date, frame: pd.DataFrame, run_id: str) -> Path`
- Produces: `write_run_manifest(run_id: str, manifest: Mapping[str, object]) -> Path`
- Produces: `write_freshness_manifest(manifest: Mapping[str, object]) -> Path`
- Storage is append-only by `run_id`; rerunning the same `run_id` raises `FileExistsError`.

- [ ] **Step 1: Write failing storage tests**

```python
def test_write_partitioned_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PROCESSED_DIR", tmp_path)
    frame = pd.DataFrame([{"ticker": "0700.HK", "metric": "revenue", "value": 1.0}])
    path = storage.write_partitioned_snapshot(
        "observations", "yfinance", date(2026, 7, 26), frame, "run-1"
    )
    assert path.exists()
    assert "source=yfinance" in str(path)
    assert "snapshot_date=2026-07-26" in str(path)
    assert pd.read_parquet(path).equals(frame)


def test_same_run_id_cannot_overwrite_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PROCESSED_DIR", tmp_path)
    frame = pd.DataFrame([{"ticker": "0700.HK"}])
    storage.write_partitioned_snapshot("observations", "yfinance", date(2026, 7, 26), frame, "run-1")
    with pytest.raises(FileExistsError):
        storage.write_partitioned_snapshot("observations", "yfinance", date(2026, 7, 26), frame, "run-1")
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/test_hk_financials_storage.py -v`

Expected: FAIL because `storage.py` does not exist.

- [ ] **Step 3: Implement append-only storage**

Use this path shape:

```text
{PROCESSED_DIR}/{dataset}/source={source}/snapshot_date={YYYY-MM-DD}/{run_id}.parquet
```

Write Parquet to a temporary sibling file first and atomically rename it to the final path.

- [ ] **Step 4: Implement manifests**

Each run manifest must contain:

```json
{
  "run_id": "uuid",
  "started_at": "UTC timestamp",
  "finished_at": "UTC timestamp",
  "status": "success|partial|failed",
  "tickers_requested": 174,
  "tickers_succeeded": 170,
  "tickers_failed": 4,
  "sources": {
    "yfinance": {"status": "partial", "records": 120000, "errors": []}
  },
  "outputs": []
}
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_hk_financials_storage.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hk_financials/storage.py tests/test_hk_financials_storage.py
git commit -m "feat(hk-financials): add append-only Parquet storage"
```

---

### Task 4: Implement yfinance financial statements and dividends

**Files:**
- Create: `src/hk_financials/sources/__init__.py`
- Create: `src/hk_financials/sources/yfinance_financials.py`
- Create: `tests/test_hk_financials_yfinance.py`
- Create: `tests/fixtures/hk_financials/yfinance_income.json`
- Create: `tests/fixtures/hk_financials/yfinance_balance.json`
- Create: `tests/fixtures/hk_financials/yfinance_cashflow.json`

**Interfaces:**
- Produces: `fetch_yfinance_security(ticker: str, fetched_at: datetime) -> YFinanceFetchResult`
- Produces dataclass: `YFinanceFetchResult(observations: pd.DataFrame, dividends: pd.DataFrame, company_metadata: pd.DataFrame, errors: tuple[str, ...])`
- Must not call `Ticker.history()` or store OHLCV prices.

- [ ] **Step 1: Write mocked adapter tests**

```python
def test_yfinance_fetcher_normalizes_three_statements(monkeypatch):
    fake = FakeTicker.from_fixture_dir(FIXTURE_DIR)
    monkeypatch.setattr(yf, "Ticker", lambda _: fake)
    result = fetch_yfinance_security("0700.HK", FIXED_FETCH_TIME)
    assert set(result.observations["statement_type"]) == {
        "income", "balance_sheet", "cash_flow"
    }
    assert {"revenue", "net_income", "total_assets", "operating_cash_flow"} <= set(
        result.observations["metric"]
    )
    assert set(result.observations["source"]) == {"yfinance"}


def test_yfinance_partial_statement_failure_is_recorded(monkeypatch):
    fake = FakeTicker(income_stmt=RuntimeError("blocked"))
    monkeypatch.setattr(yf, "Ticker", lambda _: fake)
    result = fetch_yfinance_security("0700.HK", FIXED_FETCH_TIME)
    assert result.errors
    assert result.observations["statement_type"].isin(
        ["balance_sheet", "cash_flow"]
    ).all()
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/test_hk_financials_yfinance.py -v`

Expected: FAIL because the adapter is missing.

- [ ] **Step 3: Implement statement extraction**

Fetch annual and available quarterly/interim frames separately:

```python
STATEMENT_ACCESSORS = {
    ("income", "annual"): "income_stmt",
    ("income", "quarterly"): "quarterly_income_stmt",
    ("balance_sheet", "annual"): "balance_sheet",
    ("balance_sheet", "quarterly"): "quarterly_balance_sheet",
    ("cash_flow", "annual"): "cashflow",
    ("cash_flow", "quarterly"): "quarterly_cashflow",
}
```

Treat yfinance's non-annual periods as `interim` unless the source explicitly supplies a quarter label. Do not assume HK issuers report true quarterly statements.

- [ ] **Step 4: Normalize values and metadata**

Convert yfinance's metric-by-date frames to one row per metric and period. Preserve unknown metrics. Set `announcement_date = NULL`, `available_at = fetched_at`, and initial `point_in_time_quality = low`; Task 8 will improve availability using HKEX metadata.

- [ ] **Step 5: Extract dividends and company metadata**

Dividends output columns:

```text
ticker, ex_date, amount, currency, source, fetched_at
```

Metadata output columns:

```text
ticker, name_en, currency, exchange, quote_type, market_cap,
shares_outstanding, sector, industry, source, fetched_at
```

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_hk_financials_yfinance.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hk_financials/sources tests/test_hk_financials_yfinance.py tests/fixtures/hk_financials/yfinance_*.json
git commit -m "feat(hk-financials): ingest yfinance statements"
```

---

### Task 5: Implement AkShare financial indicators and dividend supplements

**Files:**
- Create: `src/hk_financials/sources/akshare_financials.py`
- Create: `tests/test_hk_financials_akshare.py`
- Create: `tests/fixtures/hk_financials/akshare_indicators.json`

**Interfaces:**
- Produces: `fetch_akshare_financials(ticker: str, fetched_at: datetime) -> AkShareFinancialResult`
- Uses only verified functions:
  - `stock_hk_financial_indicator_em`
  - `stock_financial_hk_analysis_indicator_em`
  - `stock_hk_dividend_payout_em`
- Must not call the broken `stock_financial_hk_report_em`.

- [ ] **Step 1: Write mocked AkShare tests**

```python
def test_akshare_financials_keep_short_history_indicators(monkeypatch):
    monkeypatch.setattr(
        ak,
        "stock_financial_hk_analysis_indicator_em",
        lambda symbol: fixture_analysis_frame(),
    )
    result = fetch_akshare_financials("0700.HK", FIXED_FETCH_TIME)
    assert not result.observations.empty
    assert set(result.observations["source"]) == {"akshare"}
    assert result.observations["fiscal_period_end"].notna().all()


def test_akshare_broken_full_report_function_is_never_called(monkeypatch):
    monkeypatch.setattr(
        ak,
        "stock_financial_hk_report_em",
        lambda *args, **kwargs: pytest.fail("broken function must not be called"),
        raising=False,
    )
    fetch_akshare_financials("0700.HK", FIXED_FETCH_TIME)
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/test_hk_financials_akshare.py -v`

Expected: FAIL because the adapter is missing.

- [ ] **Step 3: Implement ticker conversion and fetch isolation**

Convert `0700.HK` to the source-specific `00700`/`0700` code required by each AkShare function. Catch errors per function and return successful datasets alongside error messages.

- [ ] **Step 4: Normalize financial indicators**

Map reported dates to `fiscal_period_end`; use `statement_type = financial_indicator`. Preserve raw metric names and normalize known ROE, ROA, gross margin, net margin, EPS, BPS and dividend metrics.

- [ ] **Step 5: Normalize AkShare dividends**

Use the same dividend schema as yfinance so DuckDB can union the two sources.

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_hk_financials_akshare.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hk_financials/sources/akshare_financials.py tests/test_hk_financials_akshare.py tests/fixtures/hk_financials/akshare_indicators.json
git commit -m "feat(hk-financials): add AkShare financial supplements"
```

---

### Task 6: Implement broker forecasts and consensus snapshots

**Files:**
- Create: `src/hk_financials/sources/akshare_forecasts.py`
- Create: `src/hk_financials/sources/yfinance_consensus.py`
- Create: `tests/fixtures/hk_financials/akshare_broker_forecasts.json`
- Create: `tests/fixtures/hk_financials/yfinance_estimates.json`
- Extend: `tests/test_hk_financials_akshare.py`
- Extend: `tests/test_hk_financials_yfinance.py`

**Interfaces:**
- Produces: `fetch_akshare_forecasts(ticker: str, fetched_at: datetime) -> ForecastFetchResult`
- Produces: `fetch_yfinance_consensus(ticker: str, fetched_at: datetime) -> pd.DataFrame`
- Produces: `aggregate_broker_consensus(broker_rows: pd.DataFrame, snapshot_date: date) -> pd.DataFrame`
- Consensus failures are returned as errors and never raise out of the ticker pipeline.

- [ ] **Step 1: Write forecast and consensus tests**

```python
def test_akshare_forecasts_preserve_broker_rows(monkeypatch):
    monkeypatch.setattr(
        ak,
        "stock_hk_profit_forecast_et",
        lambda symbol, indicator: fixture_forecast_frame(indicator),
    )
    result = fetch_akshare_forecasts("0700.HK", FIXED_FETCH_TIME)
    assert {"broker_name", "rating", "target_price", "eps_forecast"} <= set(
        result.broker_forecasts.columns
    )
    assert len(result.broker_forecasts) > 1


def test_consensus_is_aggregated_by_ticker_and_fiscal_year():
    consensus = aggregate_broker_consensus(
        fixture_broker_rows(), date(2026, 7, 26)
    )
    row = consensus.query("ticker == '0700.HK' and fiscal_year == 2027").iloc[0]
    assert row["eps_avg"] == pytest.approx(3.0)
    assert row["num_brokers"] == 3
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```bash
pytest tests/test_hk_financials_akshare.py tests/test_hk_financials_yfinance.py -v
```

Expected: FAIL because forecast adapters do not exist.

- [ ] **Step 3: Implement AkShare forecast extraction**

Call:

```python
ak.stock_hk_profit_forecast_et(symbol=source_code, indicator="盈利预测概览")
ak.stock_hk_profit_forecast_et(symbol=source_code, indicator="综合盈利预测")
ak.stock_hk_profit_forecast_et(symbol=source_code, indicator="评级总览")
```

Store broker rows from `盈利预测概览`. Derive consensus from broker rows and retain the source's aggregate rows for validation.

- [ ] **Step 4: Implement yfinance consensus as optional observations**

Call available yfinance estimate methods through `getattr`:

```python
for method_name in (
    "get_earnings_estimate",
    "get_revenue_estimate",
    "get_eps_trend",
):
    method = getattr(ticker_object, method_name, None)
```

If a method is absent, returns `None`, or raises, record a source error and return an empty frame. Never fail the financial statement run.

- [ ] **Step 5: Run the tests**

Run:

```bash
pytest tests/test_hk_financials_akshare.py tests/test_hk_financials_yfinance.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hk_financials/sources/akshare_forecasts.py src/hk_financials/sources/yfinance_consensus.py tests
git commit -m "feat(hk-financials): capture consensus snapshots"
```

---

### Task 7: Implement HKEX filing metadata ingestion

**Files:**
- Create: `src/hk_financials/sources/hkex_filings.py`
- Create: `tests/test_hk_financials_hkex.py`
- Create: `tests/fixtures/hk_financials/hkex_title_search.json`

**Interfaces:**
- Produces: `fetch_hkex_filings(ticker: str, date_from: date, date_to: date, fetched_at: datetime) -> pd.DataFrame`
- Produces: `classify_hkex_document(title: str, document_type_code: str) -> str`
- Fetches metadata only; no PDF download.

- [ ] **Step 1: Write HKEX parser tests**

```python
def test_parse_hkex_nested_result_json():
    payload = json.loads((FIXTURE_DIR / "hkex_title_search.json").read_text())
    frame = parse_hkex_title_search(payload, "0005.HK", FIXED_FETCH_TIME)
    assert {"news_id", "announcement_date", "title", "pdf_url"} <= set(frame.columns)
    assert frame["ticker"].eq("0005.HK").all()


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("ANNUAL REPORT 2025", "annual_report"),
        ("INTERIM REPORT 2026", "interim_report"),
        ("ANNUAL RESULTS ANNOUNCEMENT", "results_announcement"),
        ("POLL RESULTS", "other"),
    ],
)
def test_classify_hkex_document(title, expected):
    assert classify_hkex_document(title, "-1") == expected
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/test_hk_financials_hkex.py -v`

Expected: FAIL because the HKEX adapter is missing.

- [ ] **Step 3: Implement the title-search request**

Use `requests.Session` with timeout 30 seconds and explicit parameters:

```python
params = {
    "stockId": ticker.removesuffix(".HK"),
    "from": date_from.strftime("%Y%m%d"),
    "to": date_to.strftime("%Y%m%d"),
    "category": "0",
    "market": "SEHK",
    "documentType": "-1",
    "rowRange": "0-100",
    "lang": "EN",
}
```

Follow pagination until `totalCount` rows are parsed. Normalize relative PDF URLs against `https://www1.hkexnews.hk`.

- [ ] **Step 4: Ensure PDFs are not downloaded**

Add a test that injects a fake session recording requested URLs and asserts every request targets `titleSearchServlet.do`.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/test_hk_financials_hkex.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/hk_financials/sources/hkex_filings.py tests/test_hk_financials_hkex.py tests/fixtures/hk_financials/hkex_title_search.json
git commit -m "feat(hk-financials): index HKEX filing metadata"
```

---

### Task 8: Assign point-in-time availability and canonical values

**Files:**
- Create: `src/hk_financials/availability.py`
- Create: `src/hk_financials/canonical.py`
- Create: `src/hk_financials/quality.py`
- Create: `tests/test_hk_financials_availability.py`
- Create: `tests/test_hk_financials_canonical.py`

**Interfaces:**
- Produces: `assign_availability(observations: pd.DataFrame, filings: pd.DataFrame) -> pd.DataFrame`
- Produces: `build_canonical_facts(observations: pd.DataFrame, generated_at: datetime) -> tuple[pd.DataFrame, pd.DataFrame]`
- Returns canonical facts and conflict rows.

- [ ] **Step 1: Write availability tests**

```python
def test_exact_results_announcement_sets_high_quality():
    enriched = assign_availability(
        fixture_observation(period_end="2025-12-31"),
        fixture_filing(title="ANNUAL RESULTS ANNOUNCEMENT", date="2026-03-20"),
    )
    assert enriched.iloc[0]["available_at"] == pd.Timestamp("2026-03-20", tz="UTC")
    assert enriched.iloc[0]["point_in_time_quality"] == "high"


def test_report_date_sets_medium_quality():
    enriched = assign_availability(
        fixture_observation(period_end="2025-12-31"),
        fixture_filing(title="ANNUAL REPORT 2025", date="2026-04-15"),
    )
    assert enriched.iloc[0]["point_in_time_quality"] == "medium"


def test_missing_filing_uses_conservative_lag():
    enriched = assign_availability(fixture_observation(period_end="2025-12-31"), empty_filings())
    assert enriched.iloc[0]["available_at"] == pd.Timestamp("2026-06-29", tz="UTC")
    assert enriched.iloc[0]["point_in_time_quality"] == "low"
```

Use conservative fallbacks:

```text
annual: period_end + 180 days
interim/quarterly: period_end + 120 days
unknown: max(fetched_at, period_end + 180 days)
```

- [ ] **Step 2: Write canonical conflict tests**

```python
def test_canonical_keeps_yfinance_and_records_material_conflict():
    observations = pd.DataFrame([
        observation(source="yfinance", value=100.0),
        observation(source="akshare", value=110.0),
    ])
    canonical, conflicts = build_canonical_facts(observations, FIXED_FETCH_TIME)
    assert canonical.iloc[0]["value"] == 100.0
    assert canonical.iloc[0]["canonical_source"] == "yfinance"
    assert canonical.iloc[0]["conflict_status"] == "material"
    assert len(conflicts) == 1


def test_values_within_half_percent_are_not_material():
    observations = pd.DataFrame([
        observation(source="yfinance", value=100.0),
        observation(source="akshare", value=100.4),
    ])
    canonical, _ = build_canonical_facts(observations, FIXED_FETCH_TIME)
    assert canonical.iloc[0]["conflict_status"] == "within_tolerance"
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
pytest tests/test_hk_financials_availability.py tests/test_hk_financials_canonical.py -v
```

Expected: FAIL because the modules are missing.

- [ ] **Step 4: Implement availability matching**

Match by ticker, annual/interim document type and the fiscal year embedded in the filing title. Prefer results announcements over reports. Do not assign an official date when fiscal-year matching is ambiguous.

- [ ] **Step 5: Implement canonical source rules**

Use deterministic priorities:

```python
SOURCE_PRIORITY = {
    "income": ("yfinance", "akshare"),
    "balance_sheet": ("yfinance", "akshare"),
    "cash_flow": ("yfinance", "akshare"),
    "financial_indicator": ("akshare", "yfinance"),
}
```

Select the newest observation from the highest-priority available source. Calculate relative difference after currency and scale normalization. Sign differences are always material conflicts.

- [ ] **Step 6: Implement quality summaries**

Compute:

```text
annual_any_statement_coverage
three_statement_coverage
point_in_time_high_pct
point_in_time_medium_pct
point_in_time_low_pct
material_conflict_count
duplicate_observation_count
```

- [ ] **Step 7: Run the tests**

Run:

```bash
pytest tests/test_hk_financials_availability.py tests/test_hk_financials_canonical.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/hk_financials/availability.py src/hk_financials/canonical.py src/hk_financials/quality.py tests/test_hk_financials_availability.py tests/test_hk_financials_canonical.py
git commit -m "feat(hk-financials): reconcile point-in-time facts"
```

---

### Task 9: Build the generated DuckDB database and research views

**Files:**
- Create: `src/hk_financials/duckdb_builder.py`
- Create: `tests/test_hk_financials_duckdb.py`

**Interfaces:**
- Produces: `build_database(database_path: Path, processed_dir: Path, reference_dir: Path) -> Path`
- Rebuilds into a temporary database and atomically replaces the target.

- [ ] **Step 1: Write failing DuckDB tests**

```python
def test_build_database_creates_required_views(tmp_path):
    seed_parquet_fixtures(tmp_path)
    db_path = build_database(
        tmp_path / "hk_financials.duckdb",
        tmp_path / "processed",
        tmp_path / "reference",
    )
    with duckdb.connect(str(db_path), read_only=True) as con:
        names = {row[0] for row in con.execute("SHOW ALL TABLES").fetchall()}
    assert {
        "securities",
        "financial_observations",
        "canonical_financial_facts",
        "financial_summary_annual",
        "financial_summary_interim",
        "broker_forecasts",
        "consensus_snapshots",
        "consensus_revisions",
        "hkex_filings",
        "data_coverage",
    } <= names
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests/test_hk_financials_duckdb.py -v`

Expected: FAIL because the builder is missing.

- [ ] **Step 3: Implement Parquet-backed source views**

Use `read_parquet(..., union_by_name=true, hive_partitioning=true)` for committed source data. For a dataset with no files, create an empty typed table using its schema contract so database builds remain deterministic.

- [ ] **Step 4: Implement canonical materialization**

Load observation frames, call `assign_availability` and `build_canonical_facts`, and write materialized DuckDB tables:

```text
canonical_financial_facts
financial_conflicts
data_coverage
```

- [ ] **Step 5: Implement research views**

`financial_summary_annual` and `financial_summary_interim` pivot these metrics:

```text
revenue, gross_profit, operating_income, net_income,
basic_eps, diluted_eps, total_assets, total_debt,
cash_and_equivalents, shareholders_equity,
operating_cash_flow, capital_expenditure, free_cash_flow
```

`consensus_revisions` uses `lag()` over `ticker, fiscal_year, source` ordered by `snapshot_date` to expose:

```text
eps_avg_change_1_snapshot
eps_avg_change_pct_1_snapshot
net_income_avg_change_1_snapshot
target_price_avg_change_1_snapshot
```

- [ ] **Step 6: Run the DuckDB tests**

Run: `pytest tests/test_hk_financials_duckdb.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hk_financials/duckdb_builder.py tests/test_hk_financials_duckdb.py
git commit -m "feat(hk-financials): build DuckDB research views"
```

---

### Task 10: Add fault-isolated pipelines and CLI commands

**Files:**
- Create: `src/hk_financials/pipeline.py`
- Create: `src/hk_financials/cli.py`
- Create: `tests/test_hk_financials_pipeline.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `run_financials(tickers: Sequence[str] | None = None, run_id: str | None = None) -> RunResult`
- Produces: `run_consensus(tickers: Sequence[str] | None = None, run_id: str | None = None) -> RunResult`
- Produces: `run_hkex(date_from: date, date_to: date, tickers: Sequence[str] | None = None, run_id: str | None = None) -> RunResult`
- Produces CLI commands: `build-universe`, `run-financials`, `run-consensus`, `run-hkex`, `build-db`, `validate`

- [ ] **Step 1: Write pipeline isolation tests**

```python
def test_one_ticker_failure_does_not_stop_remaining_tickers(monkeypatch):
    monkeypatch.setattr(pipeline, "load_reference_tickers", lambda: ["0005.HK", "0700.HK"])
    monkeypatch.setattr(
        pipeline,
        "fetch_yfinance_security",
        lambda ticker, fetched_at: (
            (_ for _ in ()).throw(RuntimeError("blocked"))
            if ticker == "0005.HK"
            else successful_yfinance_result(ticker)
        ),
    )
    result = pipeline.run_financials(run_id="run-1")
    assert result.status == "partial"
    assert result.tickers_succeeded == 1
    assert result.tickers_failed == 1


def test_consensus_failure_never_changes_financials_status(monkeypatch):
    result = pipeline.run_consensus(
        tickers=["0700.HK"],
        run_id="run-consensus",
    )
    assert result.status in {"success", "partial", "failed"}
```

- [ ] **Step 2: Run the tests and verify failure**

Run: `pytest tests/test_hk_financials_pipeline.py -v`

Expected: FAIL because pipeline and CLI modules are missing.

- [ ] **Step 3: Implement orchestration**

Each ticker executes in its own `try/except`. Write successful source frames even when another source or ticker fails. After all tickers complete, write the run manifest and freshness manifest.

Status rules:

```text
success: all attempted source/ticker jobs succeeded
partial: at least one succeeded and at least one failed
failed: no ticker produced any requested dataset
```

- [ ] **Step 4: Implement CLI**

Add this script entry:

```toml
hk-financials-data = "hk_financials.cli:main"
```

Commands:

```bash
hk-financials-data build-universe
hk-financials-data run-financials
hk-financials-data run-consensus
hk-financials-data run-hkex --from 2026-07-25 --to 2026-07-26
hk-financials-data build-db
hk-financials-data validate
```

`--ticker 0700.HK` may be repeated for focused local debugging. Scheduled runs omit it and use all 174 securities.

- [ ] **Step 5: Implement validation exit codes**

```text
0: success or partial with annual coverage >= 80%
1: failed run, invalid schema, duplicate keys, or annual coverage < 80%
2: invalid CLI arguments
```

Consensus coverage never determines the financials validation exit code.

- [ ] **Step 6: Run pipeline tests**

Run: `pytest tests/test_hk_financials_pipeline.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/hk_financials/pipeline.py src/hk_financials/cli.py tests/test_hk_financials_pipeline.py pyproject.toml
git commit -m "feat(hk-financials): add pipeline CLI"
```

---

### Task 11: Add weekly and daily GitHub Actions workflows

**Files:**
- Create: `.github/workflows/hk-financials-weekly.yml`
- Create: `.github/workflows/hk-financials-hkex-daily.yml`

**Interfaces:**
- Weekly workflow writes yfinance/AkShare financial and consensus Parquet snapshots.
- Daily workflow writes HKEX metadata snapshots.
- Both commit only `data/reference/hk_financials/` and `data/processed/hk_financials/`.
- Neither workflow commits `data/databases/`.

- [ ] **Step 1: Add the weekly workflow**

Schedule Sunday 06:15 UTC and allow manual ticker input:

```yaml
name: HK Financials Weekly

on:
  schedule:
    - cron: "15 6 * * 0"
  workflow_dispatch:
    inputs:
      ticker:
        description: "Optional single ticker, e.g. 0700.HK"
        required: false
        default: ""

permissions:
  contents: write
```

Run:

```bash
hk-financials-data build-universe
hk-financials-data run-financials
hk-financials-data run-consensus
hk-financials-data validate
```

Pass `--ticker` only when the workflow input is non-empty.

- [ ] **Step 2: Add the daily HKEX workflow**

Schedule daily 05:40 UTC. Query a three-day lookback to tolerate delayed publication and weekend boundaries:

```bash
DATE_TO=$(date -u +%Y-%m-%d)
DATE_FROM=$(date -u -d '3 days ago' +%Y-%m-%d)
hk-financials-data run-hkex --from "$DATE_FROM" --to "$DATE_TO"
```

Use a small Python date helper on macOS/local documentation; GitHub Actions runs Ubuntu and supports the command above.

- [ ] **Step 3: Add safe commit logic**

Both workflows:

```bash
git add data/reference/hk_financials data/processed/hk_financials
if git diff --staged --quiet; then
  exit 0
fi
git commit -m "chore: update HK financials [$(date -u +%Y-%m-%d)]"
git pull --rebase origin "${{ github.event.repository.default_branch }}"
git push
```

- [ ] **Step 4: Validate YAML and commands**

Run:

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/hk-financials-weekly.yml')); yaml.safe_load(open('.github/workflows/hk-financials-hkex-daily.yml'))"
python -m hk_financials.cli --help
```

Expected: both YAML files parse and the CLI lists all commands.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/hk-financials-weekly.yml .github/workflows/hk-financials-hkex-daily.yml
git commit -m "ci: schedule HK financials ingestion"
```

---

### Task 12: Add documentation and end-to-end acceptance tests

**Files:**
- Create: `docs/asia-markets/database/README.md`
- Modify: `docs/asia-markets/README.md`
- Extend: `tests/test_hk_financials_pipeline.py`
- Extend: `tests/test_hk_financials_duckdb.py`

**Interfaces:**
- Documents local setup, scheduled behavior, data contracts, source limitations, point-in-time semantics and DuckDB queries.
- Provides a mocked two-ticker end-to-end test.

- [ ] **Step 1: Write the end-to-end test**

```python
def test_end_to_end_two_ticker_database(tmp_path, monkeypatch):
    configure_temp_paths(tmp_path, monkeypatch)
    seed_reference_universe(["0005.HK", "0700.HK"])
    install_mock_source_adapters(monkeypatch)

    financial_run = run_financials(run_id="financial-run")
    consensus_run = run_consensus(run_id="consensus-run")
    hkex_run = run_hkex(
        date(2026, 1, 1),
        date(2026, 7, 26),
        run_id="hkex-run",
    )
    db_path = build_database(
        tmp_path / "hk_financials.duckdb",
        tmp_path / "processed",
        tmp_path / "reference",
    )

    assert financial_run.status == "success"
    assert consensus_run.status == "success"
    assert hkex_run.status == "success"

    with duckdb.connect(str(db_path), read_only=True) as con:
        annual = con.execute(
            "SELECT ticker, revenue, net_income "
            "FROM financial_summary_annual ORDER BY ticker"
        ).fetchdf()
        revisions = con.execute(
            "SELECT * FROM consensus_revisions ORDER BY ticker, snapshot_date"
        ).fetchdf()

    assert list(annual["ticker"]) == ["0005.HK", "0700.HK"]
    assert not revisions.empty
```

- [ ] **Step 2: Run the complete HK financials test suite**

Run:

```bash
pytest tests/test_hk_financials_*.py -v
```

Expected: PASS with no live network calls.

- [ ] **Step 3: Write operating documentation**

Document:

- source roles and known limitations;
- all CLI commands;
- GitHub Actions schedules;
- Parquet paths;
- generated DuckDB path;
- conflict and point-in-time quality definitions;
- how to inspect failed tickers from run manifests;
- why HKEX PDFs are indexed but not parsed;
- why prices and alternative data are outside V1.

Include working queries:

```sql
SELECT *
FROM financial_summary_annual
WHERE ticker = '0700.HK'
ORDER BY fiscal_period_end;

SELECT *
FROM financial_conflicts
WHERE conflict_status = 'material'
ORDER BY fiscal_period_end DESC;

SELECT *
FROM consensus_revisions
WHERE ticker = '0700.HK'
ORDER BY snapshot_date;
```

- [ ] **Step 4: Link the database documentation from the Asia Markets index**

Add:

```markdown
- [HK financials database V1](database/README.md)
- [HK financials implementation plan](database/2026-07-26-hk-financials-v1-implementation-plan.md)
```

- [ ] **Step 5: Run repository verification**

Run:

```bash
pytest tests/test_hk_financials_*.py -q
python -m hk_financials.cli --help
hk-financials-data build-universe
hk-financials-data build-db
hk-financials-data validate
git diff --check -- src/hk_financials tests/test_hk_financials_*.py docs/asia-markets/database .github/workflows/hk-financials-*.yml
```

Expected:

- all tests pass;
- the CLI lists six commands;
- the reference universe contains 174 securities;
- the generated DuckDB opens read-only;
- validation reports source coverage and does not require prices or alternative data;
- no whitespace errors in V1 files.

- [ ] **Step 6: Commit**

```bash
git add docs/asia-markets/database docs/asia-markets/README.md tests/test_hk_financials_pipeline.py tests/test_hk_financials_duckdb.py
git commit -m "docs: document HK financials database V1"
```

---

## V1 Acceptance Criteria

- The machine-readable universe contains exactly 174 unique HK tickers with English and Chinese names.
- A scheduled financial run attempts all 174 securities and records every per-ticker success or failure.
- At least 80% of active securities have at least one annual financial statement from yfinance or AkShare.
- At least 70% of active securities have income, balance-sheet and cash-flow observations for at least one annual period.
- Every financial source row records `source`, `fetched_at`, `fiscal_period_end`, `available_at` and `point_in_time_quality`.
- yfinance and AkShare conflicts remain queryable after canonical selection.
- HKEX metadata includes official announcement dates and PDF URLs without PDF value parsing.
- Broker rows and consensus snapshots are independently stored; missing consensus never blocks financial statements.
- Repeated weekly snapshots create a queryable consensus revision history.
- GitHub Actions commit only Parquet/reference/manifest outputs, never the DuckDB binary.
- The DuckDB database is reproducibly generated from committed Parquet files.
- The default test suite performs no live network requests.

