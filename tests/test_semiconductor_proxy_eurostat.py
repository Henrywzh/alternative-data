from __future__ import annotations

import json
from semiconductor_proxy_data.models import Snapshot
from semiconductor_proxy_data.sources.eurostat import EurostatSource


def test_eurostat_source_extraction() -> None:
    source = EurostatSource()
    body = {
        "version": "2.0",
        "class": "dataset",
        "label": "EU trade since 1988 by HS2-4-6 and CN8",
        "source": "ESTAT",
        "updated": "2026-06-15T11:00:00+0200",
        "value": {
            "0": 100000.0,
            "1": 200000.0,
            "6": 300000.0,
            "7": 400000.0,
            "12": 500000.0,
            "13": 600000.0
        },
        "id": ["freq", "reporter", "partner", "product", "flow", "indicators", "time"],
        "size": [1, 1, 3, 1, 1, 3, 2],
        "dimension": {
            "freq": {"label": "Frequency", "category": {"index": {"M": 0}, "label": {"M": "Monthly"}}},
            "reporter": {"label": "REPORTER", "category": {"index": {"NL": 0}, "label": {"NL": "Netherlands"}}},
            "partner": {"label": "PARTNER", "category": {"index": {"CN": 0, "KR": 1, "TW": 2}, "label": {"CN": "China", "KR": "South Korea", "TW": "Taiwan"}}},
            "product": {"label": "PRODUCT", "category": {"index": {"84862000": 0}, "label": {"84862000": "Machines and apparatus"}}},
            "flow": {"label": "FLOW", "category": {"index": {"2": 0}, "label": {"2": "EXPORT"}}},
            "indicators": {"label": "INDICATORS", "category": {"index": {"VALUE_IN_EUROS": 0, "QUANTITY_IN_100KG": 1, "SUPPLEMENTARY_QUANTITY": 2}, "label": {"VALUE_IN_EUROS": "Value", "QUANTITY_IN_100KG": "Quantity", "SUPPLEMENTARY_QUANTITY": "Supplementary"}}},
            "time": {"label": "TIME_PERIOD", "category": {"index": {"2025-01": 0, "2025-02": 1}, "label": {"2025-01": "2025-01", "2025-02": "2025-02"}}}
        }
    }
    snapshot = Snapshot(
        name="official_netherlands_lithography_2025-01_2025-02",
        source_url="http://mocked/eurostat",
        body=json.dumps(body),
    )

    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-07-14T00:00:00Z")
    
    # We expect 3 partners * 2 time periods = 6 data points
    assert len(points) == 6
    
    # Check first point (China - 2025-01)
    p0 = [p for p in points if p.partner_scope == "cn" and p.period == "2025-01"][0]
    assert p0.source_region == "netherlands"
    assert p0.country_name == "Netherlands"
    assert p0.category_id == "lithography"
    assert p0.category_label == "Lithography"
    assert p0.value == 100000.0
    assert p0.currency == "EUR"
    assert p0.unit == "eur"
    
    # Check South Korea - 2025-02
    p1 = [p for p in points if p.partner_scope == "kr" and p.period == "2025-02"][0]
    assert p1.value == 400000.0
    
    # Check Taiwan - 2025-01
    p2 = [p for p in points if p.partner_scope == "tw" and p.period == "2025-01"][0]
    assert p2.value == 500000.0
    
    # Verify catalog point
    catalog = source.catalog_points(run_id="test-run", scraped_at="2026-07-14T00:00:00Z")
    assert len(catalog) == 1
    assert catalog[0].source_region == "netherlands"
    assert catalog[0].category_id == "lithography"
