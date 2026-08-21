import json
import subprocess
import requests
import pandas as pd
from typing import Dict, Any, List

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

HKMA_PUBLIC_RMS_URL = "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-survey"

def fetch_hkma_residential_mortgage_survey() -> pd.DataFrame:
    """
    Fetch HKMA Residential Mortgage Survey (RMS) API.
    Extracts financing metrics: new mortgage applications, approvals, primary/secondary split,
    drawn-down value, LTV ratio, HIBOR/BLR/fixed interest rate pricing mix, and delinquency rates.
    """
    raw_json = None
    try:
        response = requests.get(HKMA_PUBLIC_RMS_URL, headers=DEFAULT_HEADERS, params={"pagesize": 1000}, timeout=10)
        if response.status_code == 200:
            raw_json = response.json()
    except Exception:
        pass
        
    if not raw_json:
        try:
            # Without a bound the fallback can hang indefinitely when the
            # API stalls at the network layer (confirmed: requests times out
            # at 10s, then curl blocks for minutes with no --max-time).
            cmd = [
                "curl", "-s",
                "--connect-timeout", "10",
                "--max-time", "25",
                f"{HKMA_PUBLIC_RMS_URL}?pagesize=1000",
            ]
            out = subprocess.check_output(cmd, text=True)
            raw_json = json.loads(out)
        except Exception as e:
            print(f"Warning: Unable to fetch HKMA RMS API: {e}")
            return pd.DataFrame()

    if raw_json:
        save_raw_snapshot("hkma_residential_mortgage_survey", raw_json, file_ext="json")
        records = raw_json.get("result", {}).get("records", [])
        if not records:
            return pd.DataFrame()
            
        norm_records = []
        for r in records:
            obs_period = r.get("end_of_month")
            if not obs_period:
                continue
                
            period_str = str(obs_period).strip()
            if len(period_str) == 7: # YYYY-MM
                obs_date = f"{period_str}-01"
            else:
                obs_date = period_str[:10]
                
            def safe_float(val):
                if val is None or val == "*":
                    return None
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return None

            def scale_pct(val):
                f = safe_float(val)
                return round(f * 100.0, 2) if f is not None else None

            norm_records.append({
                'observation_date': obs_date,
                'period_start': obs_date,
                'period_end': obs_date,
                'publication_date': None,  # Not hardcoded to observation_date; published ~25 days after month end
                'is_provisional': False,
                'new_applications_count': safe_float(r.get('new_loans_app_received')),
                'approved_loans_amount_mhkd': safe_float(r.get('new_loans_approved_amt')),
                'approved_primary_presales_amount_mhkd': safe_float(r.get('new_loans_approved_pt_amt_pri')),
                'approved_secondary_amount_mhkd': safe_float(r.get('new_loans_approved_pt_amt_sec')),
                'approved_refinancing_amount_mhkd': safe_float(r.get('new_loans_approved_pt_amt_refin')),
                'drawn_down_amount_mhkd': safe_float(r.get('new_loans_drawn_amt')),
                'average_ltv_ratio_pct': safe_float(r.get('new_loans_approved_lv_ratio')),
                'hibor_pricing_pct_share': scale_pct(r.get('ir_new_loans_approved_hibor')),  # Scaled to 0-100% (e.g. 73.8)
                'blr_pricing_pct_share': scale_pct(r.get('ir_new_loans_approved_blr')),      # Scaled to 0-100% (e.g. 1.2)
                'fixed_pricing_pct_share': scale_pct(r.get('ir_new_loans_approved_fixed')),  # Scaled to 0-100% (e.g. 20.7)
                'other_pricing_pct_share': scale_pct(r.get('ir_new_loans_approved_other')),  # Scaled to 0-100%; 4th rate-mix category, previously dropped (the 3 tracked shares alone summed to only ~93-99%)
                'delinquency_ratio_pct': safe_float(r.get('delinquency_ratio')),             # Retained as % (e.g. 0.11)
                'rescheduled_loan_ratio_pct': safe_float(r.get('resch_loan_ratio')),
                'source_agency': 'Hong Kong Monetary Authority (HKMA)'
            })
            
        df = pd.DataFrame(norm_records)
        if not df.empty:
            df = df.sort_values('observation_date').reset_index(drop=True)
        return df

    return pd.DataFrame()
