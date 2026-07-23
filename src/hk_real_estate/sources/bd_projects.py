import io
import re
import requests
import pandas as pd
from typing import Dict, Any, List, Optional

from ..config import BD_MONTHLY_DIGEST_XLS_BASE, DEFAULT_HEADERS
from ..storage import save_raw_snapshot
from ..mapping.developer_registry import DeveloperRegistry

PERMIT_REGEX = re.compile(r'([A-Z]{1,3}\s*\d+/\d+/[A-Z]+|BD\s*\d+/\d+/\d+|\d+/\d+/\d+)', re.IGNORECASE)

def safe_int(val: Any) -> Optional[int]:
    if pd.isna(val): return None
    try:
        v_str = str(val).replace(',', '').strip()
        if v_str == '-' or not v_str: return None
        return int(float(v_str))
    except (ValueError, TypeError):
        return None

def safe_float(val: Any) -> Optional[float]:
    if pd.isna(val): return None
    try:
        v_str = str(val).replace(',', '').strip()
        if v_str == '-' or not v_str: return None
        return float(v_str)
    except (ValueError, TypeError):
        return None

def parse_bd_xls_projects(excel_bytes: bytes, permit_stage: str) -> pd.DataFrame:
    """
    Parse Buildings Department XLS tables (Md53.xls, Md54.xls, Md56.xls) using permit-number anchor blocks.
    Merges multi-line project address rows, separates domestic units from GFA, and applies stock attribution.
    """
    df_raw = pd.read_excel(io.BytesIO(excel_bytes))
    
    projects = []
    current_block = None
    current_region = "Hong Kong Island"
    current_cat = "Domestic"
    
    for idx in range(7, len(df_raw)):
        row = df_raw.iloc[idx]
        c0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        c1 = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
        
        if "Kowloon" in c0:
            current_region = "Kowloon"
            continue
        elif "New Territories" in c0:
            current_region = "New Territories"
            continue
        elif "Hong Kong" in c0 and "Island" in c0:
            current_region = "Hong Kong Island"
            continue
            
        if "Non-domestic" in c0 or "Non-domestic" in c1:
            current_cat = "Non-domestic"
            continue
        elif "Domestic" in c0 or "Domestic" in c1:
            current_cat = "Domestic"
            continue

        match_permit = PERMIT_REGEX.search(c1) or PERMIT_REGEX.search(c0)
        
        # A new project block begins if a permit number is present
        if match_permit:
            if current_block:
                projects.append(current_block)
                
            permit_str = match_permit.group(1) if match_permit else None
            num_blocks = safe_int(row.iloc[2]) if len(row) > 2 else None
            num_storeys = safe_int(row.iloc[3]) if len(row) > 3 else None
            building_type = str(row.iloc[4]).strip() if len(row) > 4 and pd.notna(row.iloc[4]) else None
            units_count = safe_int(row.iloc[5]) if len(row) > 5 else None
            ufa_sqm = safe_float(row.iloc[6]) if len(row) > 6 else None
            
            current_block = {
                'permit_stage': permit_stage,
                'address_lines': [c0] if c0 else [],
                'permit_number': permit_str,
                'region': current_region,
                'property_category': current_cat,
                'num_blocks': num_blocks,
                'num_storeys': num_storeys,
                'building_type': building_type,
                'domestic_units_count': units_count,
                'usable_floor_area_sqm': ufa_sqm,
                'site_area_sqm': None,
                'parser_confidence': 'HIGH',
                'source_agency': 'Hong Kong Buildings Department'
            }
        elif current_block:
            # Multi-line continuation of existing project block
            if c0 and not c0.startswith("TABLE") and not c0.startswith("Address"):
                if "Site Area:" in c0:
                    site_area_match = re.search(r'Site Area:\s*([\d\.]+)', c0)
                    if site_area_match:
                        current_block['site_area_sqm'] = safe_float(site_area_match.group(1))
                elif not c0.startswith("Class of Site") and not c0.startswith("1.") and not c0.startswith("Note"):
                    current_block['address_lines'].append(c0)

    if current_block:
        projects.append(current_block)

    # Format final DataFrame
    records = []
    for p in projects:
        addr_clean = " ".join([line for line in p.pop('address_lines') if line]).strip()
        p['site_address'] = addr_clean
        records.append(p)

    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=['site_address', 'permit_stage']).reset_index(drop=True)
        # Apply Developer Stock Attribution & Confidence Tiers
        registry = DeveloperRegistry()
        df = registry.attribute_dataframe(df, project_col='site_address')
    return df

def fetch_bd_project_lifecycle_events() -> pd.DataFrame:
    """
    Fetch Buildings Department project-level tables:
    - Table 5.3: Plans Approved (Md53.xls)
    - Table 5.4: Consent to Commence Works (Md54.xls)
    - Table 5.6: Occupation Permits (OP) Issued (Md56.xls)
    """
    all_dfs = []
    tables = [
        ("Md53.xls", "Plans Approved"),
        ("Md54.xls", "Consent to Commence"),
        ("Md56.xls", "Occupation Permits (OP) Issued")
    ]
    
    for filename, stage_name in tables:
        url = f"{BD_MONTHLY_DIGEST_XLS_BASE}/{filename}"
        try:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
            if r.status_code == 200:
                save_raw_snapshot(f"bd_{filename.replace('.xls', '')}", r.content, file_ext="xls")
                df_stage = parse_bd_xls_projects(r.content, stage_name)
                if not df_stage.empty:
                    all_dfs.append(df_stage)
        except Exception as e:
            print(f"Error downloading/parsing BD project table {filename}: {e}")
            
    if all_dfs:
        res_df = pd.concat(all_dfs, ignore_index=True)
        return res_df
    return pd.DataFrame()
