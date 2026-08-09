#!/usr/bin/env python3
"""
MTR SRPE Transaction Probe (P0B Magnitude Engine inputs)
========================================================

For each name-confirmed MTR property phase (SRPE development ids), download
the latest statutory register-of-transactions PDF and parse it into
structured transactions, then produce per-phase statistics:

  * units_sold_registered   - count of registered transactions (proxy for
                               units sold to date, NOT total project units)
  * asp_median_hkd / asp_mean_hkd - transaction price statistics
  * first/last transaction date

All data is from the official SRPE register; parsed values carry the source
PDF hash. No invented numbers: total project units / GFA remain unpopulated
unless separately disclosed.

Usage: python scripts/mtr_srpe_transactions.py [--refresh]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import pandas as pd
import requests

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.hk_real_estate.sources.srpe import (  # noqa: E402
    SRPE_API_BASE,
    download_srpe_document,
)
from src.hk_real_estate.sources.srpe_pdf import parse_srpe_transaction_pdf  # noqa: E402

RAW_DIR = os.path.join(REPO_ROOT, "data", "raw", "hk_transport", "mtr_srpe")
NORM_DIR = os.path.join(REPO_ROOT, "data", "normalized", "hk_transport")
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(NORM_DIR, exist_ok=True)

DETAILS_JSON = os.path.join(RAW_DIR, "srpe_dev_details.json")
TX_DETAIL_CSV = os.path.join(NORM_DIR, "mtr_srpe_transactions_detail.csv")
TX_STATS_CSV = os.path.join(NORM_DIR, "mtr_srpe_transactions_by_phase.csv")

# project_id -> list of (development_id, phase label).
# Targeted enrichment round (2026-08-09): LP12 海瑅灣 I/II, SOUTHSIDE P5 滶晨
# I/II, 凱柏峰 II/III, 朗賢峯 (Ho Man Tin P1), LP13 (suspected SRPE 10486).
PHASES = {
    "the-southside-p1": [("7585", "晉環 (SOUTHLAND)")],
    "the-southside-p2": [("7787", "揚海 (La Marina)")],
    "the-southside-p4": [("9345", "海盈山 (La Montagne)")],
    "ho-man-tin-p2": [("8745", "瑜一 (IN ONE)")],
    "lohas-park-p11": [("8545", "凱柏峰 I (Villa Garda)")],
    "lohas-park-p4a": [("4745", "晉海 (Wings at Sea)")],
    "lohas-park-p4b": [("4865", "晉海II (Wings at Sea II)")],
    "tai-wai": [("7225", "柏傲莊 I (Pavilia Farm I)")],
    # ---- targeted round ----
    "lohas-park-p12": [("11386", "海瑅灣 I"), ("11385", "海瑅灣 II")],
    "the-southside-p5": [("10706", "滶晨"), ("10707", "滶晨 II")],
    "lohas-park-p11-ii": [("8625", "凱柏峰 II")],
    "lohas-park-p11-iii": [("8645", "凱柏峰 III")],
    "ho-man-tin-p1": [("9825", "朗賢峯")],
    "lohas-park-p13": [("10486", "LP13 (suspected)")],
}


def fetch_dev_details(dev_ids: list[str]) -> dict:
    """Get selected-dev result (latest transaction register metadata)."""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Origin": "https://www.srpe.gov.hk",
        "Referer": "https://www.srpe.gov.hk/",
    })
    out = {}
    for dev_id in dev_ids:
        r = session.post(
            f"{SRPE_API_BASE}/DevBldgSearch/getSelectedDevResult",
            json={"timeStamp": int(time.time() * 1000), "devId": dev_id},
            timeout=25,
        )
        r.raise_for_status()
        dev_info = (r.json().get("resultData") or {}).get("devInfoResp") or {}
        out[dev_id] = dev_info
        time.sleep(0.4)
    with open(DETAILS_JSON, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true",
                        help="re-fetch SRPE dev details (default: reuse cached snapshot)")
    args = parser.parse_args()

    dev_ids = [d for v in PHASES.values() for d, _ in v]
    if args.refresh or not os.path.exists(DETAILS_JSON):
        details = fetch_dev_details(dev_ids)
    else:
        with open(DETAILS_JSON, encoding="utf-8") as fh:
            details = json.load(fh)

    detail_frames = []
    stats_rows = []
    for project_id, phases in PHASES.items():
      for dev_id, label in phases:
          dev_info = details.get(dev_id) or {}
          dev = dev_info.get("dev") or {}
          txs = dev_info.get("transactions") or []
          if not txs:
              print(f"[skip] {project_id} ({label}): no transaction register listed")
              stats_rows.append({"project_id": project_id, "srpe_development_id": dev_id,
                                 "phase_label": label, "units_sold_registered": None,
                                 "asp_median_hkd": None, "asp_mean_hkd": None,
                                 "first_transaction_date": None, "last_transaction_date": None,
                                 "source_pdf_document_id": None, "source_pdf_hash": None,
                                 "note": "no transaction register listed"})
              continue
          tx = txs[0]  # latest register per the API
          doc_id = tx.get("id")
          file_info = tx.get("file") or {}
          submission = file_info.get("submissionTime")
          try:
              pdf_bytes = download_srpe_document(
                  "register_of_transactions", doc_id, dev_id, timeout=60
              )
          except Exception as exc:
              print(f"[error] {project_id} ({label}): download failed: {exc}")
              stats_rows.append({"project_id": project_id, "srpe_development_id": dev_id,
                                 "phase_label": label, "units_sold_registered": None,
                                 "asp_median_hkd": None, "asp_mean_hkd": None,
                                 "first_transaction_date": None, "last_transaction_date": None,
                                 "source_pdf_document_id": str(doc_id), "source_pdf_hash": None,
                                 "note": f"download error: {exc}"})
              continue

          pdf_path = os.path.join(RAW_DIR, f"{dev_id}_{doc_id}.pdf")
          with open(pdf_path, "wb") as fh:
              fh.write(pdf_bytes)

          frame = parse_srpe_transaction_pdf(
              pdf_bytes,
              development_id=dev_id,
              development_name=(dev.get("engName") or dev.get("chnName")),
              phase_name=(dev.get("engPhaseName") or dev.get("chnPhaseName")),
              source_document=f"{dev_id}_{doc_id}.pdf (submitted {submission})",
          )
          if frame is None or frame.empty:
              print(f"[warn] {project_id} ({label}): parsed empty transaction frame")
              stats_rows.append({"project_id": project_id, "srpe_development_id": dev_id,
                                 "phase_label": label, "units_sold_registered": None,
                                 "asp_median_hkd": None, "asp_mean_hkd": None,
                                 "first_transaction_date": None, "last_transaction_date": None,
                                 "source_pdf_document_id": str(doc_id), "source_pdf_hash": None,
                                 "note": "empty parse"})
              continue

          frame["project_id"] = project_id
          frame["srpe_development_id"] = dev_id
          frame["phase_label"] = label
          detail_frames.append(frame)

          prices = pd.to_numeric(frame.get("transaction_price_hkd"), errors="coerce").dropna()
          dates = pd.to_datetime(frame.get("date_of_pasp"), errors="coerce").dropna()
          stats_rows.append({
              "project_id": project_id,
              "srpe_development_id": dev_id,
              "phase_label": label,
              "units_sold_registered": len(frame),
              "asp_median_hkd": round(float(prices.median()), 0) if len(prices) else None,
              "asp_mean_hkd": round(float(prices.mean()), 0) if len(prices) else None,
              "first_transaction_date": dates.min().strftime("%Y-%m-%d") if len(dates) else None,
              "last_transaction_date": dates.max().strftime("%Y-%m-%d") if len(dates) else None,
              "source_pdf_document_id": str(doc_id),
              "source_pdf_hash": frame.attrs.get("document_hash")
              if hasattr(frame, "attrs") else None,
              "note": "latest register PDF (cumulative to submission date)" if len(frame) else "empty",
          })
          print(f"[ok] {project_id} ({label}): {len(frame)} transactions, "
                f"median {prices.median():,.0f} if len(prices) else n/a")

    stats_df = pd.DataFrame(stats_rows)
    stats_df.to_csv(TX_STATS_CSV, index=False)
    if detail_frames:
        detail = pd.concat(detail_frames, ignore_index=True)
        detail.to_csv(TX_DETAIL_CSV, index=False)
        print(f"\nWrote {TX_DETAIL_CSV} ({len(detail)} transaction rows)")
    print(f"Wrote {TX_STATS_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
