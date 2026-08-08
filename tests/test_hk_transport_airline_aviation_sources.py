import pandas as pd
from src.hk_transport.sources.airline_aviation_source_registry import (
    AVIATION_SOURCES,
    fetch_airline_aviation_source_registry,
)


def test_aviation_source_registry_structure():
    df = fetch_airline_aviation_source_registry()
    assert not df.empty
    assert 'source_id' in df.columns
    assert 'source_tier' in df.columns
    assert 'reproducibility_score' in df.columns

    # Verify primary official filing source
    pdf_source = df[df['source_id'].eq('issuer_annual_report_filing')].iloc[0]
    assert pdf_source['source_tier'] == 'primary_official'
    assert '9 Air' in str(pdf_source['source_note'])
    assert '189 seats' in str(pdf_source['source_note'])

    # Verify Ctrip SSR fallback source
    ctrip_source = df[df['source_id'].eq('ctrip_ssr_train_booking')].iloc[0]
    assert ctrip_source['source_tier'] == 'secondary_aggregator'
    assert ctrip_source['reproducibility_score'] == 'high_100pct_reproducible'
