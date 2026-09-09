"""Offline tests for the global market-regime radar."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from global_market_regime.alerts import (
    advance_alert_state,
    detect_state_changes,
    evaluate_alert,
    load_alert_state,
    save_alert_state,
)
from global_market_regime.pipeline import (
    classify_freshness,
    fresh_state_map,
    load_cross_asset_prices,
    run_pipeline,
    source_health_rows,
)
from global_market_regime.signals import classify_level_states, classify_sync_stress, consecutive_true
from global_market_regime.sources import (
    fetch_fred_observations,
    hike_probability_history,
    nearest_rate_window,
    parse_atlanta_mpt,
)


def _series(values: list[float], start: str = "2026-08-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"date": dates, "value": values})


def test_watch_then_confirmed_then_improving_then_normal() -> None:
    history = _series([4.70, 4.90, 4.95, 4.70, 4.60, 4.50])
    states = classify_level_states(history, enter=4.82, exit=4.82)
    assert list(states["state"]) == ["Normal", "Watch", "Confirmed", "Improving", "Normal", "Normal"]


def test_oil_four_of_five_persistent_confirms_before_three_straight_closes() -> None:
    # With a stricter 3-day consecutive gate, 101/101/99/101/101 still has only
    # two consecutive closes above $100, but four of the last five prints are
    # above the line and must confirm via the persistence rule.
    history = _series([101, 101, 99, 101, 101])
    states = classify_level_states(
        history,
        enter=100,
        exit=100,
        confirm_days=3,
        persistent_window=5,
        persistent_count=4,
    )
    assert list(states["consecutive_breach"]) == [1, 2, 0, 1, 2]
    assert states.iloc[-1]["state"] == "Confirmed"


def test_hike_window_change_resets_persistence() -> None:
    history = pd.DataFrame(
        {
            "date": pd.date_range("2026-08-01", periods=4, freq="B"),
            "value": [70.0, 72.0, 80.0, 81.0],
            "window_key": ["A", "A", "B", "B"],
        }
    )
    states = classify_level_states(history, enter=65, exit=55, escalate=75, reset_on="window_key")
    assert list(states["state"]) == ["Watch", "Confirmed", "Watch", "Escalating"]


def test_sync_stress_requires_shared_date() -> None:
    credit = _series([4.0, 4.2, 4.6, 5.1, 5.8, 6.4], start="2026-07-01")
    vix = _series([12.0, 12.5, 13.5, 16.0, 18.5, 21.0], start="2026-07-02")
    merged = classify_sync_stress(credit, vix)
    # Inner join drops the first credit date, so a lone latest print cannot fire.
    assert merged["date"].min() == pd.Timestamp("2026-07-02")
    assert "hy_z" in merged.columns


def test_consecutive_true_resets_on_false() -> None:
    flags = pd.Series([True, True, False, True])
    assert list(consecutive_true(flags)) == [1, 2, 0, 1]


def test_stale_snapshot_does_not_create_alert() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "brent",
                "state": "Confirmed",
                "freshness": "Stale",
                "observation_date": "2026-07-01",
                "label_zh": "布伦特原油",
                "label_en": "Brent",
                "value": 110,
            }
        ]
    )
    events = detect_state_changes(snapshot, {"brent": "Normal"})
    assert events == []


@pytest.mark.parametrize("observation_date", [None, float("nan"), "not-a-date"])
def test_invalid_observation_date_does_not_create_alert(observation_date) -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "credit_vix",
                "state": "Confirmed",
                "freshness": "Current session",
                "observation_date": observation_date,
            }
        ]
    )

    decision = evaluate_alert(
        snapshot,
        state={"last_states": {"credit_vix": "Normal"}},
        mode="defensive",
    )

    assert decision["events"] == []
    assert decision["should_send"] is False
    assert decision["defensive_alert_eligible"] is False


def test_single_domain_state_change_is_preview_not_defensive_alert() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "us10y",
                "state": "Watch",
                "freshness": "Last session",
                "observation_date": "2026-09-02",
                "label_zh": "美国10年期",
                "label_en": "US10Y",
                "value": 4.9,
            }
        ]
    )
    decision = evaluate_alert(snapshot, state={"last_states": {"us10y": "Normal"}, "sent_event_keys": []})
    assert decision["should_send"] is False
    assert decision["kind"] == "component_preview"
    assert decision["defensive_alert_eligible"] is False
    assert decision["events"][0]["to_state"] == "Watch"


def test_two_confirmed_domains_create_defensive_alert() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "brent",
                "state": "Confirmed",
                "freshness": "Last session",
                "observation_date": "2026-09-02",
            },
            {
                "indicator_id": "us10y",
                "state": "Confirmed",
                "freshness": "Last session",
                "observation_date": "2026-09-02",
            },
        ]
    )

    decision = evaluate_alert(snapshot, state={"last_states": {}, "sent_event_keys": []})

    assert decision["should_send"] is True
    assert decision["kind"] == "defensive"
    assert decision["confirmed_domain_count"] == 2


def test_confirmed_financial_stress_alone_creates_defensive_alert() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "credit_vix",
                "state": "Confirmed",
                "freshness": "Current session",
                "observation_date": "2026-09-04",
            }
        ]
    )

    decision = evaluate_alert(snapshot, state={"last_states": {}, "sent_event_keys": []})

    assert decision["should_send"] is True
    assert decision["confirmed_domain_ids"] == ["financial_stress"]


def test_preview_records_defensive_eligibility_without_sending() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "credit_vix",
                "state": "Confirmed",
                "freshness": "Current session",
                "observation_date": "2026-09-04",
            }
        ]
    )

    decision = evaluate_alert(
        snapshot,
        state={"last_states": {"credit_vix": "Normal"}},
        mode="preview",
    )

    assert decision["kind"] == "defensive_eligible"
    assert decision["should_send"] is False


def test_preview_mode_never_sends_and_does_not_advance_stale_state() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "brent",
                "state": "Confirmed",
                "freshness": "Stale",
                "observation_date": "2026-08-01",
            },
            {
                "indicator_id": "us10y",
                "state": "Confirmed",
                "freshness": "Last session",
                "observation_date": "2026-09-02",
            },
        ]
    )

    decision = evaluate_alert(
        snapshot,
        state={"last_states": {}, "sent_event_keys": []},
        mode="preview",
    )
    updated = advance_alert_state(
        snapshot,
        events=decision["events"],
        decision=decision,
        state={"last_states": {}, "sent_event_keys": []},
        sent=False,
        mode="preview",
        run_id="run-a",
    )

    assert decision["should_send"] is False
    assert updated["last_states"] == {"us10y": "Confirmed"}
    assert updated["last_decision"] == "component_preview"
    assert updated["alert_mode"] == "preview"
    assert updated["last_run_id"] == "run-a"


def test_alert_evaluation_fails_closed_without_freshness_column() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "credit_vix",
                "state": "Confirmed",
                "observation_date": "2026-09-04",
            }
        ]
    )

    decision = evaluate_alert(snapshot, state={"last_states": {}})

    assert decision["events"] == []
    assert decision["should_send"] is False
    assert decision["defensive_alert_eligible"] is False


def test_alert_evaluation_fails_closed_for_unknown_freshness_value() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "credit_vix",
                "state": "Confirmed",
                "freshness": "Unknown",
                "observation_date": "2026-09-04",
            }
        ]
    )

    decision = evaluate_alert(snapshot, state={"last_states": {}})
    updated = advance_alert_state(
        snapshot,
        events=decision["events"],
        state={"last_states": {"credit_vix": "Normal"}},
        sent=False,
    )

    assert decision["events"] == []
    assert decision["should_send"] is False
    assert decision["defensive_alert_eligible"] is False
    assert updated["last_states"] == {"credit_vix": "Normal"}


def test_alert_state_write_is_atomic_on_interruption(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "alert-state.json"
    original = {
        "version": 1,
        "last_states": {"brent": "Normal"},
        "last_overall": "Normal",
    }
    state_path.write_text(json.dumps(original), encoding="utf-8")
    real_write_text = Path.write_text

    def interrupted_write(path, payload, *args, **kwargs):
        real_write_text(path, "{", encoding=kwargs.get("encoding", "utf-8"))
        raise OSError("simulated interruption")

    monkeypatch.setattr(Path, "write_text", interrupted_write)

    with pytest.raises(OSError, match="simulated interruption"):
        save_alert_state(
            {
                "version": 1,
                "last_states": {"brent": "Confirmed"},
                "last_overall": "Confirmed",
            },
            state_path,
        )

    assert load_alert_state(state_path)["last_states"] == {"brent": "Normal"}


@pytest.mark.parametrize("value", [pd.NA, pd.NaT, float("nan")])
def test_email_missing_values_render_as_dash(value) -> None:
    from global_market_regime.alerts import _esc

    assert _esc(value) == "—"


def test_fred_errors_redact_api_credentials() -> None:
    class FailingFred:
        api_key = "super-secret-key"

        def get_observations(self, series_id, observation_start):
            raise RuntimeError(
                "403 Client Error: https://api.stlouisfed.org/fred/series/observations"
                "?series_id=DGS10&api_key=super-secret-key&file_type=json"
            )

    _, errors = fetch_fred_observations(client=FailingFred())
    rendered = json.dumps(errors)

    assert "super-secret-key" not in rendered
    assert "api_key=[REDACTED]" in rendered


def test_gmail_config_does_not_load_unrelated_repo_secrets(
    monkeypatch, tmp_path
) -> None:
    from global_market_regime import alerts

    (tmp_path / ".config").write_text(
        "\n".join(
            [
                "GMAIL_SENDER=sender@example.com",
                "GMAIL_APP_PASSWORD=app-password",
                "GMAIL_RECIPIENT=reader@example.com",
                "OPENROUTER_API_KEY=must-not-be-loaded",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(alerts, "REPO_ROOT", tmp_path)
    for name in (
        "GMAIL_SENDER",
        "GMAIL_APP_PASSWORD",
        "GMAIL_RECIPIENT",
        "GMAIL_RECIPIENTS",
    ):
        monkeypatch.delenv(name, raising=False)

    config = alerts.load_gmail_config()

    assert config["GMAIL_SENDER"] == "sender@example.com"
    assert "OPENROUTER_API_KEY" not in config


def test_duplicate_observation_date_does_not_fake_persistence() -> None:
    history = pd.DataFrame(
        {
            "date": ["2026-09-01", "2026-09-01"],
            "value": [4.90, 4.90],
        }
    )

    states = classify_level_states(history, enter=4.82, exit=4.82)

    assert len(states) == 1
    assert states.iloc[-1]["state"] == "Watch"


def test_long_observation_gap_resets_live_persistence() -> None:
    history = pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-09-01"],
            "value": [4.90, 4.95],
        }
    )

    states = classify_level_states(history, enter=4.82, exit=4.82)

    assert states["state"].tolist() == ["Watch", "Watch"]
    assert states["consecutive_breach"].tolist() == [1, 1]


def test_unknown_alert_state_or_indicator_fails_closed() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "credit_vix",
                "state": "Compromised",
                "freshness": "Current session",
                "observation_date": "2026-09-04",
            },
            {
                "indicator_id": "unregistered_signal",
                "state": "Confirmed",
                "freshness": "Current session",
                "observation_date": "2026-09-04",
            },
        ]
    )

    decision = evaluate_alert(snapshot, state={"last_states": {}})
    updated = advance_alert_state(
        snapshot,
        events=decision["events"],
        state={"last_states": {}},
        sent=False,
    )

    assert decision["events"] == []
    assert decision["should_send"] is False
    assert updated["last_states"] == {}


def test_unknown_state_is_excluded_from_aggregate_state_map() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "brent",
                "state": "Compromised",
                "freshness": "Current session",
            },
            {
                "indicator_id": "unregistered_signal",
                "state": "Confirmed",
                "freshness": "Current session",
            },
        ]
    )

    assert fresh_state_map(snapshot) == {}


def test_stale_indicator_keeps_prior_state_until_source_recovers() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "brent",
                "state": "Unavailable",
                "freshness": "Stale",
                "observation_date": "2026-08-01",
            }
        ]
    )

    updated = advance_alert_state(
        snapshot,
        events=[],
        state={"last_states": {"brent": "Confirmed"}},
        sent=False,
    )

    assert updated["last_states"]["brent"] == "Confirmed"


def test_cli_preview_records_decision_without_gmail(monkeypatch, tmp_path) -> None:
    from global_market_regime import cli
    from global_market_regime.alerts import load_alert_state

    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "us10y",
                "state": "Confirmed",
                "freshness": "Last session",
                "observation_date": "2026-09-02",
            }
        ]
    )
    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda write: {
            "run_id": "test-run",
            "overall_state": "Confirmed",
            "fred_errors": {},
            "mpt_error": None,
            "fred_observations": pd.DataFrame([{"value": 1.0}]),
            "atlanta_mpt": pd.DataFrame([{"value": 1.0}]),
            "latest_conditions": snapshot,
            "condition_states": pd.DataFrame(),
            "freshness_ok": True,
        },
    )
    monkeypatch.setattr(
        cli,
        "send_report",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Gmail must not run")),
    )
    state_path = tmp_path / "alert-state.json"

    result = cli.main(
        [
            "--alert-mode",
            "preview",
            "--alert-state-path",
            str(state_path),
        ]
    )

    state = load_alert_state(state_path)
    assert result == 0
    assert state["last_decision"] == "component_preview"
    assert state["alert_mode"] == "preview"
    assert state["last_sent_at"] is None


def test_cli_rejects_force_report_in_preview_mode_before_fetch(monkeypatch) -> None:
    from global_market_regime import cli

    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid argument combination must fail before fetch")
        ),
    )
    monkeypatch.setattr(
        cli,
        "send_report",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("preview mode must never send")
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli.main(["--alert-mode", "preview", "--force-report"])

    assert exc.value.code == 2


def test_nearest_rate_window_keeps_closest_future_contract() -> None:
    frame = pd.DataFrame(
        {
            "date": ["2026-09-02", "2026-09-02", "2026-09-02"],
            "reference_start": ["2026-09-16", "2026-12-16", "2027-03-17"],
            "target_range": ["350bps - 375bps"] * 3,
            "field": ["Prob: hike"] * 3,
            "value": [88.9, 84.5, 82.1],
        }
    )
    nearest = nearest_rate_window(frame)
    assert nearest["reference_start"].nunique() == 1
    assert pd.Timestamp(nearest["reference_start"].iloc[0]) == pd.Timestamp("2026-09-16")


def test_parse_atlanta_roundtrip(tmp_path) -> None:
    payload = BytesIO()
    with pd.ExcelWriter(payload) as writer:
        pd.DataFrame({"x": []}).to_excel(writer, sheet_name="LICENSE", index=False)
        pd.DataFrame({"a": ["date"]}).to_excel(writer, sheet_name="DICTIONARY", index=False)
        pd.DataFrame(
            {
                "date": ["2026-09-02", "2026-09-02"],
                "reference_start": ["2026-09-16", "2026-09-16"],
                "target_range": ["350bps - 375bps", "350bps - 375bps"],
                "field": ["Prob: hike", "Prob: cut"],
                "value": [88.95, 0.29],
            }
        ).to_excel(writer, sheet_name="DATA", index=False)
    parsed = parse_atlanta_mpt(payload.getvalue())
    hist = hike_probability_history(parsed)
    assert len(hist) == 1
    assert hist.iloc[0]["value"] == 88.95
    assert hist.iloc[0]["cut_prob"] == 0.29
    assert round(hist.iloc[0]["hold_prob"], 2) == 10.76


def test_atlanta_incomplete_distribution_is_not_used_as_probability() -> None:
    parsed = pd.DataFrame(
        {
            "date": ["2026-09-02"],
            "reference_start": ["2026-09-16"],
            "target_range": ["350bps - 375bps"],
            "field": ["Prob: hike"],
            "value": [70.0],
        }
    )

    history = hike_probability_history(parsed)

    assert history.empty


def test_pipeline_partial_fred_success_still_builds_snapshot() -> None:
    dates = pd.date_range("2026-08-03", periods=8, freq="B")
    fred = pd.DataFrame(
        [
            {"date": d, "series_id": "DCOILBRENTEU", "indicator_id": "brent", "value": 95 + i, "unit": "USD/bbl", "source": "fred"}
            for i, d in enumerate(dates)
        ]
        + [
            {"date": d, "series_id": "DGS10", "indicator_id": "us10y", "value": 4.6 + i * 0.05, "unit": "percent", "source": "fred"}
            for i, d in enumerate(dates)
        ]
        + [
            {"date": d, "series_id": "VIXCLS", "indicator_id": "vix", "value": 14 + i, "unit": "index", "source": "fred"}
            for i, d in enumerate(dates)
        ]
        + [
            {"date": d, "series_id": "BAMLH0A0HYM2", "indicator_id": "hy_oas", "value": 3.2 + i * 0.1, "unit": "percent", "source": "fred"}
            for i, d in enumerate(dates)
        ]
    )
    mpt = pd.DataFrame(
        {
            "date": list(dates) * 2,
            "reference_start": [dates[-1] + pd.Timedelta(days=14)] * len(dates) * 2,
            "target_range": ["350bps - 375bps"] * len(dates) * 2,
            "field": ["Prob: hike"] * len(dates) + ["Prob: cut"] * len(dates),
            "value": [40 + i for i in range(len(dates))] + [5] * len(dates),
        }
    )
    results = run_pipeline(
        write=False,
        fred_frame=fred,
        mpt_frame=mpt,
        skip_external=True,
        now=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )
    snapshot = results["latest_conditions"]
    assert set(snapshot["indicator_id"]) >= {"brent", "us10y", "hike_prob", "credit_vix"}
    assert results["overall_state"] in {"Normal", "Watch", "Confirmed", "Escalating", "Improving"}
    assert results["freshness_ok"] is False


def test_pipeline_with_no_fresh_conditions_never_reports_normal() -> None:
    results = run_pipeline(
        write=False,
        fred_frame=pd.DataFrame(),
        mpt_frame=pd.DataFrame(),
        cot_frame=pd.DataFrame(),
        fomc_history_frame=pd.DataFrame(),
        skip_external=True,
        now=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )

    assert results["overall_state"] == "Unavailable"
    assert results["freshness_ok"] is False


def test_cross_asset_source_health_requires_the_expected_universe() -> None:
    health = source_health_rows(
        fred=pd.DataFrame(),
        mpt=pd.DataFrame(),
        fred_errors={},
        mpt_error=None,
        cot=pd.DataFrame(),
        fomc=pd.DataFrame(),
        cross_asset=pd.DataFrame(
            [
                {
                    "date": "2026-09-03",
                    "exposure_id": "sp500",
                    "close": 100.0,
                }
            ]
        ),
        now=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    row = health[health["series_id"].eq("market_monitor_prices")].iloc[0]

    assert row["status"] == "Degraded"
    assert "1/8" in row["notes"]


def test_cftc_source_health_requires_every_registered_contract() -> None:
    health = source_health_rows(
        fred=pd.DataFrame(),
        mpt=pd.DataFrame(),
        fred_errors={},
        mpt_error=None,
        cot=pd.DataFrame(
            [
                {
                    "date": "2026-09-01",
                    "contract_id": "spx",
                    "net": 1,
                }
            ]
        ),
        fomc=pd.DataFrame(),
        cross_asset=pd.DataFrame(),
        now=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    row = health[health["series_id"].eq("cftc_cot")].iloc[0]

    assert row["status"] == "Degraded"
    assert "1/7" in row["notes"]


def test_cftc_source_health_degrades_when_one_contract_is_stale() -> None:
    from global_market_regime.config import (
        CFTC_DISAGG_CONTRACTS,
        CFTC_TFF_CONTRACTS,
    )

    contracts = [
        spec["contract_id"]
        for spec in (*CFTC_TFF_CONTRACTS, *CFTC_DISAGG_CONTRACTS)
    ]
    cot = pd.DataFrame(
        [
            {
                "date": "2026-08-01" if contract_id == "wti" else "2026-09-01",
                "contract_id": contract_id,
                "net": 1,
            }
            for contract_id in contracts
        ]
    )
    health = source_health_rows(
        fred=pd.DataFrame(),
        mpt=pd.DataFrame(),
        fred_errors={},
        mpt_error=None,
        cot=cot,
        fomc=pd.DataFrame(),
        cross_asset=pd.DataFrame(),
        now=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    row = health[health["series_id"].eq("cftc_cot")].iloc[0]

    assert row["status"] == "Degraded"
    assert "Stale: wti" in row["notes"]


def test_incomplete_fomc_distribution_is_not_healthy() -> None:
    health = source_health_rows(
        fred=pd.DataFrame(),
        mpt=pd.DataFrame(),
        fred_errors={},
        mpt_error=None,
        cot=pd.DataFrame(),
        fomc=pd.DataFrame(
            [
                {
                    "date": "2026-09-04",
                    "hike_prob": 30.0,
                    "distribution_complete": False,
                }
            ]
        ),
        cross_asset=pd.DataFrame(),
        now=datetime(2026, 9, 4, tzinfo=timezone.utc),
    )
    row = health[health["series_id"].eq("polymarket_fomc")].iloc[0]

    assert row["status"] == "Degraded"
    assert "incomplete" in row["notes"].lower()


def test_cross_asset_reuse_preserves_upstream_run_lineage(monkeypatch) -> None:
    from market_monitor import storage as market_storage

    monkeypatch.setattr(
        market_storage,
        "load_latest_with_lineage",
        lambda *args, **kwargs: (
            pd.DataFrame(
                [
                    {
                        "date": "2026-09-03",
                        "exposure_id": "sp500",
                        "close": 100.0,
                    }
                ]
            ),
            {"run_id": "market-run-a", "run_scope": "full"},
        ),
    )

    prices = load_cross_asset_prices()

    assert prices.attrs["upstream_market_monitor_run_id"] == "market-run-a"
    assert prices.attrs["upstream_market_monitor_run_scope"] == "full"


def test_freshness_labels() -> None:
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    assert classify_freshness("2026-09-04", now=now) == "Current session"
    assert classify_freshness("2026-09-03", now=now) == "Last session"
    assert classify_freshness("2026-08-30", now=now) == "Recent"
    assert classify_freshness("2026-08-20", now=now) == "Stale"
    assert classify_freshness(None, now=now) == "Unavailable"


def test_overall_state_inputs_exclude_stale_conditions() -> None:
    snapshot = pd.DataFrame(
        [
            {
                "indicator_id": "brent",
                "state": "Escalating",
                "freshness": "Stale",
            },
            {
                "indicator_id": "us10y",
                "state": "Watch",
                "freshness": "Last session",
            },
            {
                "indicator_id": "fomc_hike",
                "state": "Unavailable",
                "freshness": "Current session",
            },
        ]
    )

    assert fresh_state_map(snapshot) == {"us10y": "Watch"}


from global_market_regime.cot import add_history_features, latest_cot_snapshot, normalize_disagg, normalize_tff
from global_market_regime.prediction_markets import (
    classify_fomc_question,
    fetch_token_history,
    fomc_probability_history,
    parse_fomc_snapshot,
    select_next_fomc_event,
)


def test_cot_net_and_percentile_are_computed_from_official_fields() -> None:
    raw = pd.DataFrame(
        [
            {
                "market_and_exchange_names": "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE",
                "report_date_as_yyyy_mm_dd": "2026-08-18",
                "open_interest_all": "2000000",
                "lev_money_positions_long": "160000",
                "lev_money_positions_short": "450000",
                "change_in_lev_money_long": "1000",
                "change_in_lev_money_short": "2000",
            },
            {
                "market_and_exchange_names": "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE",
                "report_date_as_yyyy_mm_dd": "2026-08-25",
                "open_interest_all": "2074931",
                "lev_money_positions_long": "138765",
                "lev_money_positions_short": "467297",
                "change_in_lev_money_long": "-21335",
                "change_in_lev_money_short": "17296",
            },
        ]
    )
    gold = pd.DataFrame(
        [
            {
                "market_and_exchange_names": "GOLD - COMMODITY EXCHANGE INC.",
                "report_date_as_yyyy_mm_dd": "2026-08-25",
                "open_interest_all": "427957",
                "m_money_positions_long_all": "159819",
                "m_money_positions_short_all": "15072",
                "change_in_m_money_long_all": "5224",
                "change_in_m_money_short_all": "2125",
            }
        ]
    )
    history = add_history_features(pd.concat([normalize_tff(raw), normalize_disagg(gold)], ignore_index=True))
    latest = latest_cot_snapshot(history)
    spx = latest[latest["contract_id"].eq("spx")].iloc[0]
    gold_row = latest[latest["contract_id"].eq("gold")].iloc[0]
    assert int(spx["net"]) == 138765 - 467297
    assert int(spx["weekly_change"]) == -21335 - 17296
    assert int(gold_row["net"]) == 159819 - 15072
    assert gold_row["report"] == "disagg_managed_money"
    assert spx["report"] == "tff_leveraged_money"


def test_polymarket_selects_next_open_fed_decision() -> None:
    events = [
        {"id": "old", "slug": "fed-decision-in-january", "title": "Fed decision in January?", "closed": True, "endDate": "2026-01-28T00:00:00Z", "markets": []},
        {"id": "oct", "slug": "fed-decision-in-october-20260617190323537", "title": "Fed Decision in October?", "closed": False, "endDate": "2026-10-28T23:59:00Z", "markets": []},
        {"id": "sep", "slug": "fed-decision-in-september-762", "title": "Fed Decision in September?", "closed": False, "endDate": "2026-09-16T00:00:00Z", "markets": []},
    ]
    chosen = select_next_fomc_event(events, now=datetime(2026, 9, 4, tzinfo=timezone.utc))
    assert chosen["id"] == "sep"


def test_polymarket_parses_yes_prices_into_hike_hold_cut() -> None:
    event = {
        "id": "481717",
        "slug": "fed-decision-in-september-762",
        "title": "Fed Decision in September?",
        "endDate": "2026-09-16T00:00:00Z",
        "markets": [
            {"question": "Will there be no change in Fed interest rates after the September 2026 meeting?", "outcomes": '["Yes", "No"]', "outcomePrices": '["0.595", "0.405"]', "clobTokenIds": '["holdtok", "x"]'},
            {"question": "Will the Fed increase interest rates by 25 bps after the September 2026 meeting?", "outcomes": '["Yes", "No"]', "outcomePrices": '["0.405", "0.595"]', "clobTokenIds": '["hike25tok", "x"]'},
            {"question": "Will the Fed increase interest rates by 50+ bps after the September 2026 meeting?", "outcomes": '["Yes", "No"]', "outcomePrices": '["0.0065", "0.9935"]', "clobTokenIds": '["hike50tok", "x"]'},
            {"question": "Will the Fed decrease interest rates by 25 bps after the September 2026 meeting?", "outcomes": '["Yes", "No"]', "outcomePrices": '["0.0065", "0.9935"]', "clobTokenIds": '["cut25tok", "x"]'},
            {"question": "Will the Fed decrease interest rates by 50+ bps after the September 2026 meeting?", "outcomes": '["Yes", "No"]', "outcomePrices": '["0.0000", "1.0000"]', "clobTokenIds": '["cut50tok", "x"]'},
        ],
    }
    snap = parse_fomc_snapshot(event, retrieved_at="2026-09-04T00:00:00Z")
    assert classify_fomc_question(event["markets"][0]["question"]) == "hold"
    assert round(snap["hold_prob"], 1) == 59.5
    assert round(snap["hike_prob"], 2) == 41.15
    assert round(snap["cut_prob"], 2) == 0.65
    assert snap["token_hold"] == "holdtok"
    assert snap["token_hike_50"] == "hike50tok"
    assert snap["token_cut_25"] == "cut25tok"
    assert snap["distribution_complete"] is True
    assert "Prediction-market" in snap["caveat"]


def test_polymarket_token_history_uses_yes_outcome_position() -> None:
    event = {
        "id": "event",
        "slug": "fed-decision-test",
        "title": "Fed Decision test",
        "endDate": "2026-09-16T00:00:00Z",
        "markets": [
            {
                "question": "Will the Fed increase interest rates by 25 bps?",
                "outcomes": '["No", "Yes"]',
                "outcomePrices": '["0.7", "0.3"]',
                "clobTokenIds": '["no-token", "yes-token"]',
            }
        ],
    }

    snapshot = parse_fomc_snapshot(event)

    assert snapshot["hike_25"] == 30.0
    assert snapshot["hike_prob"] is None
    assert snapshot["distribution_complete"] is False
    assert snapshot["token_hike_25"] == "yes-token"


def test_polymarket_parser_skips_malformed_market_json() -> None:
    event = {
        "id": "event",
        "slug": "fed-decision-test",
        "title": "Fed Decision test",
        "endDate": "2026-09-16T00:00:00Z",
        "markets": [
            {
                "question": "Will the Fed increase interest rates by 25 bps?",
                "outcomes": "not-json",
                "outcomePrices": "not-json",
                "clobTokenIds": "not-json",
            },
            {
                "question": "Will there be no change in Fed interest rates?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.6", "0.4"]',
                "clobTokenIds": '["yes-token", "no-token"]',
            },
        ],
    }

    snapshot = parse_fomc_snapshot(event)

    assert snapshot["hold_prob"] == 60.0
    assert snapshot["hike_prob"] is None
    assert snapshot["distribution_complete"] is False


def test_polymarket_history_drops_invalid_timestamps_and_prices(
    monkeypatch,
) -> None:
    from global_market_regime import prediction_markets

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "history": [
                    {"t": "bad", "p": "0.4"},
                    {"t": 1788470400, "p": "2.0"},
                    {"t": 1788470400, "p": "0.45"},
                    {"t": 1788474000, "p": "0.50"},
                ]
            }

    monkeypatch.setattr(
        prediction_markets.requests,
        "get",
        lambda *args, **kwargs: Response(),
    )

    history = fetch_token_history("token")

    assert history.to_dict("records") == [
        {"date": "2026-09-03", "value": 50.0}
    ]


def test_polymarket_history_uses_each_bucket_history_not_current_snapshot_constants() -> None:
    snapshot = {
        "event_id": "event",
        "meeting_date": "2026-09-16",
        "slug": "fed-decision-in-september-762",
        "hike_50": 9.0,
        "cut_prob": 12.0,
    }
    dates = ["2026-09-01", "2026-09-02"]
    hold = pd.DataFrame({"date": dates, "value": [55.0, 50.0]})
    hike_25 = pd.DataFrame({"date": dates, "value": [30.0, 32.0]})
    hike_50 = pd.DataFrame({"date": dates, "value": [5.0, 7.0]})
    cut_25 = pd.DataFrame({"date": dates, "value": [8.0, 9.0]})
    cut_50 = pd.DataFrame({"date": dates, "value": [2.0, 2.0]})

    history = fomc_probability_history(
        snapshot,
        hold,
        hike_25,
        hike50_history=hike_50,
        cut25_history=cut_25,
        cut50_history=cut_50,
    )

    assert history["hike_prob"].tolist() == [35.0, 39.0]
    assert history["cut_prob"].tolist() == [10.0, 11.0]


def test_polymarket_history_rejects_incomplete_bucket_history() -> None:
    history = fomc_probability_history(
        {"event_id": "event", "meeting_date": "2026-09-16", "slug": "fed"},
        pd.DataFrame({"date": ["2026-09-01"], "value": [60.0]}),
        pd.DataFrame({"date": ["2026-09-01"], "value": [30.0]}),
        hike50_history=pd.DataFrame({"date": ["2026-09-01"], "value": [1.0]}),
        cut25_history=pd.DataFrame({"date": ["2026-09-01"], "value": [9.0]}),
        cut50_history=pd.DataFrame(),
    )

    assert history.empty



def test_cot_fetch_query_filters_to_recent_history() -> None:
    from global_market_regime.cot import fetch_cftc_table
    import inspect
    source = inspect.getsource(fetch_cftc_table)
    assert "2015-01-01" in source
    assert "report_date_as_yyyy_mm_dd >=" in source
