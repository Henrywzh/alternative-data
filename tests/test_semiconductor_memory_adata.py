from __future__ import annotations

from semiconductor_memory_data.models import Snapshot
from semiconductor_memory_data.sources.adata import AdataEDMSource


def test_fetch_snapshots_month_prefers_discovered_archive_url(monkeypatch) -> None:
    source = AdataEDMSource()

    monkeypatch.setattr(
        source,
        "list_report_urls",
        lambda: ["https://industrial.adata.com/en/edm/Market%20Watch_202501"],
    )

    captured: list[str] = []

    def fake_fetch(url: str) -> Snapshot:
        captured.append(url)
        return Snapshot(name="test", source_url=url, body="<html></html>")

    monkeypatch.setattr(source, "_fetch_single", fake_fetch)

    snapshots = source.fetch_snapshots(month="2025-01")

    assert len(snapshots) == 1
    assert captured == ["https://industrial.adata.com/en/edm/Market%20Watch_202501"]


def test_parse_report_uses_url_month_when_heading_is_stale() -> None:
    source = AdataEDMSource()
    snapshot = Snapshot(
        name="marketwatch_202511",
        source_url="https://industrial.adata.com/en/edm/MarketWatch_202511",
        body="""
        <html>
          <body>
            <h1>Monthly Memory & Flash Market Watch</h1>
            <h2>October 2025</h2>
            <a href="https://industrial-ad.adata.com/storage/edms/202511_flash_1.JPG"><img src="thumb1.jpg" /></a>
            <a href="https://industrial-ad.adata.com/storage/edms/202511_dram_1.JPG"><img src="thumb2.jpg" /></a>
          </body>
        </html>
        """,
    )

    raw_point, image_points, monthly_point = source._parse_report(snapshot)

    assert raw_point.month == "2025-11"
    assert monthly_point.month == "2025-11"
    assert {point.month for point in image_points} == {"2025-11"}
