from __future__ import annotations

from pathlib import Path
from time import monotonic
from urllib.parse import urlencode


class GoogleTrendsCsvExporter:
    def __init__(self, *, profile_dir: str | Path, timeout_ms: int = 30000) -> None:
        self.profile_dir = Path(profile_dir).expanduser()
        self.timeout_ms = timeout_ms

    @staticmethod
    def build_explore_url(*, keyword: str, geo: str, timeframe: str, hl: str) -> str:
        params = {
            "date": timeframe,
            "q": keyword,
            "hl": hl,
        }
        if geo:
            params["geo"] = geo
        return f"https://trends.google.com/trends/explore?{urlencode(params)}"

    def export_interest_over_time(
        self,
        *,
        keyword: str,
        geo: str,
        timeframe: str,
        hl: str,
        output_dir: str | Path,
        headless: bool,
    ) -> Path:
        from playwright.sync_api import sync_playwright

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{self._slug(keyword)}_{geo.lower() if geo else 'worldwide'}_interest_over_time.csv"

        url = self.build_explore_url(keyword=keyword, geo=geo, timeframe=timeframe, hl=hl)

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                accept_downloads=True,
                headless=headless,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                download_button = self._wait_for_download_button(page)
                with page.expect_download(timeout=self.timeout_ms) as download_info:
                    download_button.click()
                download = download_info.value
                download.save_as(str(target_path))
            finally:
                context.close()

        return target_path

    @staticmethod
    def _slug(value: str) -> str:
        return value.lower().replace(" ", "_").replace(".", "_").replace("/", "_")

    def _dismiss_common_dialogs(self, page) -> None:
        dialog_labels = [
            "I agree",
            "Accept all",
            "Accept",
            "Got it",
        ]
        for label in dialog_labels:
            locator = page.get_by_role("button", name=label)
            if locator.count():
                try:
                    locator.first.click(timeout=2000)
                except Exception:
                    continue

    def _wait_for_download_button(self, page):
        deadline = monotonic() + (self.timeout_ms / 1000)
        last_error: ValueError | None = None
        while monotonic() < deadline:
            self._dismiss_common_dialogs(page)
            try:
                return self._locate_download_button(page)
            except ValueError as exc:
                last_error = exc
                page.wait_for_timeout(1000)

        if last_error is not None:
            raise last_error
        raise ValueError("Could not locate Google Trends CSV download button")

    def _locate_download_button(self, page):
        candidates = [
            page.get_by_role("button", name="CSV"),
            page.get_by_label("CSV"),
            page.locator("button[title*='CSV']"),
            page.locator("button[aria-label*='CSV']"),
            page.locator("[data-tooltip*='CSV']"),
        ]
        for locator in candidates:
            if locator.count():
                return locator.first
        raise ValueError("Could not locate Google Trends CSV download button")
