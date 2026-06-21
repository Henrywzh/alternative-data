from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

from semiconductor_proxy_data.models import ComtradePoint, Snapshot


class TradingEconomicsSource:
    URL = "https://tradingeconomics.com/south-korea/exports-of-semi-conductor"

    def __init__(self, session: requests.Session | None = None, timeout: int = 30) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout

    def fetch_snapshots(self) -> list[Snapshot]:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        response = self.session.get(self.URL, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return [Snapshot(name="tradingeconomics_korea", body=response.text, source_url=self.URL)]

    def extract(self, snapshots: list[Snapshot], run_id: str, scraped_at: str) -> list[ComtradePoint]:
        points: list[ComtradePoint] = []
        for snapshot in snapshots:
            if not snapshot.name.startswith("tradingeconomics_"):
                continue

            soup = BeautifulSoup(snapshot.body, "html.parser")
            meta_desc = soup.find("meta", {"id": "metaDesc"})
            if not meta_desc:
                meta_desc = soup.find("meta", {"name": "description"})

            if meta_desc and meta_desc.get("content"):
                content = str(meta_desc.get("content"))
                # Match e.g.: "increased to 11671000 USD Thousand in March from 9946000 USD Thousand in February of 2024"
                # Or sometimes "decreased to..."
                match = re.search(
                    r"(?:increased|decreased) to (\d+) USD Thousand in (\w+) from (\d+) USD Thousand in (\w+) of (\d{4})",
                    content,
                    re.IGNORECASE
                )
                if match:
                    actual_val = float(match.group(1)) * 1000
                    actual_month_name = match.group(2)
                    year = int(match.group(5))

                    months_map = {
                        "january": "01", "february": "02", "march": "03", "april": "04",
                        "may": "05", "june": "06", "july": "07", "august": "08",
                        "september": "09", "october": "10", "november": "11", "december": "12"
                    }

                    actual_month = months_map.get(actual_month_name.lower())
                    if actual_month:
                        period = f"{year}-{actual_month}"
                        points.append(
                            ComtradePoint(
                                dataset_id="semiconductor_monthly_trade",
                                reporter_code=410,
                                reporter_name="South Korea",
                                partner_code=0,
                                partner_name="World",
                                flow_code="X",
                                period=period,
                                cmd_code="8542",
                                trade_value_usd=actual_val,
                                net_weight_kg=None,
                                source_url=self.URL,
                                source_run_id=run_id,
                                scraped_at=scraped_at,
                            )
                        )
        return points
