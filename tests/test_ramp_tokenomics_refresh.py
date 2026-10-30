from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pytest

from dashboard.sections.ramp_tokenomics import activity_pivot
from ramp_data.models import RunContext, Snapshot
from ramp_data.pipeline import RampPipeline, ValidationError
from ramp_data.sources.ai_index import RampAiIndexSource
from ramp_data.sources.tokenomics import RampTokenomicsSource


def test_versioned_endpoints_are_captured_and_extracted(monkeypatch):
    monkeypatch.setattr(RampAiIndexSource, 'fetch_snapshots', lambda self: [Snapshot('ai_index', 'https://ramp.com/data/ai-index', '{"dataVersion":"version-1"}')])
    source = RampTokenomicsSource(max_retries=1)
    class Response:
        def __init__(self, key):
            self.url = 'https://ramp.com/data/ai-index/chart-data/' + key + '?version=version-1'
            self.text = json.dumps([{'metric_value': 3}] if key == 'tokenVolumes' else [{'usage_date': '2026-10-23'}])
        def raise_for_status(self):
            pass
    def get(url, params, timeout):
        assert params == {'version': 'version-1'}
        return Response(url.rsplit('/', 1)[-1])
    monkeypatch.setattr(source.session, 'get', get)
    snapshots = source.fetch_snapshots()
    rows = source.extract(snapshots, RunContext('test', datetime.now(timezone.utc)))
    assert [s.name for s in snapshots] == ['ai_index', 'tokenVolumes', 'tokenPrices']
    assert rows['ramp_ai_token_activity'][0].payload['metric_value'] == 3
    assert '/chart-data/tokenVolumes?' in rows['ramp_ai_token_activity'][0].source_url
    assert rows['ramp_ai_token_prices'][0].payload['usage_date'] == '2026-10-23'


def test_weekly_chart_does_not_mix_overlapping_reporting_calendars():
    frame = pd.DataFrame([
        {'period_end': '2026-10-18', 'metric_key': 'token_spend', 'metric_value': 10, 'model_maker': 'openai', 'series_key': 'a'},
        {'period_end': '2026-10-23', 'metric_key': 'token_spend', 'metric_value': 15, 'model_maker': 'openai', 'series_key': 'a'},
        {'period_end': '2026-10-09', 'metric_key': 'token_spend', 'metric_value': 12, 'model_maker': 'openai', 'series_key': 'a'},
    ])
    pivot = activity_pivot(frame, 'token_spend', 'By model maker')
    assert list(pivot.index.strftime('%Y-%m-%d')) == ['2026-10-09', '2026-10-16', '2026-10-23']
    assert pd.isna(pivot.iloc[1, 0])
    assert pivot.iloc[-1, 0] == 15


def test_missing_chart_data_remains_a_quality_failure():
    with pytest.raises(ValidationError, match='only 0 rows'):
        RampPipeline._assert_tokenomics_quality([], {})


def test_weekly_gate_accepts_new_calendar_and_rejects_mixed(monkeypatch):
    from ramp_data.models import GenericRecord
    from ramp_data.schemas import TOKENOMICS_DATASETS
    monkeypatch.setitem(TOKENOMICS_DATASETS['ramp_ai_token_activity'], 'min_rows', 2)
    monkeypatch.setitem(TOKENOMICS_DATASETS['ramp_ai_token_prices'], 'min_rows', 3)
    today = datetime.now(timezone.utc).date()
    friday = today - timedelta(days=(today.weekday() - 4) % 7)
    def record(dataset, payload):
        return GenericRecord(dataset, 'https://ramp.com', 'test', datetime.now(timezone.utc).isoformat(), payload)
    activity = [record('ramp_ai_token_activity', {
        'period_grain': 'weekly', 'period_start': (friday - timedelta(days=6)).isoformat(),
        'period_end': friday.isoformat(), 'metric_key': metric, 'dimension_type': 'model',
        'series_key': 'm', 'series_label': 'M', 'model_maker': 'openai', 'metric_value': 1,
    }) for metric in ('token_volume', 'token_spend')]
    prices = [record('ramp_ai_token_prices', {
        'usage_date': friday.isoformat(), 'token_type': kind, 'model_maker': 'openai',
        'token_cost_usd_7d': 1, 'token_count_7d': 1,
    }) for kind in ('all_tokens', 'uncached_input', 'output')]
    rows = {'ramp_ai_token_activity': activity, 'ramp_ai_token_prices': prices}
    assert RampPipeline._assert_tokenomics_quality([], rows)['ramp_ai_token_activity']['rows'] == 2
    sunday = friday + timedelta(days=2)
    if sunday > today:
        sunday -= timedelta(days=7)
    activity[0].payload.update(period_start=(sunday - timedelta(days=6)).isoformat(), period_end=sunday.isoformat())
    with pytest.raises(ValidationError, match='mixed weekly reporting calendars'):
        RampPipeline._assert_tokenomics_quality([], rows)
