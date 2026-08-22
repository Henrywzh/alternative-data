"""Regression tests for auditable Control Tower T2 valuation foundations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from scripts.research_control_tower_valuation import (
    _combine_valuations,
    build_explicit_valuation_inputs,
    compute_tencent_valuation_snapshots,
    main,
)
from src.research_control_tower.valuation import (
    INTERNAL_ESTIMATES_ARROW_SCHEMA,
    INTERNAL_ESTIMATES_COLUMNS,
    VALUATION_SNAPSHOTS_ARROW_SCHEMA,
    VALUATION_SNAPSHOTS_COLUMNS,
    ValuationInput,
    build_valuation_snapshot_row,
    canonicalize_metric_basis,
    empty_frame,
    frame_from_rows,
    load_internal_estimates_csv,
    validate_internal_estimates_df,
    validate_valuation_snapshots_df,
)


AS_OF = pd.Timestamp("2026-08-21T12:00:00Z")
QUOTE_URL = "https://finance.yahoo.com/quote/0700.HK"
CONSENSUS_URL = "https://finance.yahoo.com/quote/0700.HK/analysis"
FX_URL = "https://data-api.ecb.europa.eu/service/data/fixture"


def _quote(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "quote_id": "quote-0700-20260821",
        "listing_id": "0700_HK",
        "canonical_ticker": "0700.HK",
        "provider_symbol": "0700.HK",
        "quote_timestamp": pd.Timestamp("2026-08-21T08:00:00Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-21T08:05:00Z"),
        "last_price": 375.0,
        "bid": 374.8,
        "ask": 375.2,
        "day_change_pct": 1.0,
        "volume": 1_000_000.0,
        "currency": "HKD",
        "market_status": "closed",
        "latency_class": "delayed",
        "source_id": "quote:yfinance",
        "source_url": QUOTE_URL,
        "pit_class": "snapshot_from_delayed_source",
        "source_license_class": "provider_public",
        "registry_version": "v1",
    }
    row.update(overrides)
    return row


def _consensus(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "snapshot_id": "consensus-0700-eps-2026",
        "provider": "yfinance",
        "entity_id": "TENCENT",
        "listing_id": "0700_HK",
        "financial_data_security_id": "sec-0700",
        "canonical_ticker": "0700.HK",
        "metric": "eps",
        "fiscal_period": "annual",
        "fiscal_year": 2026,
        "estimate_period_end": pd.Timestamp("2026-12-31").date(),
        "horizon": "0y",
        "snapshot_at": pd.Timestamp("2026-08-20T10:00:00Z"),
        "value": 28.0,
        "statistic": "mean",
        "low_value": 27.0,
        "high_value": 29.0,
        "analyst_count": 25,
        "provider_contributor_count": 25,
        "currency": "CNY",
        "unit": "currency_per_share",
        "accounting_basis": "NON_IFRS_MANAGEMENT",
        "provider_asof": pd.Timestamp("2026-08-20T09:00:00Z"),
        "retrieved_at_utc": pd.Timestamp("2026-08-20T10:05:00Z"),
        "source_url": CONSENSUS_URL,
        "raw_hash": "hash",
        "pit_class": "snapshot_from_delayed_source",
        "source_run_id": "run-1",
        "calculation_origin": "provider_published_consensus",
        "coverage_reason": "",
    }
    row.update(overrides)
    return row


def _fx_rows() -> pd.DataFrame:
    common = {
        "dataset_id": "airline_fx_rates",
        "frequency": "daily",
        "observation_date": "2026-08-20",
        "base_currency": "USD",
        "unit": "quote currency per USD",
        "source_release_date": None,
        "retrieved_at": "2026-08-21T07:00:00Z",
        "source_name": "ECB",
        "source_url": FX_URL,
        "source_reference_currency": "EUR",
    }
    return pd.DataFrame(
        [
            {**common, "pair": "USD_CNY", "quote_currency": "CNY", "value": 7.0},
            {**common, "pair": "USD_HKD", "quote_currency": "HKD", "value": 7.8},
        ]
    )


def _consensus_health(**overrides: object) -> pd.DataFrame:
    row: dict[str, object] = {
        "provider": "yfinance",
        "status": "available",
        "reason": "provider-policy-filtered fixture",
        "row_count": 8,
        "mapped_row_count": 8,
        "latest_snapshot_at": pd.Timestamp("2026-08-20T10:00:00Z"),
        "as_of": pd.Timestamp("2026-08-21T08:00:00Z"),
        "network_calls": 3,
        "source_license_class": "local_private_research",
        "entitlement_status": "terms_unverified",
        "entitlement_evidence": "Personal research use.",
        "entitlement_ref": "task3-provider-policy:sidecar-required-v1",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _valuation_input(**overrides: object) -> ValuationInput:
    values: dict[str, object] = {
        "listing_id": "0700_HK",
        "valuation_at": AS_OF.to_pydatetime(),
        "metric_name": "forward_pe",
        "accounting_basis": "NON_IFRS_MANAGEMENT",
        "metric_basis": "NON_IFRS_MANAGEMENT",
        "numerator_value": 375.0,
        "numerator_currency": "HKD",
        "numerator_ref": "quote-1",
        "numerator_source_id": "quote:yfinance",
        "numerator_source_url": QUOTE_URL,
        "numerator_pit_class": "snapshot_from_delayed_source",
        "numerator_at_utc": pd.Timestamp(
            "2026-08-21T08:00:00Z"
        ).to_pydatetime(),
        "numerator_retrieved_at_utc": pd.Timestamp(
            "2026-08-21T08:05:00Z"
        ).to_pydatetime(),
        "denominator_value": 30.0,
        "denominator_currency": "HKD",
        "denominator_ref": "consensus-1",
        "denominator_source_id": "consensus:yfinance",
        "denominator_source_url": CONSENSUS_URL,
        "denominator_pit_class": "snapshot_from_delayed_source",
        "denominator_at_utc": pd.Timestamp(
            "2026-08-20T10:00:00Z"
        ).to_pydatetime(),
        "denominator_provider_asof_utc": pd.Timestamp(
            "2026-08-20T09:00:00Z"
        ).to_pydatetime(),
        "denominator_retrieved_at_utc": pd.Timestamp(
            "2026-08-20T10:05:00Z"
        ).to_pydatetime(),
        "source_url": CONSENSUS_URL,
        "retrieved_at_utc": AS_OF.to_pydatetime(),
    }
    values.update(overrides)
    return ValuationInput(**values)


def test_real_quote_and_consensus_contract_produce_forward_pe() -> None:
    result = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([_consensus()]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )

    assert list(result.columns) == VALUATION_SNAPSHOTS_COLUMNS
    assert len(result) == 1
    row = result.iloc[0]
    assert row["numerator_ref"] == "quote-0700-20260821"
    assert row["numerator_value"] == 375.0
    assert row["denominator_ref"] == "consensus-0700-eps-2026"
    assert row["accounting_basis"] == "NON_IFRS_MANAGEMENT"
    assert row["metric_basis"] == "NON_IFRS_MANAGEMENT"
    assert row["fx_base_currency"] == "CNY"
    assert row["fx_quote_currency"] == "HKD"
    assert row["fx_rate_applied"] == pytest.approx(7.8 / 7.0)
    assert row["ratio_value"] == pytest.approx(375.0 / (28.0 * 7.8 / 7.0))
    assert row["percentile_history_status"] == "unavailable"
    assert not validate_valuation_snapshots_df(result)


@pytest.mark.parametrize("eps", [-4.0, 0.0])
def test_loss_making_consensus_is_typed_empty_and_never_aborts_the_build(
    eps: float,
) -> None:
    """A loss-making forecast has no forward P/E; it must skip, not crash.

    ``build_valuation_snapshot_row`` rejects a non-positive denominator by
    raising, which would take the whole automated build down over one metric
    that simply has no meaningful value this period.  It never gets the chance:
    ``_latest_consensus_eps`` admits only finite positive values upstream.
    This pins that screen, which is load-bearing and easy to drop by accident
    while editing the consensus filter.
    """

    result = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([_consensus(value=eps)]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )

    assert result.empty
    assert list(result.columns) == VALUATION_SNAPSHOTS_COLUMNS


def test_the_valuation_natural_key_is_recoverable_from_mart_columns() -> None:
    """``valuation_id`` is a content hash, so dedupe groups on the columns.

    Re-deriving the same fact from a fresh capture mints a new ID by design
    (that is what makes the canonical rebuild a tamper check), so nothing may
    depend on the ID as a natural key.  Every component of the natural key is
    a column of the mart, which is what keeps an upsert possible.
    """

    natural_key = (
        "listing_id",
        "valuation_at",
        "metric_name",
        "metric_basis",
        "numerator_ref",
        "denominator_ref",
    )
    assert set(natural_key) <= set(VALUATION_SNAPSHOTS_COLUMNS)

    first = build_valuation_snapshot_row(_valuation_input())
    restated = build_valuation_snapshot_row(
        _valuation_input(
            retrieved_at_utc=pd.Timestamp("2026-08-21T23:00:00Z").to_pydatetime()
        )
    )
    assert first["valuation_id"] != restated["valuation_id"]
    assert all(first[field] == restated[field] for field in natural_key)


def test_provider_unverified_consensus_is_typed_empty_and_never_valued() -> None:
    result = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame(
            [_consensus(accounting_basis="provider_reported_non_gaap_unverified")]
        ),
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )

    assert result.empty
    assert list(result.columns) == VALUATION_SNAPSHOTS_COLUMNS

    with pytest.raises(ValueError, match="valuation metric basis"):
        build_valuation_snapshot_row(
            _valuation_input(
                accounting_basis="provider_reported_non_gaap_unverified",
                metric_basis="PROVIDER_UNVERIFIED",
            )
        )

    valid_row = build_valuation_snapshot_row(_valuation_input())
    tampered = frame_from_rows([valid_row], VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    tampered.loc[0, "accounting_basis"] = "provider_reported_non_gaap_unverified"
    tampered.loc[0, "metric_basis"] = "PROVIDER_UNVERIFIED"
    assert any(
        "valuation metric basis" in issue
        for issue in validate_valuation_snapshots_df(tampered)
    )


def test_direct_valuation_collapses_exact_duplicate_consensus_but_rejects_divergence() -> None:
    consensus = _consensus()
    exact = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([consensus, dict(consensus)]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert len(exact) == 1
    assert exact.iloc[0]["denominator_ref"] == consensus["snapshot_id"]

    divergent = dict(consensus)
    divergent["value"] = 31.0
    rejected = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([consensus, divergent]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert rejected.empty
    assert list(rejected.columns) == VALUATION_SNAPSHOTS_COLUMNS

    irrelevant = _consensus(
        snapshot_id="irrelevant-2027",
        fiscal_year=2027,
        value=40.0,
    )
    irrelevant_divergent = dict(irrelevant)
    irrelevant_divergent["value"] = 41.0
    unaffected = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([consensus, irrelevant, irrelevant_divergent]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert len(unaffected) == 1
    assert unaffected.iloc[0]["denominator_ref"] == consensus["snapshot_id"]


def test_selection_uses_fiscal_mapping_and_statistic_not_horizon() -> None:
    consensus = pd.DataFrame(
        [
            _consensus(
                snapshot_id="wrong-stat",
                statistic="median",
                value=99.0,
            ),
            _consensus(
                snapshot_id="wrong-year",
                fiscal_year=2027,
                horizon="+1y",
                value=50.0,
            ),
            _consensus(
                snapshot_id="selected",
                horizon="provider-specific-label",
                value=28.0,
            ),
        ]
    )
    result = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        consensus,
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_period="annual",
        fiscal_year=2026,
        statistic="mean",
    )
    assert result.iloc[0]["denominator_ref"] == "selected"


def test_future_quote_consensus_and_fx_vintages_are_excluded() -> None:
    quotes = pd.DataFrame(
        [
            _quote(quote_id="causal", last_price=375.0),
            _quote(
                quote_id="future",
                quote_timestamp=pd.Timestamp("2026-08-22T08:00:00Z"),
                retrieved_at_utc=pd.Timestamp("2026-08-22T08:05:00Z"),
                last_price=999.0,
            ),
        ]
    )
    consensus = pd.DataFrame(
        [
            _consensus(snapshot_id="causal", value=28.0),
            _consensus(
                snapshot_id="future",
                snapshot_at=pd.Timestamp("2026-08-22T10:00:00Z"),
                provider_asof=pd.Timestamp("2026-08-22T09:00:00Z"),
                retrieved_at_utc=pd.Timestamp("2026-08-22T10:05:00Z"),
                value=99.0,
            ),
        ]
    )
    result = compute_tencent_valuation_snapshots(
        quotes,
        consensus,
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert result.iloc[0]["numerator_ref"] == "causal"
    assert result.iloc[0]["denominator_ref"] == "causal"
    assert result.iloc[0]["numerator_at_utc"] <= AS_OF
    assert result.iloc[0]["denominator_at_utc"] <= AS_OF
    assert result.iloc[0]["denominator_provider_asof_utc"] <= AS_OF
    assert result.iloc[0]["fx_snapshot_at_utc"] <= AS_OF

    future_fx = _fx_rows()
    future_fx["retrieved_at"] = "2026-08-22T07:00:00Z"
    unavailable = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([_consensus()]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=future_fx,
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert unavailable.empty


def test_missing_fx_returns_typed_empty_instead_of_fabrication() -> None:
    result = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([_consensus()]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=None,
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert result.empty
    assert list(result.columns) == VALUATION_SNAPSHOTS_COLUMNS


def test_naive_source_timestamps_are_not_assumed_to_be_utc() -> None:
    result = compute_tencent_valuation_snapshots(
        pd.DataFrame(
            [
                _quote(
                    quote_timestamp="2026-08-21 08:00:00",
                    retrieved_at_utc="2026-08-21 08:05:00",
                )
            ]
        ),
        pd.DataFrame([_consensus()]),
        consensus_health_df=_consensus_health(),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert result.empty


def test_consensus_health_is_required_and_rejects_stale_or_degraded_provider() -> None:
    with pytest.raises(ValueError, match="consensus health"):
        compute_tencent_valuation_snapshots(
            pd.DataFrame([_quote()]),
            pd.DataFrame([_consensus()]),
            fx_rates_df=_fx_rows(),
            as_of_utc=AS_OF,
            fiscal_year=2026,
        )

    for health in (
        _consensus_health(status="degraded"),
        _consensus_health(
            latest_snapshot_at=pd.Timestamp("2026-07-01T10:00:00Z")
        ),
    ):
        result = compute_tencent_valuation_snapshots(
            pd.DataFrame([_quote()]),
            pd.DataFrame([_consensus()]),
            consensus_health_df=health,
            fx_rates_df=_fx_rows(),
            as_of_utc=AS_OF,
            fiscal_year=2026,
        )
        assert result.empty


@pytest.mark.parametrize(
    ("health_overrides", "accepted"),
    [
        ({"source_license_class": "local_private_research"}, True),
        (
            {
                "source_license_class": "research_use_only",
                "entitlement_status": "permitted_local_private",
            },
            True,
        ),
        ({"source_license_class": "private_research"}, True),
        ({"source_license_class": "provider_public"}, False),
        ({"entitlement_status": "active"}, False),
        ({"entitlement_evidence": ""}, False),
        ({"entitlement_ref": ""}, False),
    ],
)
def test_consensus_health_entitlement_matches_build_policy(
    health_overrides: dict[str, object], accepted: bool
) -> None:
    result = compute_tencent_valuation_snapshots(
        pd.DataFrame([_quote()]),
        pd.DataFrame([_consensus()]),
        consensus_health_df=_consensus_health(**health_overrides),
        fx_rates_df=_fx_rows(),
        as_of_utc=AS_OF,
        fiscal_year=2026,
    )
    assert (not result.empty) is accepted


@pytest.mark.parametrize(
    "missing_column",
    ["source_license_class", "entitlement_evidence"],
)
def test_consensus_health_requires_build_entitlement_columns(
    missing_column: str,
) -> None:
    health = _consensus_health().drop(columns=[missing_column])
    with pytest.raises(ValueError, match=missing_column):
        compute_tencent_valuation_snapshots(
            pd.DataFrame([_quote()]),
            pd.DataFrame([_consensus()]),
            consensus_health_df=health,
            fx_rates_df=_fx_rows(),
            as_of_utc=AS_OF,
            fiscal_year=2026,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("numerator_value", 0.0, "numerator_value must be positive"),
        ("numerator_value", float("inf"), "numerator_value must be finite"),
        ("denominator_value", 0.0, "denominator_value must be positive"),
        ("denominator_value", -1.0, "denominator_value must be positive"),
        ("denominator_value", float("nan"), "denominator_value must be finite"),
    ],
)
def test_nonpositive_or_nonfinite_inputs_are_unavailable(
    field: str, value: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_valuation_snapshot_row(_valuation_input(**{field: value}))


def test_all_supported_metrics_have_positive_audited_calculations() -> None:
    expected = {
        "forward_pe": 375.0 / 30.0,
        "ev_ebitda": 375.0 / 30.0,
        "fcf_yield": 30.0 / 375.0 * 100.0,
        "shareholder_cash_return_yield": 30.0 / 375.0 * 100.0,
    }
    for metric_name, ratio in expected.items():
        row = build_valuation_snapshot_row(
            _valuation_input(metric_name=metric_name)
        )
        assert row["ratio_value"] == pytest.approx(ratio)
        arrow_round_trip = frame_from_rows(
            [row], VALUATION_SNAPSHOTS_ARROW_SCHEMA
        )
        assert not validate_valuation_snapshots_df(arrow_round_trip)


def test_explicit_local_inputs_support_non_pe_metrics() -> None:
    explicit = pd.DataFrame(
        [
            vars(
                _valuation_input(
                    metric_name="ev_ebitda",
                    numerator_value=3_500.0,
                    denominator_value=350.0,
                )
            )
        ]
    )
    result = build_explicit_valuation_inputs(explicit)
    assert result.iloc[0]["metric_name"] == "ev_ebitda"
    assert result.iloc[0]["ratio_value"] == pytest.approx(10.0)


def test_fx_direction_and_causality_are_enforced() -> None:
    with pytest.raises(ValueError, match="denominator-to-numerator"):
        build_valuation_snapshot_row(
            _valuation_input(
                denominator_currency="CNY",
                fx_rate_applied=7.8 / 7.0,
                fx_base_currency="HKD",
                fx_quote_currency="CNY",
                fx_source="ECB",
                fx_source_url=FX_URL,
                fx_snapshot_at_utc=pd.Timestamp(
                    "2026-08-20T00:00:00Z"
                ).to_pydatetime(),
                fx_retrieved_at_utc=pd.Timestamp(
                    "2026-08-21T07:00:00Z"
                ).to_pydatetime(),
            )
        )
    with pytest.raises(ValueError, match="FX vintage"):
        build_valuation_snapshot_row(
            _valuation_input(
                denominator_currency="CNY",
                fx_rate_applied=7.8 / 7.0,
                fx_base_currency="CNY",
                fx_quote_currency="HKD",
                fx_source="ECB",
                fx_source_url=FX_URL,
                fx_snapshot_at_utc=pd.Timestamp(
                    "2026-08-22T00:00:00Z"
                ).to_pydatetime(),
                fx_retrieved_at_utc=pd.Timestamp(
                    "2026-08-22T07:00:00Z"
                ).to_pydatetime(),
            )
        )


def test_fx_observation_must_not_postdate_fx_retrieval() -> None:
    with pytest.raises(ValueError, match="FX observation"):
        build_valuation_snapshot_row(
            _valuation_input(
                denominator_currency="CNY",
                fx_rate_applied=7.8 / 7.0,
                fx_base_currency="CNY",
                fx_quote_currency="HKD",
                fx_source="ECB",
                fx_source_url=FX_URL,
                fx_snapshot_at_utc=pd.Timestamp(
                    "2026-08-21T08:00:00Z"
                ).to_pydatetime(),
                fx_retrieved_at_utc=pd.Timestamp(
                    "2026-08-21T07:00:00Z"
                ).to_pydatetime(),
            )
        )


def test_source_observation_must_not_postdate_source_retrieval() -> None:
    with pytest.raises(ValueError, match="numerator observation"):
        build_valuation_snapshot_row(
            _valuation_input(
                numerator_at_utc=pd.Timestamp(
                    "2026-08-21T09:00:00Z"
                ).to_pydatetime(),
                numerator_retrieved_at_utc=pd.Timestamp(
                    "2026-08-21T08:00:00Z"
                ).to_pydatetime(),
            )
        )
    with pytest.raises(ValueError, match="denominator observation/provider-as-of"):
        build_valuation_snapshot_row(
            _valuation_input(
                denominator_provider_asof_utc=pd.Timestamp(
                    "2026-08-20T11:00:00Z"
                ).to_pydatetime(),
                denominator_retrieved_at_utc=pd.Timestamp(
                    "2026-08-20T10:00:00Z"
                ).to_pydatetime(),
            )
        )


def test_basis_canonicalization_never_promotes_unverified_provider_label() -> None:
    assert (
        canonicalize_metric_basis("provider_reported_non_gaap_unverified")
        == "PROVIDER_UNVERIFIED"
    )
    assert canonicalize_metric_basis(None) == "PROVIDER_UNVERIFIED"
    assert canonicalize_metric_basis("NON_IFRS_MANAGEMENT") == (
        "NON_IFRS_MANAGEMENT"
    )
    assert canonicalize_metric_basis("IFRS as reported") == "GAAP_REPORTED"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("valuation_date", pd.Timestamp("2026-08-20").date()),
        ("numerator_source_url", "https://tampered.example/quote"),
        ("numerator_currency", "USD"),
        ("numerator_at_utc", pd.Timestamp("2026-08-21T07:00:00Z")),
        ("denominator_ref", "tampered-consensus-id"),
        ("source_url", "https://tampered.example/calculation"),
    ],
)
def test_validator_rejects_tampered_canonical_fields(
    field: str, value: object
) -> None:
    row = build_valuation_snapshot_row(_valuation_input())
    frame = frame_from_rows([row], VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    frame.loc[0, field] = value
    issues = validate_valuation_snapshots_df(frame)
    assert issues


def test_combining_duplicate_valuation_ids_fails_closed() -> None:
    row = build_valuation_snapshot_row(_valuation_input())
    first = frame_from_rows([row], VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    divergent = first.copy()
    divergent.loc[0, "ratio_value"] = float(first.loc[0, "ratio_value"]) + 1.0
    with pytest.raises(ValueError, match="duplicate valuation_id"):
        _combine_valuations(first, divergent)
    with pytest.raises(ValueError, match="duplicate valuation_id"):
        _combine_valuations(first, first.copy())


def _internal_rows() -> pd.DataFrame:
    rows = [
        {
            "estimate_id": "EST-1",
            "version": 1,
            "supersedes_estimate_id": None,
            "entity_id": "TENCENT",
            "listing_id": "0700_HK",
            "observation_type": "internal_estimate",
            "author": "research_analyst",
            "metric": "operating_profit",
            "accounting_basis": "NON_IFRS_MANAGEMENT",
            "metric_basis": "NON_IFRS_MANAGEMENT",
            "fiscal_period": "FY2026",
            "fiscal_year": 2026,
            "value_low": 260.0,
            "value_high": 280.0,
            "value_mid": 270.0,
            "currency": "CNY",
            "unit": "CNY_billion",
            "effective_asof": pd.Timestamp("2026-08-20").date(),
            "recorded_at_utc": pd.Timestamp("2026-08-20T15:00:00Z"),
            "rationale_notes": "Internal model.",
            "source_ref": "model-v1",
            "source_url": None,
            "pit_class": "not_pit",
            "reviewed_at_utc": None,
            "reviewed_by": None,
        },
        {
            "estimate_id": "EST-2",
            "version": 2,
            "supersedes_estimate_id": "EST-1",
            "entity_id": "TENCENT",
            "listing_id": "0700_HK",
            "observation_type": "internal_estimate",
            "author": "research_analyst",
            "metric": "operating_profit",
            "accounting_basis": "NON_IFRS_MANAGEMENT",
            "metric_basis": "NON_IFRS_MANAGEMENT",
            "fiscal_period": "FY2026",
            "fiscal_year": 2026,
            "value_low": 265.0,
            "value_high": 285.0,
            "value_mid": 275.0,
            "currency": "CNY",
            "unit": "CNY_billion",
            "effective_asof": pd.Timestamp("2026-08-21").date(),
            "recorded_at_utc": pd.Timestamp("2026-08-21T15:00:00Z"),
            "rationale_notes": "Internal model revision.",
            "source_ref": "model-v2",
            "source_url": None,
            "pit_class": "not_pit",
            "reviewed_at_utc": pd.Timestamp("2026-08-21T16:00:00Z"),
            "reviewed_by": "lead_pm",
        },
    ]
    return pd.DataFrame(rows, columns=INTERNAL_ESTIMATES_COLUMNS)


def test_internal_estimates_exact_schema_version_order_and_review_contract() -> None:
    valid = _internal_rows()
    assert not validate_internal_estimates_df(valid)

    invalid = valid.copy()
    invalid.loc[1, "value_low"] = 290.0
    invalid.loc[1, "reviewed_by"] = None
    invalid.loc[1, "pit_class"] = "snapshot_from_live_source"
    issues = validate_internal_estimates_df(invalid)
    assert any("value_low must be <= value_mid" in issue for issue in issues)
    assert any("both be set or both be null" in issue for issue in issues)
    assert any("internal_estimate pit_class must be not_pit" in issue for issue in issues)

    wrong_schema = valid.drop(columns=["source_ref"])
    assert validate_internal_estimates_df(wrong_schema) == [
        "internal_estimates has invalid exact schema"
    ]


def test_internal_estimate_loader_rejects_schema_drift(tmp_path: Path) -> None:
    path = tmp_path / "internal_estimates.csv"
    path.write_text("estimate_id,unexpected\nEST-1,x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid exact schema"):
        load_internal_estimates_csv(path)


def test_internal_estimate_loader_does_not_assume_timezone(
    tmp_path: Path,
) -> None:
    path = tmp_path / "internal_estimates.csv"
    row = _internal_rows().iloc[0].copy()
    row["recorded_at_utc"] = "2026-08-20 15:00:00"
    pd.DataFrame([row], columns=INTERNAL_ESTIMATES_COLUMNS).to_csv(
        path, index=False
    )
    loaded = load_internal_estimates_csv(path)
    issues = validate_internal_estimates_df(loaded)
    assert any("effective_asof/recorded_at_utc is invalid" in issue for issue in issues)


def test_cli_atomically_writes_populated_outputs_with_exact_arrow_schema(
    tmp_path: Path,
) -> None:
    quotes_path = tmp_path / "quotes.parquet"
    consensus_path = tmp_path / "consensus.parquet"
    consensus_health_path = tmp_path / "consensus-health.parquet"
    fx_path = tmp_path / "fx.parquet"
    estimates_path = tmp_path / "internal_estimates.csv"
    output_dir = tmp_path / "out"
    pd.DataFrame([_quote()]).to_parquet(quotes_path, index=False)
    pd.DataFrame([_consensus()]).to_parquet(consensus_path, index=False)
    _consensus_health().to_parquet(consensus_health_path, index=False)
    _fx_rows().to_parquet(fx_path, index=False)
    estimates_path.write_text(
        ",".join(INTERNAL_ESTIMATES_COLUMNS) + "\n", encoding="utf-8"
    )

    assert (
        main(
            [
                "--quotes",
                str(quotes_path),
                "--consensus",
                str(consensus_path),
                "--consensus-health",
                str(consensus_health_path),
                "--fx-rates",
                str(fx_path),
                "--internal-estimates",
                str(estimates_path),
                "--output-dir",
                str(output_dir),
                "--as-of",
                AS_OF.isoformat(),
                "--fiscal-year",
                "2026",
            ]
        )
        == 0
    )
    valuation_path = output_dir / "valuation_snapshots.parquet"
    internal_path = output_dir / "internal_estimates.parquet"
    assert valuation_path.exists()
    assert internal_path.exists()
    assert pq.read_schema(valuation_path).equals(VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    assert pq.read_schema(internal_path).equals(INTERNAL_ESTIMATES_ARROW_SCHEMA)
    assert len(pd.read_parquet(valuation_path)) == 1
    assert pd.read_parquet(internal_path).empty
    assert not list(output_dir.glob(".*.tmp"))


def test_cli_writes_typed_empty_outputs_when_sources_are_unavailable(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "empty-out"
    missing_estimates = tmp_path / "missing.csv"
    assert (
        main(
            [
                "--internal-estimates",
                str(missing_estimates),
                "--output-dir",
                str(output_dir),
                "--as-of",
                AS_OF.isoformat(),
            ]
        )
        == 0
    )
    valuation_path = output_dir / "valuation_snapshots.parquet"
    internal_path = output_dir / "internal_estimates.parquet"
    assert pq.read_schema(valuation_path).equals(VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    assert pq.read_schema(internal_path).equals(INTERNAL_ESTIMATES_ARROW_SCHEMA)
    assert pd.read_parquet(valuation_path).empty
    assert pd.read_parquet(internal_path).empty


def test_arrow_empty_frames_keep_exact_columns() -> None:
    valuations = empty_frame(VALUATION_SNAPSHOTS_ARROW_SCHEMA)
    estimates = empty_frame(INTERNAL_ESTIMATES_ARROW_SCHEMA)
    assert list(valuations.columns) == VALUATION_SNAPSHOTS_COLUMNS
    assert list(estimates.columns) == INTERNAL_ESTIMATES_COLUMNS
