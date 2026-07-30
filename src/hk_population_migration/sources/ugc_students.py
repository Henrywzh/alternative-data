import logging
import pandas as pd
import requests
from ..config import DEFAULT_HEADERS, UGC_STUDENT_ENROLMENT_FEATURESERVER_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)


def fetch_ugc_nonlocal_students() -> pd.DataFrame:
    """
    Fetch UGC (University Grants Committee) non-local student enrollment.

    Real source: "Student Enrolment of UGC-funded Programmes by University,
    Level of Study, Place of Origin and Mode of Study", published on the
    government's CSDI portal as an Esri FeatureServer -- one row per
    university/level-of-study/mode-of-study/place-of-origin/academic-year
    combination, aggregated here to one row per academic year.
    """
    response = requests.get(
        UGC_STUDENT_ENROLMENT_FEATURESERVER_URL,
        headers=DEFAULT_HEADERS,
        params={"where": "1=1", "outFields": "*", "f": "json"},
        timeout=30,
    )
    response.raise_for_status()
    save_raw_snapshot(
        "ugc_nonlocal_students",
        response.content,
        file_ext="json",
        source_url=UGC_STUDENT_ENROLMENT_FEATURESERVER_URL,
    )
    features = response.json().get("features", [])
    records = [feature["attributes"] for feature in features]
    raw = pd.DataFrame(records)
    if raw.empty:
        return pd.DataFrame(columns=["academic_year", "mainland_students", "other_non_local_students", "total_non_local"])

    raw["Student_Enrolment_Headcount"] = pd.to_numeric(raw["Student_Enrolment_Headcount"], errors="coerce")
    by_origin = (
        raw.groupby(["Academic_Year", "Place_of_Origin_EN"])["Student_Enrolment_Headcount"]
        .sum()
        .unstack(fill_value=0)
    )
    mainland = by_origin.get("Chinese Mainland", pd.Series(0, index=by_origin.index))
    other_non_local = (
        by_origin.get("Other places of Asia", pd.Series(0, index=by_origin.index))
        + by_origin.get("The rest of the world", pd.Series(0, index=by_origin.index))
    )

    df = pd.DataFrame(
        {
            "academic_year": by_origin.index,
            "mainland_students": mainland.astype(int).values,
            "other_non_local_students": other_non_local.astype(int).values,
        }
    )
    df["total_non_local"] = df["mainland_students"] + df["other_non_local_students"]
    df = df.sort_values("academic_year").reset_index(drop=True)
    df["source_agency"] = "University Grants Committee (UGC)"
    df.attrs.update(source_url=UGC_STUDENT_ENROLMENT_FEATURESERVER_URL)
    return df
