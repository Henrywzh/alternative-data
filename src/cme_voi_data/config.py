from __future__ import annotations

DEFAULT_PRODUCT_CODES = {
    "ES": {"name": "E-mini S&P 500", "category": "Equity", "exchange": "CME"},
    "NQ": {"name": "E-mini Nasdaq 100", "category": "Equity", "exchange": "CME"},
    "SR3": {"name": "Three-Month SOFR Futures", "category": "Rates", "exchange": "CME"},
    "ZN": {"name": "10-Year Treasury Note", "category": "Rates", "exchange": "CBOT"},
    "GC": {"name": "Gold Futures", "category": "Metals", "exchange": "COMEX"},
    "CL": {"name": "Crude Oil WTI", "category": "Energy", "exchange": "NYMEX"},
    "HG": {"name": "Copper Futures", "category": "Metals", "exchange": "COMEX"},
}

CME_DAILY_BULLETIN_BASE_URL = "https://www.cmegroup.com/daily_bulletin/current"
CME_MONTHLY_ARCHIVE_BASE_URL = "https://www.cmegroup.com/ftp/webmthly"
CME_BULLETIN_FILES = {
    "equity": "Section01C_Summary_Volume_And_Open_Interest_Equity_Index_Futures_And_Options.pdf",
    "rates": "Section02A_Summary_Volume_And_Open_Interest_Int_Rates_Futures_And_Options.pdf",
    "metals": "Section02B_Summary_Volume_And_Open_Interest_Metals_Futures_And_Options.pdf",
    "energy": "Section02C_Summary_Volume_And_Open_Interest_Energy_Futures_And_Options.pdf",
}
