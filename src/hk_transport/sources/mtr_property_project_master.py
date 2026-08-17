"""
MTR Property Project Master Table (official disclosures + SRPE crosswalk)
==========================================================================

P0B Property Engine master table, v2. Every row is sourced from either:
  * official MTR annual results announcements (profit recognition / tender
    years, official English project names), or
  * this repo's already-verified data: SHKP phase data
    (`src/hk_real_estate/sources/shkp.py`) and the SRPE development index
    snapshots under `data/raw/hk_real_estate/srpe_development_index/`.

SRPE crosswalk rules (conservative by design):
  * `srpe_development_id` is populated ONLY where the mapping is confirmed by
    an official English name match (e.g. MTR results state "SOUTHLAND (THE
    SOUTHSIDE Package 1)" and the SRPE phase 晉環 is publicly known as
    SOUTHLAND) or by repo-verified SHKP data (Wings at Sea / YOHO WEST).
  * `srpe_first_price_list_date` = the SRPE index's `earlistPublicationTime`
    for that phase - an official proxy for the first presale launch.
  * Ambiguous phases (THE SOUTHSIDE P3/P5/P6, LOHAS Park P7-10/P12 etc.) keep
    NULL srpe ids until verified - empty cells are honest unknowns.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
os.makedirs(OUT_DIR, exist_ok=True)

CSV_PATH = os.path.join(OUT_DIR, "mtr_property_project_master.csv")

# srpe_development_id -> (phase_name, first_price_list_date) confirmed mappings
SRPE_CONFIRMED = {
    # THE SOUTHSIDE (Wong Chuk Hang station), official English names from MTR results
    "the-southside-p1": ("7585", "晉環 (SOUTHLAND)", "2021-04-19"),
    "the-southside-p2": ("7787", "揚海 (La Marina)", "2021-08-17"),
    "the-southside-p4": ("9345", "海盈山 (La Montagne)", "2023-06-27"),
    # Ho Man Tin station
    "ho-man-tin-p2": ("8745", "瑜一 (IN ONE)", "2023-05-08"),
    # LOHAS Park: repo-verified SHKP phases
    "lohas-park-p4a": ("4745", "晉海 (Wings at Sea)", "2017-09-08"),
    "lohas-park-p4b": ("4865", "晉海II (Wings at Sea II)", "2017-10-14"),
}


MTR_PROPERTY_PROJECTS: list[dict[str, Any]] = [
    dict(project_id="lohas-park-p7-p9", station="LOHAS Park",
         package_label="LOHAS Park Packages 7, 8, 9",
         project_name_official=None, developer=None,
         profit_recognition_year="2021", tender_year=None,
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2021 results (HK$9.3bn booked)"),
    dict(project_id="lohas-park-p10", station="LOHAS Park",
         package_label="LOHAS Park Package 10 (LP10)",
         project_name_official="LP10", developer=None,
         profit_recognition_year="2022", tender_year=None,
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2022 results"),
    dict(project_id="lohas-park-p11", station="LOHAS Park",
         package_label="LOHAS Park Package 11",
         project_name_official="Villa Garda", developer=None,
         profit_recognition_year="2024", tender_year=None,
         srpe_development_id="8545", srpe_phase_name="凱柏峰 I (Villa Garda)", srpe_first_price_list_date="2022-06-20",
         evidence_level="official_name_match",
         units_sold_registered=669,
         asp_median_hkd=8215400.0,
         asp_mean_hkd=8314083.0,
         first_transaction_date="2022-06-30",
         last_transaction_date="2026-06-27",
         cross_ref_hk_real_estate=None, source="MTR FY2023/FY2024 results; SRPE index"),
    dict(project_id="lohas-park-p12", station="LOHAS Park",
         package_label="LOHAS Park Package 12",
         project_name_official=None, developer=None,
         profit_recognition_year="2025", tender_year=None,
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2024 outlook / FY2025 results"),
    dict(project_id="lohas-park-p4a", station="LOHAS Park",
         package_label="LOHAS Park Phase IVA (Wings at Sea / 晉海)",
         project_name_official="Wings at Sea", developer="SHKP-led with MTR as owner",
         profit_recognition_year=None, tender_year=None,
         srpe_development_id="4745", srpe_phase_name="晉海 (Wings at Sea)", srpe_first_price_list_date="2017-09-08",
         evidence_level="repo_verified_shkp",
         units_sold_registered=1047,
         asp_median_hkd=7364400.0,
         asp_mean_hkd=8341898.0,
         first_transaction_date="2017-09-30",
         last_transaction_date="2023-05-09",
         cross_ref_hk_real_estate="shkp.py phase Wings at Sea (LOHAS Park Phase IVA)",
         source="HK real-estate SHKP phase data (repo-verified); SRPE index"),
    dict(project_id="lohas-park-p4b", station="LOHAS Park",
         package_label="LOHAS Park Phase IVB (Wings at Sea II / 晉海II)",
         project_name_official="Wings at Sea II", developer="SHKP-led with MTR as owner",
         profit_recognition_year=None, tender_year=None,
         srpe_development_id="4865", srpe_phase_name="晉海II (Wings at Sea II)", srpe_first_price_list_date="2017-10-14",
         evidence_level="repo_verified_shkp",
         units_sold_registered=1142,
         asp_median_hkd=8424100.0,
         asp_mean_hkd=8505845.0,
         first_transaction_date="2017-10-22",
         last_transaction_date="2023-08-08",
         cross_ref_hk_real_estate="shkp.py phase Wings at Sea II (LOHAS Park Phase IVB)",
         source="HK real-estate SHKP phase data (repo-verified); SRPE index"),
    dict(project_id="the-southside-p1", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 1",
         project_name_official="SOUTHLAND", developer=None,
         profit_recognition_year="2022, 2024", tender_year=None,
         srpe_development_id="7585", srpe_phase_name="晉環 (SOUTHLAND)", srpe_first_price_list_date="2021-04-19",
         evidence_level="official_name_match",
         units_sold_registered=860,
         asp_median_hkd=18224000.0,
         asp_mean_hkd=21026522.0,
         first_transaction_date="2021-05-01",
         last_transaction_date="2026-06-10",
         cross_ref_hk_real_estate=None, source="MTR FY2022/FY2024 results; SRPE index"),
    dict(project_id="the-southside-p2", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 2",
         project_name_official="La Marina", developer=None,
         profit_recognition_year="2022, 2024", tender_year=None,
         srpe_development_id="7787", srpe_phase_name="揚海 (La Marina)", srpe_first_price_list_date="2021-08-17",
         evidence_level="official_name_match",
         units_sold_registered=641,
         asp_median_hkd=19052000.0,
         asp_mean_hkd=25180201.0,
         first_transaction_date="2021-09-04",
         last_transaction_date="2026-07-08",
         cross_ref_hk_real_estate=None, source="MTR FY2022/FY2024 results; SRPE index"),
    dict(project_id="the-southside-p3", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 3",
         project_name_official=None, developer=None,
         profit_recognition_year="2025", tender_year=None,
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2024 outlook / FY2025 results"),
    dict(project_id="the-southside-p4", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 4",
         project_name_official="La Montagne", developer=None,
         profit_recognition_year="2024", tender_year=None,
         srpe_development_id="9345", srpe_phase_name="海盈山 (La Montagne)", srpe_first_price_list_date="2023-06-27",
         evidence_level="official_name_match",
         units_sold_registered=374,
         asp_median_hkd=14198450.0,
         asp_mean_hkd=16560358.0,
         first_transaction_date="2023-07-15",
         last_transaction_date="2026-06-08",
         cross_ref_hk_real_estate=None, source="MTR FY2024 results; SRPE index"),
    dict(project_id="the-southside-p5", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 5",
         project_name_official=None, developer=None,
         profit_recognition_year="2024, 2025", tender_year="2021",
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2021/FY2024/FY2025 results"),
    dict(project_id="the-southside-p6", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 6",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year="2021",
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2021 results (tendered out)"),
    dict(project_id="ho-man-tin-p1", station="Ho Man Tin",
         package_label="Ho Man Tin Station Package 1",
         project_name_official=None, developer=None,
         profit_recognition_year="2024, 2025", tender_year=None,
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2024/FY2025 results"),
    dict(project_id="ho-man-tin-p2", station="Ho Man Tin",
         package_label="Ho Man Tin Station Package 2",
         project_name_official="IN ONE", developer=None,
         profit_recognition_year="2025", tender_year=None,
         srpe_development_id="8745", srpe_phase_name="瑜一 (IN ONE)", srpe_first_price_list_date="2023-05-08",
         evidence_level="official_name_match",
         units_sold_registered=378,
         asp_median_hkd=16405500.0,
         asp_mean_hkd=18467320.0,
         first_transaction_date="2023-05-21",
         last_transaction_date="2026-08-03",
         cross_ref_hk_real_estate=None, source="MTR FY2023 outlook / FY2025 results; SRPE index"),
    dict(project_id="tai-wai", station="Tai Wai",
         package_label="Tai Wai Station project (The Wai mall sharing-in-kind)",
         project_name_official="The Wai (柏傲莊)", developer=None,
         profit_recognition_year="2022 (initial booking via IP fair value)", tender_year=None,
         srpe_development_id="7225", srpe_phase_name="柏傲莊 I (Pavilia Farm I)", srpe_first_price_list_date="2020-10-06",
         evidence_level="public_knowledge_name_match",
         units_sold_registered=810,
         asp_median_hkd=10201000.0,
         asp_mean_hkd=11288285.0,
         first_transaction_date="2020-10-17",
         last_transaction_date="2026-05-29",
         cross_ref_hk_real_estate=None, source="MTR FY2022 results; SRPE index"),
    dict(project_id="tung-chung-east-p1", station="Tung Chung East",
         package_label="Tung Chung East Station Package 1",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year="2024",
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2024 results (awarded Dec 2024)"),
    dict(project_id="tuen-mun-a16-p1", station="Tuen Mun A16",
         package_label="Tuen Mun A16 Station Package 1",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year="2025",
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None, source="MTR FY2025 results (awarded Nov 2025)"),
    dict(project_id="hung-shui-kiu", station="Hung Shui Kiu",
         package_label="Hung Shui Kiu Station",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year=None,
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="official_recognition_only",
         cross_ref_hk_real_estate=None,
         source="MTR FY2021 (detailed planning) / FY2024 (project agreement)"),
    dict(project_id="yoho-west", station="Tin Wing Stop / Tin Shui Wai",
         package_label="YOHO WEST (Tin Wing Stop development)",
         project_name_official="YOHO WEST / YOHO WEST PARKSIDE", developer="SHKP-MTR JV",
         profit_recognition_year=None, tender_year=None,
         srpe_development_id=None, srpe_phase_name=None, srpe_first_price_list_date=None,
         evidence_level="repo_verified_shkp",
         cross_ref_hk_real_estate="shkp.py YOHO WEST PARKSIDE / Tin Wing Stop Development",
         source="HK real-estate SHKP phase data (repo-verified)"),
]


def load_mtr_property_project_master() -> pd.DataFrame:
    """Load or regenerate the MTR property project master table."""
    df = pd.DataFrame(MTR_PROPERTY_PROJECTS)
    df.to_csv(CSV_PATH, index=False)
    return df


if __name__ == "__main__":
    out = load_mtr_property_project_master()
    mapped = out["srpe_development_id"].notna().sum()
    print(f"Wrote {CSV_PATH} ({len(out)} rows, {int(mapped)} with confirmed SRPE crosswalk)")
