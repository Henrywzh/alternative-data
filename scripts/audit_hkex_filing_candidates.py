"""Inventory broader HKEX filings without promoting them into the event study."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import duckdb
import pandas as pd


FAMILY_RULES = [
    ("governance", r"corporate governance|constitutional|committee|agm|egm|sgm|general meeting"),
    ("results", r"profit warning|profit alert|earnings|interim results|final results|annual results|quarterly results|results of a subsidiary"),
    ("board_meeting", r"date of board meeting"),
    ("trading_update", r"trading update"),
    ("business_update", r"business update"),
    ("dividend", r"dividend|distribution"),
    ("director_change", r"director|company secretary"),
    ("capital_action", r"issue of securities|issue of shares|convertible|debt securities|share scheme|change in terms|shareholding|spin-off|privatisation|withdrawal|cancellation of listing"),
    ("transaction", r"transaction|discloseable|acquisition|disposal|takeovers code|offeror|offeree"),
    ("inside_information", r"inside information"),
]
MATERIAL_REPURCHASE_TITLE_PATTERN = re.compile(
    r"voluntary announcement.*(?:intention to conduct|share repurchase|repurchase mandate|repurchase program)",
    re.IGNORECASE,
)


def classify_category(category: object) -> tuple[str, bool]:
    text = "" if pd.isna(category) else str(category).lower()
    family = "other"
    for candidate, pattern in FAMILY_RULES:
        if re.search(pattern, text):
            family = candidate
            break
    composite = any(separator in text for separator in (" / ", "&#x2f;", ";"))
    return family, composite


def classify_filing(
    category: object,
    title_en: object,
    title_zh: object,
) -> tuple[str, bool, str]:
    """Classify a filing, with one narrow material-repurchase title override."""
    family, composite = classify_category(category)
    title = " ".join(
        value
        for value in (title_en, title_zh)
        if value is not None and not pd.isna(value)
    )
    title = re.sub(r"\s+", " ", str(title)).strip()
    if (
        family == "other"
        and not composite
        and MATERIAL_REPURCHASE_TITLE_PATTERN.search(title)
    ):
        return "capital_action", composite, "title_material_repurchase_override"
    return family, composite, "category_rule"


def load_pit_recovery_ids(sidecar_path: Path | None) -> set[str]:
    if sidecar_path is None or not sidecar_path.exists():
        return set()
    sidecar = pd.read_parquet(sidecar_path, columns=["filing_id", "event_study_eligible"])
    if sidecar["event_study_eligible"].astype(bool).any():
        raise ValueError("PIT recovery sidecar contains event-study-eligible rows")
    return set(sidecar["filing_id"].dropna().astype(str))


def build_inventory(
    financial_db: Path,
    sidecar_path: Path | None = None,
) -> pd.DataFrame:
    with duckdb.connect(str(financial_db), read_only=True) as connection:
        filings = connection.execute(
            """
            SELECT filing_id, ticker, announcement_date, title_en, title_zh,
                   category, document_url, announcement_at, available_at,
                   availability_basis
            FROM hkex_filings
            """
        ).fetchdf()
        canonical = connection.execute(
            """
            SELECT filing_id, event_id, event_type
            FROM hkex_announcement_events
            """
        ).fetchdf()
    result = filings.merge(canonical, on="filing_id", how="left")
    pit_recovery_ids = load_pit_recovery_ids(sidecar_path)
    result["pit_recovery_sidecar"] = result["filing_id"].astype(str).isin(pit_recovery_ids)
    result["event_study_eligible"] = ~result["pit_recovery_sidecar"]
    classified = result.apply(
        lambda row: classify_filing(row["category"], row["title_en"], row["title_zh"]),
        axis=1,
    )
    result["candidate_family"] = classified.map(lambda value: value[0])
    result["category_is_composite"] = classified.map(lambda value: value[1])
    result["candidate_family_basis"] = classified.map(lambda value: value[2])
    result["pit_status"] = result.apply(
        lambda row: (
            "recovered_sidecar_excluded"
            if row["pit_recovery_sidecar"]
            else
            "missing_availability"
            if pd.isna(row["available_at"])
            else "observed_collection"
            if row["availability_basis"] == "observed_collection"
            else "source_timestamp_proxy"
            if row["availability_basis"] == "source_timestamp_proxy"
            else "unknown_availability_basis"
        ),
        axis=1,
    )
    result["candidate_status"] = result.apply(
        lambda row: (
            "already_canonical"
            if pd.notna(row["event_id"])
            else "blocked_pit_recovery_sidecar"
            if row["pit_recovery_sidecar"]
            else "blocked_missing_pit"
            if row["pit_status"] == "missing_availability"
            else "blocked_composite_category"
            if row["category_is_composite"]
            else "discovery_candidate"
        ),
        axis=1,
    )
    return result.sort_values(["candidate_status", "candidate_family", "ticker", "announcement_at"]).reset_index(drop=True)


def run(
    financial_db: Path,
    output_dir: Path,
    sidecar_path: Path | None = None,
) -> dict[str, object]:
    inventory = build_inventory(financial_db, sidecar_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory.to_csv(output_dir / "hkex_filing_candidate_inventory.csv", index=False)
    summary = (
        inventory.groupby(["candidate_family", "candidate_status", "pit_status"], dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values(["candidate_family", "candidate_status"])
    )
    summary.to_csv(output_dir / "hkex_filing_candidate_summary.csv", index=False)
    result = {
        "version": "hkex_filing_candidate_inventory.v1",
        "source_table": "hkex_filings",
        "rows": int(len(inventory)),
        "summary_rows": int(len(summary)),
        "candidate_status_counts": inventory["candidate_status"].value_counts().to_dict(),
        "pit_status_counts": inventory["pit_status"].value_counts().to_dict(),
        "pit_recovery_sidecar_rows": int(inventory["pit_recovery_sidecar"].sum()),
        "event_study_eligible_rows": int(inventory["event_study_eligible"].sum()),
        "production_database_modified": False,
        "artifacts": {
            "inventory": str(output_dir / "hkex_filing_candidate_inventory.csv"),
            "summary": str(output_dir / "hkex_filing_candidate_summary.csv"),
        },
    }
    (output_dir / "coverage.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--financial-db", type=Path, default=Path(__file__).resolve().parents[2] / "financial-data" / "data" / "databases" / "hk_financials.duckdb")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/hkex_filing_candidate_inventory"))
    parser.add_argument(
        "--pit-recovery-sidecar",
        type=Path,
        dest="sidecar_path",
        default=Path("outputs/hkex_pit_recovery_sidecar/pit_recovered_filings.parquet"),
        help="Read-only recovery sidecar; its filing IDs are blocked from candidate event-study inclusion.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(**vars(parse_args())), indent=2, ensure_ascii=False, default=str))
