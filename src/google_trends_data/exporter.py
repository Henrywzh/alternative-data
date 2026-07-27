from __future__ import annotations

import csv
from datetime import datetime
from datetime import timezone
from pathlib import Path
from time import monotonic
from time import sleep
from urllib.parse import urlencode

import requests


class GoogleTrendsCsvExporter:
    def __init__(self, *, profile_dir: str | Path, timeout_ms: int = 30000, max_attempts: int = 5) -> None:
        self.profile_dir = Path(profile_dir).expanduser()
        self.timeout_ms = timeout_ms
        self.max_attempts = max_attempts

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
        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{self._slug(keyword)}_{geo.lower() if geo else 'worldwide'}_interest_over_time.csv"

        url = self.build_explore_url(keyword=keyword, geo=geo, timeframe=timeframe, hl=hl)
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                self._export_attempt(
                    url=url,
                    target_path=target_path,
                    headless=headless,
                )
                return target_path
            except Exception as exc:
                last_error = exc

            if attempt < self.max_attempts:
                sleep(min(attempt * 2, 10))

        if last_error is not None:
            raise last_error
        raise ValueError("Google Trends CSV export did not run")

    def _export_attempt(self, *, url: str, target_path: Path, headless: bool) -> None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                accept_downloads=True,
                headless=headless,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                download_buttons = self._wait_for_download_buttons(page)
                for download_button in download_buttons:
                    try:
                        with page.expect_download(timeout=self.timeout_ms) as download_info:
                            download_button.click()
                        download = download_info.value
                        download.save_as(str(target_path))
                    except Exception:
                        continue
                    if self._download_contains_timeseries_header(target_path):
                        return
            finally:
                context.close()

        preview = self._download_preview(target_path) if target_path.exists() else ""
        raise ValueError(
            "Downloaded Google Trends CSV did not contain a Day/Week/Month header. "
            f"Preview: {preview}. This usually means the automation clicked a non-timeseries export "
            "or Google Trends served an incomplete/blocked page state."
        )

    @staticmethod
    def _slug(value: str) -> str:
        return value.lower().replace(" ", "_").replace(".", "_").replace("/", "_")

    def _dismiss_common_dialogs(self, page) -> None:
        dialog_labels = [
            "I agree",
            "Accept all",
            "Accept",
            "Got it",
            "OK, got it",
        ]
        for label in dialog_labels:
            locator = page.get_by_role("button", name=label)
            if locator.count():
                try:
                    locator.first.click(timeout=2000)
                except Exception:
                    continue

    def _wait_for_download_buttons(self, page):
        deadline = monotonic() + (self.timeout_ms / 1000)
        last_error: ValueError | None = None
        while monotonic() < deadline:
            self._dismiss_common_dialogs(page)
            try:
                buttons = self._candidate_download_buttons(page)
                if buttons:
                    return buttons
                raise ValueError("Could not locate Google Trends CSV download button")
            except ValueError as exc:
                last_error = exc
                page.wait_for_timeout(1000)

        if last_error is not None:
            raise last_error
        raise ValueError("Could not locate Google Trends CSV download button")

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
        buttons = self._candidate_download_buttons(page)
        if buttons:
            return buttons[0]

        raise ValueError("Could not locate Google Trends CSV download button")

    def _candidate_download_buttons(self, page):
        ordered_buttons = []
        seen = set()

        interest_over_time = page.locator("widget").filter(has_text="Interest over time").locator("button[title='CSV']")
        if not interest_over_time.count():
            return ordered_buttons

        self._extend_unique_buttons(ordered_buttons, seen, interest_over_time)

        candidates = [
            page.locator("button[title='CSV']"),
            page.get_by_role("button", name="CSV"),
            page.get_by_label("CSV"),
            page.locator("button[aria-label*='CSV']"),
            page.locator("[data-tooltip*='CSV']"),
        ]
        for locator in candidates:
            self._extend_unique_buttons(ordered_buttons, seen, locator)
        return ordered_buttons

    @staticmethod
    def _pick_topmost_button(locator):
        best = None
        best_key = None
        for index in range(locator.count()):
            candidate = locator.nth(index)
            box = candidate.bounding_box()
            if not box:
                continue
            key = (box.get("y", float("inf")), box.get("x", float("inf")))
            if best is None or key < best_key:
                best = candidate
                best_key = key
        return best or locator.first

    def _extend_unique_buttons(self, ordered_buttons, seen, locator) -> None:
        if not locator.count():
            return
        indexed = []
        for index in range(locator.count()):
            candidate = locator.nth(index)
            box = candidate.bounding_box()
            if not box:
                continue
            key = (box.get("y", float("inf")), box.get("x", float("inf")))
            indexed.append((key, candidate))

        for key, candidate in sorted(indexed):
            if key in seen:
                continue
            seen.add(key)
            ordered_buttons.append(candidate)

    @staticmethod
    def _download_contains_timeseries_header(csv_path: str | Path) -> bool:
        path = Path(csv_path)
        rows = csv.reader(path.open(encoding="utf-8"))
        for row in rows:
            if row and row[0].strip().lower() in {"day", "week", "month"}:
                return True
        return False

    @staticmethod
    def _download_preview(csv_path: str | Path, *, max_lines: int = 3) -> str:
        path = Path(csv_path)
        return " | ".join(path.read_text(encoding="utf-8").splitlines()[:max_lines])


class SerpApiCsvExporter:
    """Fetch Google Trends timeseries through SerpApi and emit importer-compatible CSV."""

    endpoint = "https://serpapi.com/search.json"

    def __init__(self, *, api_key: str, timeout_ms: int = 30000) -> None:
        self.api_key = api_key
        self.timeout_ms = timeout_ms

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
        if not self.api_key:
            raise ValueError("SERP_API_KEY is required for the SerpApi fallback")

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{self._slug(keyword)}_{geo.lower() if geo else 'worldwide'}_interest_over_time.csv"
        params = {
            "engine": "google_trends",
            "q": keyword,
            "date": timeframe,
            "hl": hl.split("-", 1)[0],
            "data_type": "TIMESERIES",
            "api_key": self.api_key,
        }
        if geo:
            params["geo"] = geo

        response = requests.get(self.endpoint, params=params, timeout=self.timeout_ms / 1000)
        response.raise_for_status()
        payload = response.json()
        metadata = payload.get("search_metadata", {})
        if metadata.get("status") != "Success":
            raise ValueError(f"SerpApi Google Trends request failed: {payload.get('error', metadata)}")

        timeline = payload.get("interest_over_time", {}).get("timeline_data", [])
        if not timeline:
            raise ValueError("SerpApi returned no Google Trends timeseries data")

        rows: list[tuple[str, int, bool]] = []
        for point in timeline:
            values = [value for value in point.get("values", []) if value.get("query") == keyword]
            if not values:
                raise ValueError(f"SerpApi response omitted query {keyword!r} from a timeseries point")
            extracted_value = values[0].get("extracted_value")
            if extracted_value is None:
                raise ValueError(f"SerpApi response omitted a value for {keyword!r}")
            date = datetime.fromtimestamp(int(point["timestamp"]), tz=timezone.utc).date().isoformat()
            rows.append((date, int(extracted_value), bool(point.get("partial_data", False))))

        with target_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Week", keyword, "isPartial"])
            writer.writerows(rows)
        return target_path

    @staticmethod
    def _slug(value: str) -> str:
        return value.lower().replace(" ", "_").replace(".", "_").replace("/", "_")


class FallbackGoogleTrendsExporter:
    """Try one CSV export, then use SerpApi, spacing every outbound search."""

    def __init__(self, *, primary, fallback, delay_seconds: float = 2.0) -> None:
        self.primary = primary
        self.fallback = fallback
        self.delay_seconds = max(0.0, delay_seconds)
        self._last_request_at: float | None = None
        self.sources: list[str] = []

    def export_interest_over_time(self, **kwargs) -> Path:
        try:
            result = self._call(self.primary, **kwargs)
            self.sources.append("csv")
            return result
        except Exception as primary_error:
            try:
                result = self._call(self.fallback, **kwargs)
                self.sources.append("serpapi")
                return result
            except Exception as fallback_error:
                raise RuntimeError(
                    "Google Trends CSV export failed once and SerpApi fallback also failed. "
                    f"CSV error: {primary_error}; SerpApi error: {fallback_error}"
                ) from fallback_error

    def _call(self, exporter, **kwargs) -> Path:
        self._wait_between_requests()
        try:
            return exporter.export_interest_over_time(**kwargs)
        finally:
            self._last_request_at = monotonic()

    def _wait_between_requests(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.delay_seconds - (monotonic() - self._last_request_at)
        if remaining > 0:
                sleep(remaining)

    def source_summary(self) -> str:
        return ",".join(dict.fromkeys(self.sources))
