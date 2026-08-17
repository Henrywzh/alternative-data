"""
MTR Historical Annual Earnings Bridge (FY2010 - FY2025)
========================================================

Purpose
-------
Reconstructs MTR's (66.HK) annual income-statement bridge for the 16 fiscal
years 2010-2025 from official MTR published results, so that every operational
KPI (patronage, property handover, HIBOR, fares) can be mapped to the exact
earnings line it drives.

Every value in this module was hand-verified on 2026-08-09 against official
MTR PDFs downloaded from mtr.com.hk:
  * 2020-2025: full "Announcement of Audited Results" (Consolidated Statement
    of Profit or Loss), e.g. e_Annual_Results_2025.pdf.
  * 2010-2019: official analyst results presentations (e.g. mtr_2016_final_eng_web.pdf).
Values are HK$ million except EPS / DPS (HK$).

Accounting architecture (MTR-specific):
  * Property development is NOT booked as top-line revenue; it appears as the
    separate "Hong Kong property development profit" line (share of surplus /
    income / interest in unsold properties).
  * Recurrent businesses = HK transport operations + station commercial +
    property rental & management + other + (Mainland & international
    subsidiaries). Associates/JVs (e.g. Beijing lines) contribute only via
    "Share of profit of associates and joint ventures".
  * Reported NPAT = underlying businesses profit + investment-property fair
    value movements (+ one-offs / impairments).

Known source conventions / caveats:
  * 2016-2018 decks disclose HK station commercial and HK property rental as a
    MERGED revenue line (hk_station_plus_rental_rev); 2014/2015 and 2020+
    disclose them separately.
  * 2010-2013 decks disclose only total revenue and "revenue before Mainland
    of China & international subsidiaries", so segment revenue rows are NULL.
  * hk_pdp_pre_tax is the gross "share of surplus" profit; hk_pdp_post_tax is
    profit attributable to shareholders (2016-2025 includes Mainland China
    property development for 2016-2018 per official disclosure convention).
  * recurrent_post_tax_profit is profit from recurrent businesses after tax
  (attributable to shareholders); recurrent_op_profit is "operating profit arising from recurrent
    businesses" BEFORE depreciation, amortisation and variable annual payment
    for 2019-2025; for 2017-2018 it is "EBIT on recurrent businesses" AFTER
    D&A / VAP per the decks.
  * 2012 figures are restated under revised HKAS19 (as per the 2013 deck);
    2011 reported NPAT uses the 2011 deck's own figure (14,716).
  * 2014 DPS (1.05) is from public record (the 2015 deck does not print it).
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
os.makedirs(OUT_DIR, exist_ok=True)

CSV_PATH = os.path.join(OUT_DIR, "mtr_historical_earnings_bridge.csv")

# ---------------------------------------------------------------------------
# Hand-verified official data, FY2010 - FY2025 (HK$ million; EPS/DPS in HK$)
# ---------------------------------------------------------------------------
MTR_ANNUAL_DATA: list[dict[str, Any]] = [
    dict(year=2010, recurrent_post_tax_profit=None, total_revenue=29518, hk_transport_rev=None, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=None, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=None, other_rev=None, mainland_china_property_dev_rev=None,
         recurrent_op_profit=None, hk_pdp_pre_tax=4034, hk_pdp_post_tax=None,
         underlying_profit=8657, ip_fv_revaluation=None, reported_npat=12059, eps_basic=2.10,
         dps=0.59, pbt=14762, finance_costs=None, tax=None),
    dict(year=2011, recurrent_post_tax_profit=None, total_revenue=33423, hk_transport_rev=None, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=None, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=None, other_rev=None, mainland_china_property_dev_rev=None,
         recurrent_op_profit=None, hk_pdp_pre_tax=4934, hk_pdp_post_tax=None,
         underlying_profit=10468, ip_fv_revaluation=None, reported_npat=14716, eps_basic=2.55,
         dps=0.76, pbt=17669, finance_costs=None, tax=None),
    dict(year=2012, recurrent_post_tax_profit=6914, total_revenue=35739, hk_transport_rev=None, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=None, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=None, other_rev=None, mainland_china_property_dev_rev=None,
         recurrent_op_profit=None, hk_pdp_pre_tax=3238, hk_pdp_post_tax=None,
         underlying_profit=9618, ip_fv_revaluation=None, reported_npat=13375, eps_basic=2.31,
         dps=0.79, pbt=15376, finance_costs=None, tax=None),
    dict(year=2013, recurrent_post_tax_profit=7437, total_revenue=38707, hk_transport_rev=None, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=None, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=None, other_rev=None, mainland_china_property_dev_rev=None,
         recurrent_op_profit=None, hk_pdp_pre_tax=1396, hk_pdp_post_tax=None,
         underlying_profit=8600, ip_fv_revaluation=None, reported_npat=13025, eps_basic=2.25,
         dps=0.92, pbt=15027, finance_costs=None, tax=None),
    dict(year=2014, recurrent_post_tax_profit=8024, total_revenue=40156, hk_transport_rev=16223, hk_station_commercial_rev=4963,
         hk_property_rental_mgmt_rev=4190, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=12627, other_rev=2153, mainland_china_property_dev_rev=None,
         recurrent_op_profit=15478, hk_pdp_pre_tax=4216, hk_pdp_post_tax=3547,
         underlying_profit=11571, ip_fv_revaluation=4035, reported_npat=15606, eps_basic=2.69,
         dps=1.05, pbt=18293, finance_costs=545, tax=2496),
    dict(year=2015, recurrent_post_tax_profit=8565, total_revenue=41701, hk_transport_rev=16916, hk_station_commercial_rev=5380,
         hk_property_rental_mgmt_rev=4533, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=12572, other_rev=2300, mainland_china_property_dev_rev=None,
         recurrent_op_profit=16260, hk_pdp_pre_tax=2891, hk_pdp_post_tax=2329,
         underlying_profit=10894, ip_fv_revaluation=2100, reported_npat=12994, eps_basic=2.22,
         dps=1.06, pbt=15375, finance_costs=599, tax=2237),
    dict(year=2016, recurrent_post_tax_profit=8916, total_revenue=45189, hk_transport_rev=16545, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=None, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=None, other_rev=None, mainland_china_property_dev_rev=1348,
         recurrent_op_profit=None, hk_pdp_pre_tax=None, hk_pdp_post_tax=530,
         underlying_profit=9446, ip_fv_revaluation=808, reported_npat=10254, eps_basic=1.74,
         dps=1.07, pbt=None, finance_costs=None, tax=None),
    dict(year=2017, recurrent_post_tax_profit=8580, total_revenue=55440, hk_transport_rev=18201, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=4900, hk_station_plus_rental_rev=10875,
         mainland_intl_subsidiaries_rev=17194, other_rev=2174, mainland_china_property_dev_rev=6996,
         recurrent_op_profit=11740, hk_pdp_pre_tax=None, hk_pdp_post_tax=1935,
         underlying_profit=10515, ip_fv_revaluation=6314, reported_npat=16829, eps_basic=2.83,
         dps=1.12, pbt=None, finance_costs=None, tax=None),
    dict(year=2018, recurrent_post_tax_profit=9020, total_revenue=53930, hk_transport_rev=19490, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=None, hk_station_plus_rental_rev=11513,
         mainland_intl_subsidiaries_rev=20877, other_rev=1990, mainland_china_property_dev_rev=60,
         recurrent_op_profit=12553, hk_pdp_pre_tax=2574, hk_pdp_post_tax=2243,
         underlying_profit=11263, ip_fv_revaluation=4745, reported_npat=16008, eps_basic=2.64,
         dps=1.20, pbt=None, finance_costs=None, tax=None),
    dict(year=2019, recurrent_post_tax_profit=4980, total_revenue=54504, hk_transport_rev=19938, hk_station_commercial_rev=None,
         hk_property_rental_mgmt_rev=None, hk_station_plus_rental_rev=11936,
         mainland_intl_subsidiaries_rev=21085, other_rev=1545, mainland_china_property_dev_rev=0,
         recurrent_op_profit=15351, hk_pdp_pre_tax=5707, hk_pdp_post_tax=5580,
         underlying_profit=10560, ip_fv_revaluation=1372, reported_npat=11932, eps_basic=1.94,
         dps=1.23, pbt=14014, finance_costs=859, tax=1922),
    dict(year=2020, recurrent_post_tax_profit=-1126, total_revenue=42541, hk_transport_rev=11896, hk_station_commercial_rev=3269,
         hk_property_rental_mgmt_rev=5054, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=21428, other_rev=894, mainland_china_property_dev_rev=0,
         recurrent_op_profit=5194, hk_pdp_pre_tax=6491, hk_pdp_post_tax=5507,
         underlying_profit=4381, ip_fv_revaluation=-9190, reported_npat=-4809, eps_basic=-0.78,
         dps=1.23, pbt=-3520, finance_costs=1004, tax=1301),
    dict(year=2021, recurrent_post_tax_profit=1808, total_revenue=47202, hk_transport_rev=13177, hk_station_commercial_rev=3208,
         hk_property_rental_mgmt_rev=5036, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=25045, other_rev=383, mainland_china_property_dev_rev=353,
         recurrent_op_profit=8019, hk_pdp_pre_tax=11097, hk_pdp_post_tax=9343,
         underlying_profit=11151, ip_fv_revaluation=-1616, reported_npat=9552, eps_basic=1.55,
         dps=1.27, pbt=11940, finance_costs=967, tax=2261),
    dict(year=2022, recurrent_post_tax_profit=157, total_revenue=47812, hk_transport_rev=13404, hk_station_commercial_rev=3077,
         hk_property_rental_mgmt_rev=4779, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=26016, other_rev=363, mainland_china_property_dev_rev=173,
         recurrent_op_profit=7852, hk_pdp_pre_tax=11589, hk_pdp_post_tax=10480,
         underlying_profit=10637, ip_fv_revaluation=-810, reported_npat=9827, eps_basic=1.59,
         dps=1.31, pbt=11749, finance_costs=982, tax=1608),
    dict(year=2023, recurrent_post_tax_profit=4281, total_revenue=56982, hk_transport_rev=20131, hk_station_commercial_rev=5117,
         hk_property_rental_mgmt_rev=5079, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=25955, other_rev=700, mainland_china_property_dev_rev=0,
         recurrent_op_profit=15323, hk_pdp_pre_tax=2329, hk_pdp_post_tax=2083,
         underlying_profit=6364, ip_fv_revaluation=1386, reported_npat=7784, eps_basic=1.26,
         dps=1.31, pbt=9663, finance_costs=1139, tax=1575),
    dict(year=2024, recurrent_post_tax_profit=7210, total_revenue=60011, hk_transport_rev=23013, hk_station_commercial_rev=5343,
         hk_property_rental_mgmt_rev=5379, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=25467, other_rev=809, mainland_china_property_dev_rev=0,
         recurrent_op_profit=17907, hk_pdp_pre_tax=12185, hk_pdp_post_tax=10265,
         underlying_profit=17475, ip_fv_revaluation=-1703, reported_npat=15772, eps_basic=2.54,
         dps=1.31, pbt=19525, finance_costs=1032, tax=3458),
    dict(year=2025, recurrent_post_tax_profit=5653, total_revenue=55465, hk_transport_rev=23595, hk_station_commercial_rev=5345,
         hk_property_rental_mgmt_rev=5067, hk_station_plus_rental_rev=None,
         mainland_intl_subsidiaries_rev=20686, other_rev=758, mainland_china_property_dev_rev=14,
         recurrent_op_profit=17701, hk_pdp_pre_tax=13212, hk_pdp_post_tax=11084,
         underlying_profit=16737, ip_fv_revaluation=-2060, reported_npat=14677, eps_basic=2.36,
         dps=1.31, pbt=18917, finance_costs=1006, tax=3359),
]


def load_mtr_historical_earnings_bridge() -> pd.DataFrame:
    """Return the normalized annual MTR earnings bridge (2010-2025)."""
    df = pd.DataFrame(MTR_ANNUAL_DATA)
    df.to_csv(CSV_PATH, index=False)
    return df


if __name__ == "__main__":
    out = load_mtr_historical_earnings_bridge()
    print(f"Wrote {CSV_PATH} ({len(out)} fiscal years, 2010-2025)")
