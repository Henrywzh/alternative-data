from __future__ import annotations

from datetime import datetime, timezone
import io
import re
import subprocess
import tempfile
from typing import Any

import requests

from .config import CME_BULLETIN_FILES, CME_DAILY_BULLETIN_BASE_URL, DEFAULT_PRODUCT_CODES
from .models import CmeObservation

class CmeBulletinClient:
    def __init__(self, timeout_seconds: float = 30.0, session: requests.Session | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/pdf"})

    def fetch_daily_bulletin(self, section: str) -> tuple[str, bytes]:
        filename = CME_BULLETIN_FILES[section]
        url = f"{CME_DAILY_BULLETIN_BASE_URL}/{filename}"
        response = self.session.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return url, response.content

    @staticmethod
    def extract_pdf_text(payload: bytes) -> str:
        """Extract text without adding a Python PDF parser dependency."""
        with tempfile.NamedTemporaryFile(suffix=".pdf") as input_file:
            input_file.write(payload)
            input_file.flush()
            result = subprocess.run(
                ["pdftotext", "-layout", input_file.name, "-"],
                check=True,
                capture_output=True,
                text=True,
            )
        return result.stdout

    @staticmethod
    def _number_tokens(text: str) -> list[float]:
        values: list[float] = []
        for token in re.findall(r"(?<![A-Z])[-+]?\d[\d,]*(?:\.\d+)?", text):
            try:
                values.append(float(token.replace(",", "")))
            except ValueError:
                continue
        return values

    @classmethod
    def parse_bulletin_products(
        cls,
        text: str,
        *,
        product_codes: list[str] | None = None,
        fetched_at: str | None = None,
    ) -> list[CmeObservation]:
        """Parse product rows from a CME Summary Volume/OI bulletin.

        The report is a fixed-width presentation.  For product rows, the
        final five numeric columns are overall volume, current OI, OI change,
        prior-year volume, and prior-year OI; rows with an omitted venue
        column simply contain one fewer leading number.  Settlement prices
        are not in this report and remain NULL by design.
        """
        fetched = fetched_at or datetime.now(timezone.utc).isoformat()
        wanted = set(product_codes or DEFAULT_PRODUCT_CODES)
        date_match = re.search(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s+([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", text)
        trade_date = ""
        if date_match:
            trade_date = datetime.strptime(date_match.group(1), "%b %d, %Y").date().isoformat()
        records: list[CmeObservation] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            code_match = re.match(r"^([A-Z0-9]{2,8})\s+(.+)$", stripped)
            if not code_match:
                continue
            code = code_match.group(1)
            if code not in wanted:
                continue
            numbers = cls._number_tokens(code_match.group(2))
            if len(numbers) < 5:
                continue
            volume, open_interest, oi_change = numbers[-5:-2]
            records.append(
                CmeObservation(
                    trade_date=trade_date,
                    product_code=code,
                    contract_month="ALL",
                    settle_price=None,
                    price_change=None,
                    volume=int(volume),
                    open_interest=int(open_interest),
                    open_interest_change=int(oi_change),
                    flow_regime=cls.classify_positioning_flow(None, int(oi_change)),
                    fetched_at=fetched,
                )
            )
        return records

    @staticmethod
    def classify_positioning_flow(price_change: float | None, oi_change: int | None) -> str:
        """Classify a (price change, OI change) pair into a flow regime.

        A missing input returns UNKNOWN, not NEUTRAL. The Summary Volume and
        Open Interest bulletin carries no settlement prices, so every row
        parsed from it has ``price_change=None`` -- and collapsing that into
        NEUTRAL made an unmeasurable row indistinguishable from a genuinely
        flat one. Every row in the table then read NEUTRAL while appearing to
        be a real classification.
        """
        if price_change is None or oi_change is None:
            return "UNKNOWN"
        if oi_change == 0 or price_change == 0:
            return "NEUTRAL"
        if price_change > 0 and oi_change > 0:
            return "BULLISH_INFLOW"
        if price_change < 0 and oi_change > 0:
            return "BEARISH_INFLOW"
        if price_change > 0 and oi_change < 0:
            return "SHORT_COVERING"
        if price_change < 0 and oi_change < 0:
            return "LONG_LIQUIDATION"
        return "NEUTRAL"
