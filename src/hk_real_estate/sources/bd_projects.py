import io
import re
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from ..config import BD_MONTHLY_DIGEST_XLS_BASE, DEFAULT_HEADERS
from ..storage import save_raw_snapshot
from ..mapping.developer_registry import DeveloperRegistry

PERMIT_REGEX = re.compile(r'([A-Z]{1,3}\s*\d+/\d+/[A-Z]+|BD\s*\d+/\d+/\d+|\d+/\d+/\d+)', re.IGNORECASE)

# Matches a bare "Class of Site" planning-area reference line, e.g.
# "1.8.4/(3)" or "9.5.1/(5) & 9.5.1/(6)" -- these are continuation lines
# that trail a project's address block and carry no address content of
# their own, so they should never be appended into `site_address`.
PERMIT_CLASS_REF_REGEX = re.compile(r'^\d+(?:\.\d+)+/\(\d+\)')

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

# Per-stage column layouts. Md53 (Plans Approved) and Md54 (Consent to
# Commence) have no permit-number column at all -- only Md56 (Occupation
# Permits Issued) carries one. Anchoring block-detection on a permit-number
# regex match (as the original parser did) silently drops every row from
# Md53/Md54, since a project block never gets created for those two tables.
# The reliable anchor across all three tables is instead the "No. of Blocks"
# column, which is populated only on a project's first row and blank on
# every continuation line.
_STAGE_COLUMNS: dict[str, dict[str, int | None]] = {
    "Plans Approved": {
        "permit_col": None, "blocks_col": 1, "storeys_col": 2, "building_type_col": 3,
        "units_col": None, "domestic_gfa_col": 4, "non_domestic_gfa_col": 5,
        "domestic_ufa_col": None, "non_domestic_ufa_col": None,
    },
    "Consent to Commence": {
        "permit_col": None, "blocks_col": 1, "storeys_col": 2, "building_type_col": 3,
        "units_col": 4, "domestic_gfa_col": 6, "non_domestic_gfa_col": 7,
        "domestic_ufa_col": 8, "non_domestic_ufa_col": 9,
    },
    "Occupation Permits (OP) Issued": {
        "permit_col": 1, "blocks_col": 2, "storeys_col": 3, "building_type_col": 4,
        "units_col": 5, "domestic_gfa_col": 7, "non_domestic_gfa_col": 8,
        "domestic_ufa_col": 9, "non_domestic_ufa_col": 10,
    },
}


def _col(row: pd.Series, index: int | None):
    if index is None or index >= len(row):
        return None
    return row.iloc[index]


def parse_bd_xls_projects(excel_bytes: bytes, permit_stage: str) -> pd.DataFrame:
    """
    Parse Buildings Department XLS tables (Md53.xls, Md54.xls, Md56.xls).

    A new project block begins only on a row where BOTH the "No. of Blocks"
    column AND the "Building Type" column are populated together. Neither
    column alone is a safe anchor: BD repeats the "No. of Blocks" value on
    every continuation sub-row of a project that spans multiple unit-size
    tiers or multiple houses (confirmed on live Md56.xls rows ~65-70, "8 Hoi
    Ying Road, Tai Po", and live Md54.xls rows ~16-38, "30-38 Magazine Gap
    Road" with houses 3A/3B/4A/4B) -- so anchoring on that column alone
    shreds one real project into several fake ones. Conversely "Building
    Type" text itself sometimes wraps onto a continuation line (e.g. "with
    residents' / recreational facilities" trailing "Apartment/Commercial"),
    so it isn't safe alone either. Requiring both together has been
    verified against every project in the live Md53/Md54/Md56 files,
    including two back-to-back projects that share a row with no blank
    separator between them (Md56 "78-80 Queen's Road West" immediately
    followed by "265-267 Hollywood Road").

    A fully blank row (every cell NaN) always terminates the current
    project block in the live files, so it flushes `current_block`
    regardless of the header anchor above.

    Continuation rows (address wraps, "Site Area:", "Class of Site", or a
    project's later unit-size tiers) are merged into the SAME project:
    their "Unit No." values are summed into `domestic_units_count` instead
    of starting a new orphan project or being silently dropped. GFA/UFA are
    NOT re-summed across tiers -- BD already publishes the project's total
    GFA/UFA once on the header row (verified: sum(tier_units * tier_size)
    for every tiered project in the live files reproduces that header-row
    total exactly, e.g. 86*17.2 + 91*23.1 + 365*25.2 + 172*35.8 + 13*45.3 ==
    19,525.8 == the Hoi Ying Road header row's own domestic UFA).
    """
    df_raw = pd.read_excel(io.BytesIO(excel_bytes))
    cols = _STAGE_COLUMNS.get(permit_stage, _STAGE_COLUMNS["Occupation Permits (OP) Issued"])

    projects = []
    current_block = None
    current_region = "Hong Kong Island"
    current_cat = "Domestic"

    for idx in range(7, len(df_raw)):
        row = df_raw.iloc[idx]

        # A fully blank row always closes out the in-progress project in
        # the live files -- flush it regardless of anchor state below.
        if row.isna().all():
            if current_block:
                projects.append(current_block)
                current_block = None
            continue

        c0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        c1 = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else ""

        # Region/category section headers only ever appear between
        # projects (right after a blank-row flush leaves current_block
        # None) in the live files. A wrapped address line can coincidally
        # read exactly "New Territories" or similar mid-project (confirmed
        # on Md56's Hoi Ying Road project), so these checks must not fire
        # while a project is still being accumulated.
        if current_block is None:
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

        blocks_value = _col(row, cols["blocks_col"])
        num_blocks = safe_int(blocks_value)
        building_type_raw = _col(row, cols["building_type_col"])
        building_type = str(building_type_raw).strip() if pd.notna(building_type_raw) and str(building_type_raw).strip() else None
        is_new_project_header = num_blocks is not None and building_type is not None

        if current_block is None and not is_new_project_header:
            # Stray row (footnote, leftover header text) with no active
            # project and no valid header signal -- nothing to attach it to.
            continue

        if is_new_project_header:
            if current_block:
                projects.append(current_block)

            permit_match = PERMIT_REGEX.search(str(_col(row, cols["permit_col"]) or "")) if cols["permit_col"] is not None else None
            num_storeys = safe_int(_col(row, cols["storeys_col"]))
            units_count = safe_int(_col(row, cols["units_col"]))
            domestic_gfa = safe_float(_col(row, cols["domestic_gfa_col"]))
            non_domestic_gfa = safe_float(_col(row, cols["non_domestic_gfa_col"]))
            domestic_ufa = safe_float(_col(row, cols["domestic_ufa_col"]))
            non_domestic_ufa = safe_float(_col(row, cols["non_domestic_ufa_col"]))
            # Prefer usable floor area when the table publishes it; Md53
            # (Plans Approved) only publishes GFA, so fall back to that.
            ufa_sqm = domestic_ufa if domestic_ufa is not None else domestic_gfa
            if current_cat == "Non-domestic":
                ufa_sqm = non_domestic_ufa if non_domestic_ufa is not None else non_domestic_gfa

            current_block = {
                'permit_stage': permit_stage,
                'address_lines': [c0] if c0 else [],
                'permit_number': permit_match.group(1) if permit_match else None,
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
        else:
            # Continuation row of the in-progress project block: merge its
            # unit-size tier into the running total, its address text (if
            # any) into the address, and its site area if present.
            units_val = safe_int(_col(row, cols["units_col"])) if cols["units_col"] is not None else None
            if units_val is not None:
                current_block['domestic_units_count'] = (current_block.get('domestic_units_count') or 0) + units_val

            if c0 and not c0.startswith("TABLE") and not c0.startswith("Address"):
                if "Site Area:" in c0:
                    site_area_match = re.search(r'Site Area:\s*([\d\.,]+)', c0)
                    if site_area_match:
                        current_block['site_area_sqm'] = safe_float(site_area_match.group(1))
                elif (
                    not c0.startswith("Class of Site")
                    and not c0.startswith("1.")
                    and not c0.startswith("Note")
                    and not PERMIT_CLASS_REF_REGEX.match(c0)
                ):
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

def fetch_bd_supply_leading_indicators() -> pd.DataFrame:
    """
    Aggregate project lifecycle events into monthly macro supply indicators by stage, region, and category.
    Acts as the primary leading indicator for future housing supply.
    """
    df_projects = fetch_bd_project_lifecycle_events()
    if df_projects.empty:
        return pd.DataFrame()

    current_month = datetime.now(timezone.utc).strftime("%Y-%m-01")
    
    grouped = df_projects.groupby(['permit_stage', 'region', 'property_category'])
    indicators = []
    
    for (stage, region, cat), grp in grouped:
        indicators.append({
            'date': current_month,
            'observation_month': current_month,
            'permit_stage': stage,
            'region': region,
            'property_category': cat,
            'total_projects_count': len(grp),
            'total_domestic_units': float(grp['domestic_units_count'].sum(skipna=True)),
            'total_usable_floor_area_sqm': float(grp['usable_floor_area_sqm'].sum(skipna=True)),
            'total_site_area_sqm': float(grp['site_area_sqm'].sum(skipna=True)),
            'source_agency': 'Hong Kong Buildings Department'
        })
        
    res_df = pd.DataFrame(indicators)
    if not res_df.empty:
        res_df = res_df.sort_values(['permit_stage', 'region']).reset_index(drop=True)
    return res_df
