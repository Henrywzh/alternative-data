# Chinese Airline KPI Backtest: Source-Disclosure Audit & Improvements

Status: complete (2026-08-09). Scope: the 22 Juneyao 2016 missing cells, parser
gaps found during the audit, and the H1/H2/FY KPI-to-earnings backtest.

## 1. Juneyao 2016: 22 missing cells are genuine source non-disclosures

| Item | Value |
|---|---|
| Missing cells | 22 (11 AFTK + 11 freight-load-factor) |
| Months | 2016-01 .. 2016-11 |
| Carrier | Juneyao Airlines (603885) |
| Verdict | **Genuine non-disclosure, not a parser gap** (high confidence) |
| Evidence | `pdftotext` on all 11 cached CNINFO PDFs returns **zero** hits for `可用货邮/可用货运/AFTK` |

The 2016-01..11 announcements disclose ATK/ASK/RTK/RPK/RFTK, cargo tonnage,
overall load factor and passenger load factor, but **not** AFTK. Freight load
factor = RFTK/AFTK cannot be derived without it. The format changed in
2016-12 (`1203025921.PDF`), which is the first month disclosing AFTK and
freight load factor. The parser's `_AFTK_KEYWORDS` contains the Chinese
keywords and parses 2016-12 correctly (52.7483), so a disclosure would have
been captured.

These 22 cells remain `missing/not_filled` in the imputed layer. They are not
interpolated.

## 2. Parser gaps found during the audit (now fixed)

| Location | Metric | Root cause | Fix |
|---|---|---|---|
| 600115 2025-05/07 | AFTK | Abbreviated header `里（AFTK）（百万）` not in Chinese keyword list | Added `（AFTK）`/`(AFTK)`/`（RFTK）`/`(RFTK)` keywords |
| 603885 2020-12/2023-12/2024-01 | AFTK | Same abbreviated-header issue | Same |
| 603885 2017-04/08/12, 2018-02, 2023-03 | Freight load factor | Header wraps as `货物及邮件载运` + `率` across pages | Added `货物及邮件载运` keyword + continuation handling for the lone `率` row |
| 601021 2016-04/2017-04/2018-02 | Freight load factor | Value in third column, not second (Spring layout) | `_first_value_cell` scans for the current-period numeric cell |
| 601111 2023-10 | RFTK | pdfplumber drops the row from the table structure | Text-layer recovery |
| 600029 2020-01/10, 2017-10, 2020-02/09, 2020-12, 2021-05/07 | AFTK/FLF/RFTK Total | pdfplumber drops the 合计 Total row | Regional-sum recovery in the source-recovered layer |

All 751 cached PDFs were re-parsed; 1,384 additional (metric, region) keys are
now present and 204 previously-wrong cells (mostly Spring load factors recorded
as 0.0) are corrected. The only remaining raw-vs-recovered Total discrepancy is
600029 2016-11 RPK, where the issuer's own printed total (16,705.86) differs
from the printed regional sum (16,699.86) — the parser preserves the official
printed value.

## 3. Data-layer rebuild

- Raw archive (`china_airlines_monthly.parquet`) rebuilt offline from the 751
  cached PDFs with the fixed parser: **31,823 rows**.
- Source-recovered layer rebuilt: **178 recovered rows** (was 46) + 22
  undisclosed rows.
- Imputed layer rebuilt (8,261 rows; Juneyao 2016 AFTK/FLF remain unfilled).
- H1 backtest and the new H1/H2/FY period backtest re-run.

## 4. Backtest results (strict, source-recovered layer)

Revenue MAE by period and model (|%|, historical 2017-2025 evaluated rows):

| Company | Period | Evaluated | flat ASK | flat RPK | Spring recovery |
|---|---:|---:|---:|---:|
| Spring Airlines | H1 | 9 | 9.57 | 7.42 | **6.51** |
| Spring Airlines | H2 | 9 | 11.95 | 10.75 | **9.92** |
| Spring Airlines | FY | 9 | 10.09 | 7.92 | **6.95** |
| Juneyao | H1 | 9 | 6.50 | 8.15 | — |
| Juneyao | H2 | 9 | 9.92 | 8.91 | — |
| Juneyao | FY | 9 | 7.26 | 5.62 | — |
| Air China | H1 | 9 | 4.88 | 11.55 | — |
| China Southern | H1 | 9 | 4.52 | 12.21 | — |
| China Eastern | H1 | 9 | 4.38 | 9.57 | — |

Key changes after the parser repair:

- Juneyao evaluated rows jumped from 1 FY / 5 H1 / 2 H2 to **9 / 9 / 9**
  (the ASK/RPK Total parsing gap was blocking most years).
- Spring H1 operating-cost MAE fell from ~11.5% to **8.3%** (ASK Total now
  official, not region-summed).
- All 27 Spring diagnostics rows are now PIT-safe.

Spring's high MAE is concentrated in the 2023 reopening (H1 2023 flat-ASK
revenue error -31.9%; RPK -17.5%). The `spring_recovery_case` (pre-declared
+10% yield premium when RPK-ASK gap and load-factor lift both exceed
thresholds) cuts that to -9.3%. This is a transparent sensitivity, not a
fitted target.

## 5. H2 = FY - H1 verification

H2 financial rows are derived as FY minus H1 and verified to match to <1
currency unit on every evaluated company-year. H2 operating KPIs use the
issuer's own July-December monthly releases.

## Key files

- Parser: `scripts/scrape_cn_airline_traffic.py`
- Recovery: `scripts/recover_cn_airline_source_gaps.py`
- H1 backtest: `src/hk_transport/sources/airline_h1_kpi_backtest.py`
- H1/H2/FY backtest: `src/hk_transport/sources/airline_period_kpi_backtest.py`
- Tests: `tests/test_hk_transport_airline_period_kpi_backtest.py`,
  `tests/test_hk_transport_airline_source_recovery.py`
- Outputs: `data/normalized/hk_transport/airline_period_kpi_backtest*.csv`,
  `airline_spring_mae_diagnostics.csv`, `airline_h1_kpi_backtest*.csv`
