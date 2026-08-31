from __future__ import annotations

import json

import pandas as pd


def _state(
    *,
    close_cursor: str | None = "2026-01-01",
    intraday_cursor: str | None = None,
    sent_date: str | None = "2026-01-01",
    sent_week: str | None = "2026-W01",
) -> dict:
    return {
        "version": 1,
        "baseline_initialized": True,
        "last_evaluated_by_mode": {"close": close_cursor, "intraday": intraday_cursor},
        "last_sent_report_date": sent_date,
        "last_sent_week": sent_week,
        "last_sent_kind": "event",
        "pending_events": [],
    }


def _core_inputs():
    wrappers = pd.DataFrame(
        [
            {
                "ticker": "510500",
                "fund_name": "南方中证500ETF",
                "exposure_id": "csi500",
                "premium_regime": "domestic",
                "premium_pct": -0.30,
                "quote_status": "Fresh",
            },
            {
                "ticker": "159922",
                "fund_name": "嘉实中证500ETF",
                "exposure_id": "csi500",
                "premium_regime": "domestic",
                "premium_pct": 0.00,
                "quote_status": "Fresh",
            },
        ]
    )
    premium_history = pd.DataFrame(
        [
            {"date": "2026-01-01", "ticker": "510500", "premium_pct": 0.00},
            {"date": "2026-01-02", "ticker": "510500", "premium_pct": -0.20},
            {"date": "2026-01-03", "ticker": "510500", "premium_pct": -0.30},
            {"date": "2026-01-01", "ticker": "159922", "premium_pct": 0.00},
            {"date": "2026-01-02", "ticker": "159922", "premium_pct": 0.00},
            {"date": "2026-01-03", "ticker": "159922", "premium_pct": 0.00},
        ]
    )
    return wrappers, premium_history


def test_first_run_sends_baseline_and_state_contains_only_delivery_metadata(tmp_path):
    from market_monitor.alert_policy import (
        advance_alert_state,
        evaluate_alert,
        save_alert_state,
    )

    decision = evaluate_alert(
        report_date="2026-01-05",
        mode="close",
        state=None,
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame([{"date": "2026-01-05", "exposure_id": "csi300", "close": 100.0}]),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.should_send is True
    assert decision.kind == "baseline"

    path = tmp_path / "alert_state.json"
    save_alert_state(
        advance_alert_state(
            {},
            mode="close",
            observation_date="2026-01-05",
            report_date="2026-01-05",
            kind=decision.kind,
            sent=True,
        ),
        path,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["last_evaluated_by_mode"]["close"] == "2026-01-05"
    assert payload["last_sent_report_date"] == "2026-01-05"
    assert "premium_history" not in path.read_text(encoding="utf-8")
    assert "close" not in payload


def test_status_and_same_index_leader_need_two_confirming_observations():
    from market_monitor.alert_policy import evaluate_alert

    wrappers, premium_history = _core_inputs()
    decision = evaluate_alert(
        report_date="2026-01-04",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=wrappers,
        premium_history=premium_history,
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.should_send is True
    assert decision.kind == "event"
    assert {event.event_type for event in decision.events} == {"entry_status", "leader_change"}
    assert all(event.observation_date == "2026-01-03" for event in decision.events)
    assert all(event.entity_id.startswith("csi500:") for event in decision.events)


def test_one_day_premium_crossing_is_not_an_alert():
    from market_monitor.alert_policy import evaluate_alert

    wrappers, premium_history = _core_inputs()
    premium_history.loc[
        (premium_history["ticker"] == "510500") & (premium_history["date"] == "2026-01-03"),
        "premium_pct",
    ] = 0.00
    wrappers.loc[wrappers["ticker"] == "510500", "premium_pct"] = 0.00
    decision = evaluate_alert(
        report_date="2026-01-03",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=wrappers,
        premium_history=premium_history,
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.should_send is False
    assert decision.kind == "none"


def test_same_day_event_is_deduplicated():
    from market_monitor.alert_policy import evaluate_alert

    wrappers, premium_history = _core_inputs()
    decision = evaluate_alert(
        report_date="2026-01-04",
        mode="close",
        state=_state(sent_date="2026-01-04"),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=wrappers,
        premium_history=premium_history,
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.should_send is False
    assert decision.kind == "deduped"


def test_quiet_friday_sends_weekly_heartbeat():
    from market_monitor.alert_policy import evaluate_alert

    decision = evaluate_alert(
        report_date="2026-01-09",
        mode="close",
        state=_state(sent_date="2026-01-02", sent_week="2026-W01"),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.should_send is True
    assert decision.kind == "weekly"
    assert "每周兜底" in decision.reason_lines[0]


def test_published_fee_change_is_an_immediate_event():
    from market_monitor.alert_policy import evaluate_alert

    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness={
            "fetch_errors": [
                {
                    "dataset": "fund_fee",
                    "ticker": "510500",
                    "severity": "event",
                    "error": "FeeChange: 510500 management_fee cut",
                }
            ]
        },
    )
    assert decision.should_send is True
    assert decision.kind == "event"
    assert decision.events[0].event_type == "fee_change"
    assert "费率变化" in decision.events[0].detail


def test_pending_event_is_replayed_after_a_failed_send():
    from market_monitor.alert_policy import AlertEvent, evaluate_alert, state_with_pending_events

    event = AlertEvent(
        event_type="fee_change",
        entity_id="510500",
        label="510500",
        observation_date="2026-01-06",
        detail="费率变化：管理费下调。",
        priority=0,
    )
    pending_state = state_with_pending_events(_state(), [event])
    decision = evaluate_alert(
        report_date="2026-01-07",
        mode="close",
        state=pending_state,
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.should_send is True
    assert decision.kind == "event"
    assert decision.events[0].event_type == "fee_change"


def test_same_day_dedupe_queues_new_events_for_the_next_run():
    from market_monitor.alert_policy import (
        advance_alert_state,
        evaluate_alert,
        state_with_pending_events,
    )

    wrappers, premium_history = _core_inputs()
    decision = evaluate_alert(
        report_date="2026-01-04",
        mode="close",
        state=_state(sent_date="2026-01-04"),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=wrappers,
        premium_history=premium_history,
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.kind == "deduped"
    assert decision.events

    # This is the exact state transition used by the CLI for a same-day retry.
    updated = advance_alert_state(
        _state(sent_date="2026-01-04"),
        mode="close",
        observation_date=decision.observation_date,
        report_date="2026-01-04",
        kind=decision.kind,
        sent=False,
    )
    updated = state_with_pending_events(updated, decision.events)
    replay = evaluate_alert(
        report_date="2026-01-05",
        mode="close",
        state=updated,
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=wrappers,
        premium_history=premium_history,
        relative_pair_history=pd.DataFrame(),
    )
    assert replay.should_send is True
    assert replay.kind == "event"
    assert {event.event_key for event in replay.events} >= {
        event.event_key for event in decision.events
    }


def test_sent_event_keys_prevent_replaying_an_operational_event():
    from market_monitor.alert_policy import advance_alert_state, evaluate_alert

    freshness = {
        "fetch_errors": [
            {
                "dataset": "fund_fee",
                "ticker": "510500",
                "severity": "event",
                "error": "FeeChange: 510500 management_fee cut",
            }
        ]
    }
    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=_state(sent_date="2026-01-05"),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness=freshness,
    )
    assert decision.events
    updated = advance_alert_state(
        _state(sent_date="2026-01-05"),
        mode="close",
        observation_date=None,
        report_date="2026-01-06",
        kind=decision.kind,
        sent=True,
        sent_events=decision.events,
    )
    assert decision.events[0].event_key in updated["sent_event_keys"]
    repeat = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=updated,
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness=freshness,
    )
    assert repeat.should_send is False
    assert repeat.kind == "none"


def test_unverified_iopv_history_cannot_trigger_a_premium_alert():
    from market_monitor.alert_policy import evaluate_alert

    wrappers = pd.DataFrame(
        [
            {
                "ticker": "510500",
                "fund_name": "南方中证500ETF",
                "exposure_id": "csi500",
                "premium_regime": "domestic",
                "premium_pct": -0.30,
                "quote_status": "Unverified",
            }
        ]
    )
    history = pd.DataFrame(
        [
            {"date": "2026-01-01", "ticker": "510500", "exposure_id": "csi500", "premium_pct": 0.0, "basis": "nav"},
            {"date": "2026-01-02", "ticker": "510500", "exposure_id": "csi500", "premium_pct": -0.3, "basis": "iopv_unverified"},
            {"date": "2026-01-03", "ticker": "510500", "exposure_id": "csi500", "premium_pct": -0.3, "basis": "iopv_unverified"},
        ]
    )
    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=wrappers,
        premium_history=history,
        relative_pair_history=pd.DataFrame(),
    )
    assert decision.should_send is False
    assert decision.kind == "none"


def test_neutral_or_missing_technical_observations_break_confirmation():
    from market_monitor.alert_policy import _confirmed_transitions, _technical_state

    assert _technical_state(0.0) == "neutral"
    states = pd.Series(
        ["above", "below", "neutral", "below"],
        index=["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
    )
    transitions = _confirmed_transitions(
        states,
        None,
        after_date="2025-12-31",
        transition_filter=lambda old, new: new == "below",
    )
    assert transitions == []


def test_leader_alert_waits_for_a_gap_and_detects_later_widening():
    from market_monitor.alert_policy import evaluate_alert

    wrappers = pd.DataFrame(
        [
            {
                "ticker": "510500",
                "fund_name": "南方中证500ETF",
                "exposure_id": "csi500",
                "premium_regime": "domestic",
                "premium_pct": 0.0,
                "quote_status": "Fresh",
            },
            {
                "ticker": "159922",
                "fund_name": "嘉实中证500ETF",
                "exposure_id": "csi500",
                "premium_regime": "domestic",
                "premium_pct": 0.2,
                "quote_status": "Fresh",
            },
        ]
    )
    history = pd.DataFrame(
        [
            {"date": "2026-01-01", "ticker": "510500", "exposure_id": "csi500", "premium_pct": 0.00},
            {"date": "2026-01-01", "ticker": "159922", "exposure_id": "csi500", "premium_pct": 0.05},
            {"date": "2026-01-02", "ticker": "510500", "exposure_id": "csi500", "premium_pct": 0.00},
            {"date": "2026-01-02", "ticker": "159922", "exposure_id": "csi500", "premium_pct": 0.05},
            {"date": "2026-01-03", "ticker": "510500", "exposure_id": "csi500", "premium_pct": 0.00},
            {"date": "2026-01-03", "ticker": "159922", "exposure_id": "csi500", "premium_pct": 0.20},
            {"date": "2026-01-04", "ticker": "510500", "exposure_id": "csi500", "premium_pct": 0.00},
            {"date": "2026-01-04", "ticker": "159922", "exposure_id": "csi500", "premium_pct": 0.20},
        ]
    )
    decision = evaluate_alert(
        report_date="2026-01-05",
        mode="close",
        state=_state(close_cursor="2026-01-01", sent_date="2025-12-31", sent_week="2025-W52"),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=wrappers,
        premium_history=history,
        relative_pair_history=pd.DataFrame(),
    )
    leader_events = [event for event in decision.events if event.event_type == "leader_change"]
    assert len(leader_events) == 1
    assert leader_events[0].observation_date == "2026-01-04"
    assert "领先 +0.20" in leader_events[0].detail


def test_failed_weekly_heartbeat_is_retried_on_the_next_run():
    from market_monitor.alert_policy import evaluate_alert, state_with_pending_events

    state = _state(sent_date="2026-01-02", sent_week="2026-W01")
    first = evaluate_alert(
        report_date="2026-01-09",
        mode="close",
        state=state,
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
    )
    assert first.kind == "weekly"
    assert first.events[0].event_type == "weekly_heartbeat"
    pending = state_with_pending_events(state, first.events)
    retry = evaluate_alert(
        report_date="2026-01-12",
        mode="close",
        state=pending,
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
    )
    assert retry.should_send is True
    assert retry.kind == "weekly"
    assert "重试" in retry.reason_lines[0]


def test_policy_blocks_direct_evaluation_when_freshness_fails():
    from market_monitor.alert_policy import evaluate_alert

    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame([{"date": "2026-01-06", "exposure_id": "csi500", "close": 100.0}]),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness={"daily_close": {"status": "Stale"}, "fetch_errors": []},
    )
    assert decision.should_send is False
    assert decision.observation_date is None
    assert "freshness gate" in decision.reason_lines[0]


def test_intraday_policy_allows_stale_borrowed_close_but_requires_live_quote():
    from market_monitor.alert_policy import evaluate_alert

    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="intraday",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame(),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness={
            "quote": {"status": "Fresh"},
            "daily_close": {"status": "Stale"},
            "fetch_errors": [],
        },
    )
    assert decision.kind == "none"
    assert "freshness gate" not in decision.reason_lines[0]


def test_raw_snapshot_without_source_timestamp_is_marked_unverified():
    from market_monitor.pipeline import _premium_rows

    unverified = _premium_rows(
        pd.DataFrame([{"ticker": "510500", "premium_pct": 0.1, "source_observed_at_utc": pd.NaT}]),
        "2026-01-06",
        basis=None,
    )
    verified = _premium_rows(
        pd.DataFrame([{"ticker": "510500", "premium_pct": 0.1, "source_observed_at_utc": "2026-01-06T04:00:00Z"}]),
        "2026-01-06",
        basis=None,
    )
    assert unverified[0]["basis"] == "iopv_unverified"
    assert verified[0]["basis"] == "iopv"


def test_cli_persists_pending_events_when_gmail_fails_and_clears_after_retry(monkeypatch, tmp_path):
    from market_monitor import cli
    from market_monitor.alert_policy import advance_alert_state, load_alert_state, save_alert_state

    wrappers, premium_history = _core_inputs()
    results = {
        "mode": "close",
        "exposure_technicals": pd.DataFrame(),
        "relative_regime": pd.DataFrame(),
        "relative_pair_history": pd.DataFrame(),
        "index_price_daily": pd.DataFrame(),
        "wrapper_metrics": wrappers,
        "premium_history": premium_history,
        "freshness": {
            "quote": {"status": "Fresh"},
            "daily_close": {"status": "Last session"},
            "fetch_errors": [],
        },
    }
    state_path = tmp_path / "alert_state.json"
    save_alert_state(
        advance_alert_state(
            _state(),
            mode="close",
            observation_date="2026-01-01",
            report_date="2026-01-01",
            kind="baseline",
            sent=True,
        ),
        state_path,
    )
    monkeypatch.setattr(cli, "run_pipeline", lambda **kwargs: results)
    monkeypatch.setattr(cli, "market_date", lambda: "2026-01-04")

    def _fail_send(**kwargs):
        raise RuntimeError("simulated Gmail timeout")

    monkeypatch.setattr(cli, "send_report", _fail_send)
    assert cli.main(["--mode", "close", "--send-report", "--alert-state-path", str(state_path)]) == 0
    failed_state = load_alert_state(state_path)
    assert failed_state["pending_events"]

    sent = []
    monkeypatch.setattr(cli, "send_report", lambda **kwargs: sent.append(kwargs))
    assert cli.main(["--mode", "close", "--send-report", "--alert-state-path", str(state_path)]) == 0
    retried_state = load_alert_state(state_path)
    assert sent
    assert retried_state["pending_events"] == []


def test_a_registry_fee_disagreement_does_not_black_out_every_alert():
    """The registry's fee is unused; disagreeing with it must not stop email.

    ``build_wrapper_metrics`` takes the issuer's published schedule over the
    registry, so this finding changes no number anyone sees. Blocking on it
    silenced the whole alert channel until a human edited a hand-typed table.
    """
    from market_monitor.alert_policy import evaluate_alert
    from market_monitor.pipeline import fee_mismatch_event

    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame([{"date": "2026-01-06", "exposure_id": "csi500", "close": 100.0}]),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness={
            "quote": {"status": "Fresh"},
            "daily_close": {"status": "Fresh"},
            "fetch_errors": [
                fee_mismatch_event({"fund_id": "510300", "stated": "0.5000%", "published": "0.1500%"})
            ],
        },
    )

    assert "freshness gate" not in decision.reason_lines[0]
    assert decision.should_send is True
    assert [event.event_type for event in decision.events] == ["fee_registry_mismatch"]
    # A registry disagreement is not a rate cut and must not read as one.
    assert "费率变化：" not in decision.events[0].detail
    assert "登记费率与发行方不一致" in decision.events[0].detail


def test_a_wrong_exposure_registry_name_still_blocks_the_alert():
    """The name check guards which index a ticker is ranked under."""
    from market_monitor.alert_policy import evaluate_alert

    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame([{"date": "2026-01-06", "exposure_id": "csi500", "close": 100.0}]),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness={
            "quote": {"status": "Fresh"},
            "daily_close": {"status": "Fresh"},
            "fetch_errors": [
                {
                    "dataset": "etf_spot",
                    "exposure_id": "csi300",
                    "ticker": "510300",
                    "error": "RegistryMismatch: registry says 510300 is 沪深300ETF, exchange says 中证500ETF",
                }
            ],
        },
    )

    assert decision.should_send is False
    assert "freshness gate" in decision.reason_lines[0]
    assert decision.observation_date is None


def test_a_real_rate_cut_is_still_labelled_as_a_fee_change():
    """The declared-type fallback must not regress the existing emitter."""
    from market_monitor.alert_policy import evaluate_alert

    decision = evaluate_alert(
        report_date="2026-01-06",
        mode="close",
        state=_state(),
        technicals=pd.DataFrame(),
        index_prices=pd.DataFrame([{"date": "2026-01-06", "exposure_id": "csi500", "close": 100.0}]),
        wrappers=pd.DataFrame(),
        premium_history=pd.DataFrame(),
        relative_pair_history=pd.DataFrame(),
        freshness={
            "quote": {"status": "Fresh"},
            "daily_close": {"status": "Fresh"},
            "fetch_errors": [
                {
                    "dataset": "fund_fee",
                    "ticker": "510300",
                    "severity": "event",
                    "error": "FeeChange: 510300 management_fee cut: 0.5000% -> 0.1500%",
                }
            ],
        },
    )

    assert decision.should_send is True
    assert decision.events[0].event_type == "fee_change"
    assert "费率变化：" in decision.events[0].detail


def test_a_standing_registry_disagreement_does_not_mail_every_single_day():
    """The live registry has held this disagreement for weeks at a time.

    Dating the key would mint a fresh event every morning and turn a stale
    hand-typed row into a daily email that nobody can silence except by
    editing the registry -- the same pressure the blocking behaviour applied,
    just delivered to the inbox instead of to CI.
    """
    from market_monitor.alert_policy import advance_alert_state, evaluate_alert
    from market_monitor.pipeline import fee_mismatch_event

    freshness = {
        "quote": {"status": "Fresh"},
        "daily_close": {"status": "Fresh"},
        "fetch_errors": [
            fee_mismatch_event({"fund_id": "513080", "stated": "0.8000%", "published": "0.5000%"})
        ],
    }
    prices = pd.DataFrame([{"date": "2026-01-06", "exposure_id": "csi500", "close": 100.0}])
    state = _state()
    sent_days = []
    for report_date in ("2026-01-06", "2026-01-07", "2026-01-08"):
        decision = evaluate_alert(
            report_date=report_date,
            mode="close",
            state=state,
            technicals=pd.DataFrame(),
            index_prices=prices,
            wrappers=pd.DataFrame(),
            premium_history=pd.DataFrame(),
            relative_pair_history=pd.DataFrame(),
            freshness=freshness,
        )
        if decision.should_send:
            sent_days.append(report_date)
        state = advance_alert_state(
            state,
            mode="close",
            observation_date=decision.observation_date,
            report_date=report_date,
            kind=decision.kind,
            sent=decision.should_send,
            sent_events=decision.events,
        )

    assert sent_days == ["2026-01-06"]


def test_a_queued_condition_keeps_its_identity_through_a_failed_send():
    """A retry must not be keyed differently from the send that failed."""
    from market_monitor.alert_policy import AlertEvent, _event

    original = _event(
        "fee_registry_mismatch",
        "513080",
        "513080",
        "2026-01-06",
        "登记费率与发行方不一致：FeeMismatch: registry states 513080。",
        recurring_condition=True,
    )
    restored = AlertEvent.from_mapping(original.as_dict())

    assert restored is not None
    assert restored.event_key == original.event_key
