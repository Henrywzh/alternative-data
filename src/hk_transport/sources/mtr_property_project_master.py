"""
MTR Property Project Master Table (official disclosures only)
=============================================================

Initial skeleton of MTR's railway-property project database for the Property
Development Engine (P0B). Every row is sourced from official MTR annual
results PDFs (2021-2025) or from this repo's already-verified SHKP real-estate
data (`src/hk_real_estate/sources/shkp.py`).

Deliberately conservative:
  * `profit_recognition_year` = fiscal year in which MTR's official results
    announcement states property development profit was booked for the package.
  * `tender_year` = fiscal year the package was tendered out (official).
  * Units / GFA / ASP / sell-through / MTR profit share / remaining profit are
    NOT populated here until they can be verified from SRPE or other official
    sources - empty cells are honest unknowns, not zeros.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
os.makedirs(OUT_DIR, exist_ok=True)

CSV_PATH = os.path.join(OUT_DIR, "mtr_property_project_master.csv")

# ---------------------------------------------------------------------------
# Source legend: Y2021..Y2025 = MTR annual results announcement of that year;
# SHKP = verified Sun Hung Kai phase data in this repo (shkp.py).
# ---------------------------------------------------------------------------
MTR_PROPERTY_PROJECTS: list[dict[str, Any]] = [
    dict(project_id="lohas-park-p7-p9", station="LOHAS Park",
         package_label="LOHAS Park Packages 7, 8, 9",
         project_name_official=None, developer=None,
         profit_recognition_year="2021", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2021 results (HK$9.3bn booked)"),
    dict(project_id="lohas-park-p10", station="LOHAS Park",
         package_label="LOHAS Park Package 10 (LP10)",
         project_name_official="LP10", developer=None,
         profit_recognition_year="2022", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2022 results"),
    dict(project_id="lohas-park-p11", station="LOHAS Park",
         package_label="LOHAS Park Package 11",
         project_name_official="Villa Garda", developer=None,
         profit_recognition_year="2024", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2023/FY2024 results"),
    dict(project_id="lohas-park-p12", station="LOHAS Park",
         package_label="LOHAS Park Package 12",
         project_name_official=None, developer=None,
         profit_recognition_year="2025", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2024 outlook / FY2025 results"),
    dict(project_id="lohas-park-p4a", station="LOHAS Park",
         package_label="LOHAS Park Phase IVA (Wings at Sea / 晉海)",
         project_name_official="Wings at Sea", developer="SHKP-led with MTR as owner",
         profit_recognition_year=None, tender_year=None,
         cross_ref_hk_real_estate="shkp.py phase Wings at Sea (LOHAS Park Phase IVA)",
         source="HK real-estate SHKP phase data (repo-verified)"),
    dict(project_id="lohas-park-p4b", station="LOHAS Park",
         package_label="LOHAS Park Phase IVB (Wings at Sea II / 晉海II)",
         project_name_official="Wings at Sea II", developer="SHKP-led with MTR as owner",
         profit_recognition_year=None, tender_year=None,
         cross_ref_hk_real_estate="shkp.py phase Wings at Sea II (LOHAS Park Phase IVB)",
         source="HK real-estate SHKP phase data (repo-verified)"),
    dict(project_id="the-southside-p1", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 1",
         project_name_official="SOUTHLAND", developer=None,
         profit_recognition_year="2022, 2024", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2022/FY2024 results"),
    dict(project_id="the-southside-p2", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 2",
         project_name_official="La Marina", developer=None,
         profit_recognition_year="2022, 2024", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2022/FY2024 results"),
    dict(project_id="the-southside-p3", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 3",
         project_name_official=None, developer=None,
         profit_recognition_year="2025", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2024 outlook / FY2025 results"),
    dict(project_id="the-southside-p4", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 4",
         project_name_official="La Montagne", developer=None,
         profit_recognition_year="2024", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2024 results"),
    dict(project_id="the-southside-p5", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 5",
         project_name_official=None, developer=None,
         profit_recognition_year="2024, 2025", tender_year="2021",
         cross_ref_hk_real_estate=None, source="MTR FY2021/FY2024/FY2025 results"),
    dict(project_id="the-southside-p6", station="Wong Chuk Hang",
         package_label="THE SOUTHSIDE Package 6",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year="2021",
         cross_ref_hk_real_estate=None, source="MTR FY2021 results (tendered out)"),
    dict(project_id="ho-man-tin-p1", station="Ho Man Tin",
         package_label="Ho Man Tin Station Package 1",
         project_name_official=None, developer=None,
         profit_recognition_year="2024, 2025", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2024/FY2025 results"),
    dict(project_id="ho-man-tin-p2", station="Ho Man Tin",
         package_label="Ho Man Tin Station Package 2",
         project_name_official="IN ONE", developer=None,
         profit_recognition_year="2025", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2023 outlook / FY2025 results"),
    dict(project_id="tai-wai", station="Tai Wai",
         package_label="Tai Wai Station project (The Wai mall sharing-in-kind)",
         project_name_official="The Wai (柏傲莊)", developer=None,
         profit_recognition_year="2022 (initial booking via IP fair value)", tender_year=None,
         cross_ref_hk_real_estate=None, source="MTR FY2022 results"),
    dict(project_id="tung-chung-east-p1", station="Tung Chung East",
         package_label="Tung Chung East Station Package 1",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year="2024",
         cross_ref_hk_real_estate=None, source="MTR FY2024 results (awarded Dec 2024)"),
    dict(project_id="tuen-mun-a16-p1", station="Tuen Mun A16",
         package_label="Tuen Mun A16 Station Package 1",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year="2025",
         cross_ref_hk_real_estate=None, source="MTR FY2025 results (awarded Nov 2025)"),
    dict(project_id="hung-shui-kiu", station="Hung Shui Kiu",
         package_label="Hung Shui Kiu Station",
         project_name_official=None, developer=None,
         profit_recognition_year=None, tender_year=None,
         cross_ref_hk_real_estate=None,
         source="MTR FY2021 (detailed planning) / FY2024 (project agreement)"),
    dict(project_id="yoho-west", station="Tin Wing Stop / Tin Shui Wai",
         package_label="YOHO WEST (Tin Wing Stop development)",
         project_name_official="YOHO WEST / YOHO WEST PARKSIDE", developer="SHKP-MTR JV",
         profit_recognition_year=None, tender_year=None,
         cross_ref_hk_real_estate="shkp.py YOHO WEST PARKSIDE / Tin Wing Stop Development",
         source="HK real-estate SHKP phase data (repo-verified)"),
]


def load_mtr_property_project_master() -> pd.DataFrame:
    """Load or regenerate the MTR property project master table (official only)."""
    df = pd.DataFrame(MTR_PROPERTY_PROJECTS)
    df.to_csv(CSV_PATH, index=False)
    return df


if __name__ == "__main__":
    out = load_mtr_property_project_master()
    print(f"Wrote {CSV_PATH} ({len(out)} project/package rows)")
