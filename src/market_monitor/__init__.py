"""Index & ETF Allocation Monitor.

Tracks exposure -> index -> ETF wrapper across China, HK, and US markets.

Data flow mirrors financial-data's PIT philosophy (immutable raw observations,
normalized time series, then derived signals) but stays inside alternative-data
as its own domain; financial-data remains a pure fundamental/PIT DB.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
