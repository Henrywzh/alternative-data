import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from ..config import REGISTRY_DIR

REGISTRY_CSV_PATH = REGISTRY_DIR / "hk_developer_project_registry.csv"

class DeveloperRegistry:
    """
    Registry matcher linking project names, site addresses, and aliases to HKEX listed developers and REITs.
    Categorizes matches into confidence tiers: EXACT, ALIAS, FUZZY, or UNMATCHED.
    """
    def __init__(self, csv_path: Path = REGISTRY_CSV_PATH):
        self.csv_path = csv_path
        self.df = self._load_registry()

    def _load_registry(self) -> pd.DataFrame:
        if self.csv_path.exists():
            df = pd.read_csv(self.csv_path, dtype={'stock_code': str})
            df['stock_code'] = df['stock_code'].str.zfill(4)
            return df
        return pd.DataFrame(columns=[
            'stock_code', 'listed_company_en', 'listed_company_zh',
            'subsidiary_spv_name', 'project_name_en', 'project_name_zh',
            'project_aliases', 'district', 'asset_type', 'ownership_pct',
            'source_document', 'last_verified_date', 'effective_from', 'effective_to'
        ])

    def match_project(self, query: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Match a project name or site address against the developer registry.
        Returns tuple: (matched_dict_or_none, confidence_tier: 'EXACT' | 'ALIAS' | 'FUZZY' | 'UNMATCHED')
        """
        if not query or self.df.empty:
            return None, "UNMATCHED"
            
        q_clean = str(query).strip().lower()
        
        # 1. Exact Match on project names
        for _, row in self.df.iterrows():
            name_en = str(row.get('project_name_en', '')).lower()
            name_zh = str(row.get('project_name_zh', '')).lower()
            if q_clean == name_en or q_clean == name_zh:
                return row.to_dict(), "EXACT"
                
        # 2. Alias Match
        for _, row in self.df.iterrows():
            aliases = [a.lower() for a in str(row.get('project_aliases', '')).split('|') if a]
            if q_clean in aliases:
                return row.to_dict(), "ALIAS"

        # 3. Substring / Fuzzy Match
        for _, row in self.df.iterrows():
            name_en = str(row.get('project_name_en', '')).lower()
            name_zh = str(row.get('project_name_zh', '')).lower()
            aliases = [a.lower() for a in str(row.get('project_aliases', '')).split('|') if a]
            all_names = [name_en, name_zh] + aliases
            
            for target in all_names:
                if target and len(target) >= 3:
                    if target in q_clean or q_clean in target:
                        return row.to_dict(), "FUZZY"
                
        return None, "UNMATCHED"

    def attribute_dataframe(self, df: pd.DataFrame, project_col: str = 'project_name') -> pd.DataFrame:
        """
        Attribute a DataFrame of project entries with developer stock codes and confidence tiers.
        """
        if df.empty or project_col not in df.columns:
            return df

        stock_codes = []
        company_names = []
        ownership_pcts = []
        asset_types = []
        confidence_tiers = []

        unmatched_count = 0

        for val in df[project_col]:
            match, tier = self.match_project(val)
            confidence_tiers.append(tier)
            if match:
                stock_codes.append(match.get('stock_code'))
                company_names.append(match.get('listed_company_en'))
                ownership_pcts.append(match.get('ownership_pct'))
                asset_types.append(match.get('asset_type'))
            else:
                unmatched_count += 1
                stock_codes.append(None)
                company_names.append(None)
                ownership_pcts.append(None)
                asset_types.append(None)

        df['matched_stock_code'] = stock_codes
        df['matched_listed_company'] = company_names
        df['matched_ownership_pct'] = ownership_pcts
        df['matched_asset_type'] = asset_types
        df['match_confidence_tier'] = confidence_tiers

        unmatched_rate = (unmatched_count / len(df) * 100.0) if len(df) > 0 else 0.0
        df.attrs['unmatched_rate_pct'] = round(unmatched_rate, 2)
        df.attrs['unmatched_count'] = unmatched_count
        df.attrs['total_count'] = len(df)
        return df
