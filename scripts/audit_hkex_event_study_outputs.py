"""Independently audit persisted HKEX event-study evidence artifacts.

This post-write audit is deliberately separate from the event-study generator.
It checks that CSV/JSON artifacts still reconcile after serialization and that
no persisted row can silently register as a trading signal.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import pandas as pd


VALID_NATIVE_STATUS = {"missing", "covered", "benchmark_missing", "bar_hole"}
VALID_RESOLVED_DIRECTION = {"unknown", "positive", "negative", "mixed", "review_required"}
VALID_CANDIDATE_FAMILIES = {
    "business_update", "capital_action", "director_change", "dividend",
    "governance", "inside_information", "results", "trading_update",
}
MIN_SAMPLE_CLUSTERS = 30


def _as_bool(value: object) -> bool:
    """Parse CSV booleans without treating the string ``False`` as truthy."""
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes"}


def _cutoff_key(value: object) -> str | None:
    if value is None or str(value).strip() in {"", "None", "NaT"}:
        return None
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(timestamp) else timestamp.isoformat()


def audit_comparison(comparison_path: Path) -> dict[str, object]:
    """Audit pair-level cutoff classification and aggregate robustness status."""
    if not comparison_path.exists():
        return {"status": "failed", "errors": [f"missing:{comparison_path}"]}
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    pairs = comparison.get("pairs") or []
    replays = comparison.get("replays") or []
    successful_replays = [replay for replay in replays if replay.get("status") == "ok"]
    expected_pair_count = len(successful_replays) * (len(successful_replays) - 1) // 2
    if int(comparison.get("pair_count", -1)) != expected_pair_count:
        errors.append("pair_count_does_not_match_successful_replays")
    replay_by_id = {replay.get("capture_id"): replay for replay in successful_replays}
    observed_pair_ids: set[tuple[object, object]] = set()
    statuses = {"same", "partial_interval_difference", "distinct_both_intervals"}
    for pair in pairs:
        left_id = pair.get("left_capture_id")
        right_id = pair.get("right_capture_id")
        pair_key = tuple(sorted((left_id, right_id)))
        if left_id == right_id or pair_key in observed_pair_ids:
            errors.append(f"duplicate_or_self_pair:{left_id}:{right_id}")
        observed_pair_ids.add(pair_key)
        status = pair.get("market_cutoff_status")
        five_distinct = _cutoff_key(pair.get("left_market_cutoff_5m")) != _cutoff_key(
            pair.get("right_market_cutoff_5m")
        )
        one_distinct = _cutoff_key(pair.get("left_market_cutoff_1h")) != _cutoff_key(
            pair.get("right_market_cutoff_1h")
        )
        expected = (
            "distinct_both_intervals"
            if five_distinct and one_distinct
            else "partial_interval_difference"
            if five_distinct or one_distinct
            else "same"
        )
        if status not in statuses or status != expected:
            errors.append(f"invalid_cutoff_status:{pair.get('left_capture_id')}:{pair.get('right_capture_id')}")
        for side, capture_id in (("left", left_id), ("right", right_id)):
            replay = replay_by_id.get(capture_id)
            if replay is None:
                errors.append(f"pair_capture_missing_from_replays:{capture_id}")
                continue
            for interval in ("5m", "1h"):
                if _cutoff_key(pair.get(f"{side}_market_cutoff_{interval}")) != _cutoff_key(
                    replay.get(f"market_cutoff_{interval}")
                ):
                    errors.append(f"pair_cutoff_provenance_mismatch:{capture_id}:{interval}")
        if status == "same" and pair.get("exact_replay_consistent") is not True:
            errors.append(f"same_cutoff_pair_not_exact:{left_id}:{right_id}")
    distinct_count = sum(pair.get("market_cutoff_status") == "distinct_both_intervals" for pair in pairs)
    partial_count = sum(pair.get("market_cutoff_status") == "partial_interval_difference" for pair in pairs)
    expected_pair_ids = {
        tuple(sorted((left.get("capture_id"), right.get("capture_id"))))
        for left, right in itertools.combinations(successful_replays, 2)
    }
    if observed_pair_ids != expected_pair_ids:
        errors.append("pair_set_does_not_match_successful_replay_combinations")
    if int(comparison.get("pair_count", -1)) != len(pairs):
        errors.append("pair_count_does_not_reconcile")
    if int(comparison.get("distinct_market_cutoff_pair_count", -1)) != distinct_count:
        errors.append("distinct_pair_count_does_not_reconcile")
    if int(comparison.get("partial_market_cutoff_pair_count", -1)) != partial_count:
        errors.append("partial_pair_count_does_not_reconcile")
    expected_status = (
        "distinct_cutoff_comparison_available"
        if distinct_count > 0
        else "insufficient_distinct_market_cutoffs"
    )
    if comparison.get("robustness_status") != expected_status:
        errors.append("robustness_status_does_not_reconcile")
    if comparison.get("production_database_modified") is not False:
        errors.append("comparison_reports_production_database_modified")
    return {
        "status": "failed" if errors else "ok",
        "errors": errors,
        "pair_count": len(pairs),
        "distinct_market_cutoff_pair_count": distinct_count,
        "partial_market_cutoff_pair_count": partial_count,
        "robustness_status": comparison.get("robustness_status"),
    }


def audit_output(output_dir: Path, comparison_path: Path | None = None) -> dict[str, object]:
    errors: list[str] = []
    coverage_path = output_dir / "coverage.json"
    returns_path = output_dir / "event_returns.csv"
    robustness_path = output_dir / "event_robustness_summary.csv"
    registry_path = output_dir / "signal_registry.csv"
    conflicts_path = output_dir / "event_direction_conflicts.csv"
    required = [coverage_path, returns_path, robustness_path, registry_path, conflicts_path]
    missing = [str(path.name) for path in required if not path.exists()]
    if missing:
        return {
            "version": "hkex_event_study_output_audit.v1",
            "output_dir": str(output_dir),
            "status": "failed",
            "errors": [f"missing_artifacts:{','.join(missing)}"],
            "production_database_modified": False,
        }

    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    result = pd.read_csv(returns_path)
    robustness = pd.read_csv(robustness_path)
    registry = pd.read_csv(registry_path)
    conflicts = pd.read_csv(conflicts_path)
    checks: dict[str, object] = {}

    checks["event_rows_reconcile"] = int(coverage.get("event_rows", -1)) == len(result)
    if not checks["event_rows_reconcile"]:
        errors.append("coverage.event_rows does not reconcile to event_returns.csv")
    checks["event_id_unique"] = not result["event_id"].duplicated().any()
    if not checks["event_id_unique"]:
        errors.append("event_returns.event_id is not unique")
    checks["cluster_representative_counts_reconcile"] = (
        int(coverage.get("deduped_event_rows", -1)) == int(result["is_cluster_representative"].sum())
        and int(coverage.get("event_type_cluster_rows", -1))
        == int(result["is_type_cluster_representative"].sum())
    )
    if not checks["cluster_representative_counts_reconcile"]:
        errors.append("cluster representative counts do not reconcile")
    availability_counts = {
        str(key): int(value)
        for key, value in result["availability_basis"].value_counts(dropna=False).to_dict().items()
    }
    expected_availability_counts = {
        str(key): int(value)
        for key, value in (coverage.get("availability_basis_counts") or {}).items()
    }
    checks["availability_basis_counts_reconcile"] = availability_counts == expected_availability_counts
    if not checks["availability_basis_counts_reconcile"]:
        errors.append("availability basis counts do not reconcile")

    cluster_rows = result.loc[result["cluster_key"].notna()].drop_duplicates("cluster_key")
    expected_cluster_documents = (
        result.loc[result["cluster_key"].notna()]
        .groupby("cluster_key")["document_key"]
        .nunique()
    )
    expected_cluster_labels = (
        result.loc[result["cluster_key"].notna()]
        .groupby("cluster_key")["primary_event_type"]
        .agg(lambda values: ",".join(sorted({str(value) for value in values if pd.notna(value)})))
    )
    observed_cluster_documents = (
        result.loc[result["cluster_key"].notna()]
        .drop_duplicates("cluster_key")
        .set_index("cluster_key")["cluster_document_count"]
    )
    observed_cluster_labels = (
        result.loc[result["cluster_key"].notna()]
        .drop_duplicates("cluster_key")
        .set_index("cluster_key")["cluster_co_occurring_types"]
    )
    checks["cluster_document_counts_reconcile"] = bool(
        expected_cluster_documents.sort_index().equals(observed_cluster_documents.sort_index())
        and result.loc[result["cluster_key"].isna(), "cluster_document_count"].eq(0).all()
    )
    checks["cluster_flags_reconcile"] = bool(
        expected_cluster_labels.sort_index().astype("string").equals(
            observed_cluster_labels.sort_index().astype("string")
        )
        and result.loc[result["cluster_key"].isna(), "cluster_co_occurring_types"].isna().all()
        and
        result["is_multi_document_cluster"].eq(result["cluster_document_count"].gt(1)).all()
        and result["is_pure_event_type"].eq(
            result["cluster_key"].notna()
            & ~result["cluster_co_occurring_types"].fillna("").str.contains(",", regex=False)
            & result["cluster_co_occurring_types"].notna()
        ).all()
        and int(coverage.get("multi_document_cluster_count", -1))
        == int(cluster_rows["is_multi_document_cluster"].sum())
        and int(coverage.get("pure_event_cluster_count", -1))
        == int(cluster_rows["is_pure_event_type"].sum())
    )
    if not checks["cluster_document_counts_reconcile"] or not checks["cluster_flags_reconcile"]:
        errors.append("cluster co-occurrence metadata does not reconcile")

    total_identity_checks: list[bool] = []
    signed_identity_checks: list[bool] = []
    for horizon in ("5m", "30m", "1h"):
        drift = pd.to_numeric(result[f"{horizon}_return"], errors="coerce")
        gap = pd.to_numeric(result["opening_gap_return"], errors="coerce")
        gap_component = gap.where(result["session"].ne("INTRADAY"), 0.0)
        total = pd.to_numeric(result[f"total_{horizon}_return"], errors="coerce")
        expected_total = (1.0 + gap_component) * (1.0 + drift) - 1.0
        mask = total.notna() & expected_total.notna()
        total_identity_checks.append(bool((total.loc[mask] - expected_total.loc[mask]).abs().le(1e-9).all()))
        benchmark_drift = pd.to_numeric(result[f"{horizon}_benchmark_drift_return"], errors="coerce")
        benchmark_gap = pd.to_numeric(result["opening_gap_benchmark_return"], errors="coerce")
        benchmark_gap_component = benchmark_gap.where(result["session"].ne("INTRADAY"), 0.0)
        expected_benchmark_total = (1.0 + benchmark_gap_component) * (1.0 + benchmark_drift) - 1.0
        expected_total_abnormal = total - expected_benchmark_total
        total_abnormal = pd.to_numeric(result[f"total_{horizon}_abnormal_return"], errors="coerce")
        mask_abnormal = total_abnormal.notna() & expected_total_abnormal.notna()
        total_identity_checks.append(
            bool(
                (total_abnormal.loc[mask_abnormal] - expected_total_abnormal.loc[mask_abnormal])
                .abs()
                .le(1e-9)
                .all()
            )
        )
        direction = result["resolved_impact_direction"].fillna("unknown")
        abnormal = pd.to_numeric(result[f"{horizon}_abnormal_return"], errors="coerce")
        expected_signed = abnormal.where(direction.eq("positive"), -abnormal.where(direction.eq("negative")))
        signed = pd.to_numeric(result[f"signed_{horizon}_abnormal_return"], errors="coerce")
        signed_identity_checks.append(bool(signed.fillna(0).eq(expected_signed.fillna(0)).all()))
        total_abnormal_series = pd.to_numeric(result[f"total_{horizon}_abnormal_return"], errors="coerce")
        expected_signed_total = total_abnormal_series.where(
            direction.eq("positive"), -total_abnormal_series.where(direction.eq("negative"))
        )
        signed_total = pd.to_numeric(result[f"signed_total_{horizon}_abnormal_return"], errors="coerce")
        signed_identity_checks.append(bool(signed_total.fillna(0).eq(expected_signed_total.fillna(0)).all()))
    checks["total_return_decomposition"] = all(total_identity_checks)
    checks["signed_direction_identity"] = all(signed_identity_checks)
    if not checks["total_return_decomposition"]:
        errors.append("total return decomposition does not reconcile")
    if not checks["signed_direction_identity"]:
        errors.append("signed directional return identity does not reconcile")

    checks["robustness_direction_grain"] = not robustness.duplicated(
        ["primary_event_type", "resolved_impact_direction", "horizon"]
    ).any()
    if not checks["robustness_direction_grain"]:
        errors.append("robustness summary direction grain is not unique")

    native_comparable = result.loc[
        result["native_1h_abnormal_return"].notna() & result["1h_abnormal_return"].notna()
    ]
    if native_comparable.empty:
        expected_native_agreement = None
        expected_native_difference = None
    else:
        expected_native_agreement = float(
            (
                (native_comparable["native_1h_abnormal_return"] == 0)
                & (native_comparable["1h_abnormal_return"] == 0)
                | (
                    native_comparable["native_1h_abnormal_return"]
                    * native_comparable["1h_abnormal_return"]
                    > 0
                )
            ).mean()
        )
        expected_native_difference = float(
            (
                native_comparable["native_1h_abnormal_return"]
                - native_comparable["1h_abnormal_return"]
            ).abs().mean()
        )
    checks["native_global_metrics_reconcile"] = (
        int(coverage.get("native_1h_comparable_rows", -1)) == len(native_comparable)
        and (
            coverage.get("native_1h_global_directional_agreement_rate") is None
            if expected_native_agreement is None
            else abs(
                float(coverage.get("native_1h_global_directional_agreement_rate", float("nan")))
                - expected_native_agreement
            )
            <= 1e-12
        )
        and (
            coverage.get("native_1h_mean_absolute_difference") is None
            if expected_native_difference is None
            else abs(
                float(coverage.get("native_1h_mean_absolute_difference", float("nan")))
                - expected_native_difference
            )
            <= 1e-12
        )
    )
    if not checks["native_global_metrics_reconcile"]:
        errors.append("native 1h global metrics do not reconcile")

    checks["resolved_direction_contract"] = "resolved_impact_direction" in result.columns
    if not checks["resolved_direction_contract"]:
        errors.append("event_returns is missing resolved_impact_direction")
    else:
        resolved = result["resolved_impact_direction"].fillna("unknown")
        checks["resolved_direction_enum"] = bool(resolved.isin(VALID_RESOLVED_DIRECTION).all())
        if not checks["resolved_direction_enum"]:
            errors.append("resolved_impact_direction contains an unsupported value")
        actual_resolved_counts = {
            str(key): int(value) for key, value in resolved.value_counts(dropna=False).to_dict().items()
        }
        expected_resolved_counts = {
            str(key): int(value)
            for key, value in (coverage.get("resolved_impact_direction_counts") or {}).items()
        }
        checks["resolved_direction_counts_reconcile"] = actual_resolved_counts == expected_resolved_counts
        checks["resolved_direction_review_rows_reconcile"] = int(
            coverage.get("resolved_impact_direction_review_rows", -1)
        ) == int(resolved.eq("review_required").sum())
        if not checks["resolved_direction_counts_reconcile"]:
            errors.append("resolved direction counts do not reconcile")
        if not checks["resolved_direction_review_rows_reconcile"]:
            errors.append("resolved direction review rows do not reconcile")

    covered = result["market_data_status"].eq("covered")
    entry = pd.to_datetime(result.loc[covered, "entry_bar_at"], errors="coerce", utc=True)
    available = pd.to_datetime(result.loc[covered, "available_at"], errors="coerce", utc=True)
    checks["pit_entry_strict"] = bool((entry > available).all())
    if not checks["pit_entry_strict"]:
        errors.append("covered entry_bar_at is not strictly later than available_at")

    checks["horizon_coverage_monotonic"] = bool(
        not (result["1h_return"].notna() & result["30m_return"].isna()).any()
        and not (result["30m_return"].notna() & result["5m_return"].isna()).any()
    )
    if not checks["horizon_coverage_monotonic"]:
        errors.append("horizon return coverage is not monotonic")

    checks["native_status_enum"] = bool(result["native_1h_status"].isin(VALID_NATIVE_STATUS).all())
    if not checks["native_status_enum"]:
        errors.append("native_1h_status contains an unsupported value")
    native_covered = result["native_1h_status"].eq("covered")
    native_entry = pd.to_datetime(
        result.loc[native_covered, "native_1h_entry_bar_at"], errors="coerce", utc=True
    )
    native_available = pd.to_datetime(
        result.loc[native_covered, "available_at"], errors="coerce", utc=True
    )
    checks["native_pit_entry_strict"] = bool((native_entry > native_available).all())
    if not checks["native_pit_entry_strict"]:
        errors.append("covered native 1h entry is not strictly later than available_at")
    checks["native_coverage_reconciles"] = int(coverage.get("native_1h_return_coverage", -1)) == int(
        native_covered.sum()
    )
    checks["native_covered_values_complete"] = bool(
        result.loc[native_covered, ["native_1h_return", "native_1h_abnormal_return"]].notna().all().all()
    )
    if not checks["native_coverage_reconciles"] or not checks["native_covered_values_complete"]:
        errors.append("native 1h coverage or values do not reconcile")

    conflict_rows = len(conflicts)
    checks["direction_conflict_count_reconciles"] = (
        int(coverage.get("direction_conflict_rows", -1)) == conflict_rows
    )
    if not checks["direction_conflict_count_reconciles"]:
        errors.append("direction conflict count does not reconcile")
    if "resolved_impact_direction" in conflicts:
        checks["direction_conflicts_resolve_to_review"] = bool(
            conflicts["resolved_impact_direction"].eq("review_required").all()
        )
        if not checks["direction_conflicts_resolve_to_review"]:
            errors.append("direction conflict rows do not resolve to review_required")
    bar_hole_rows = int(result["bar_hole_horizons"].fillna("").ne("").sum())
    checks["bar_hole_count_reconciles"] = int(coverage.get("bar_hole_event_rows", -1)) == bar_hole_rows
    if not checks["bar_hole_count_reconciles"]:
        errors.append("bar-hole count does not reconcile")

    candidate_mask = result["event_id"].astype(str).str.startswith("filing:")
    checks["candidate_count_reconciles"] = int(coverage.get("candidate_event_rows", -1)) == int(candidate_mask.sum())
    checks["canonical_count_reconciles"] = int(coverage.get("canonical_event_rows", -1)) == int((~candidate_mask).sum())
    if not checks["candidate_count_reconciles"] or not checks["canonical_count_reconciles"]:
        errors.append("canonical/candidate event counts do not reconcile")
    if candidate_mask.any():
        candidate = result.loc[candidate_mask]
        candidate_filter_ok = bool(
            candidate["candidate_status"].eq("discovery_candidate").all()
            and not candidate["category_is_composite"].astype(bool).any()
            and candidate["candidate_family"].isin(VALID_CANDIDATE_FAMILIES).all()
            and candidate["available_at"].notna().all()
            and (
                "event_study_eligible" not in candidate
                or candidate["event_study_eligible"].map(_as_bool).all()
            )
        )
        archive_symbols = set()
        for interval_symbols in (coverage.get("archive_symbols_by_interval") or {}).values():
            archive_symbols.update(str(symbol) for symbol in interval_symbols)
        candidate_tickers_in_archive = bool(
            not archive_symbols
            or set(candidate["ticker"].astype(str)).issubset(archive_symbols)
        )
        checks["candidate_filtering_invariants"] = candidate_filter_ok and candidate_tickers_in_archive
        if not checks["candidate_filtering_invariants"]:
            errors.append("candidate events violate exploratory filtering invariants")
    else:
        checks["candidate_filtering_invariants"] = True

    registered = registry["registered_for_trading_signal"].fillna(False).astype(bool)
    checks["no_registered_signals"] = not registered.any()
    if not checks["no_registered_signals"]:
        errors.append("signal_registry contains a registered trading signal")
    registry_contract_columns = {
        "statistical_gates_passed",
        "sample_tier",
        "trading_execution_eligible",
        "sample_gate",
        "date_gate",
        "t_stat_gate",
        "distribution_gate",
        "cost_direction_gate",
        "global_registration_gate_status",
        "status",
        "n_type_clusters",
    }
    missing_registry_contract = sorted(registry_contract_columns - set(registry.columns))
    checks["registry_execution_contract"] = not missing_registry_contract
    if missing_registry_contract:
        errors.append(
            "signal_registry missing execution-contract columns: "
            + ",".join(missing_registry_contract)
        )
    else:
        gate_columns = [
            "sample_gate",
            "date_gate",
            "t_stat_gate",
            "distribution_gate",
            "cost_direction_gate",
        ]
        expected_statistical = registry[gate_columns].apply(
            lambda column: column.map(_as_bool)
        ).all(axis=1)
        actual_statistical = registry["statistical_gates_passed"].map(_as_bool)
        checks["statistical_gate_status_reconciles"] = bool(
            (actual_statistical == expected_statistical).all()
        )
        expected_tier = registry["n_type_clusters"].map(
            lambda value: (
                "sufficient_sample"
                if int(value) >= MIN_SAMPLE_CLUSTERS
                else "insufficient_sample"
            )
        )
        checks["sample_tier_reconciles"] = bool(
            registry["sample_tier"].eq(expected_tier).all()
        )
        expected_eligibility = (
            registry["registered_for_trading_signal"].map(_as_bool)
            & actual_statistical
            & registry["status"].eq("candidate_review")
            & registry["global_registration_gate_status"].eq("passed")
        )
        actual_eligibility = registry["trading_execution_eligible"].map(_as_bool)
        checks["trading_execution_eligibility_reconciles"] = bool(
            (actual_eligibility == expected_eligibility).all()
        )
        if not all(
            checks[key]
            for key in [
                "statistical_gate_status_reconciles",
                "sample_tier_reconciles",
                "trading_execution_eligibility_reconciles",
            ]
        ):
            errors.append("signal registry execution contract does not reconcile")
    checks["registry_rows_reconcile"] = int(coverage.get("signal_registry_rows", -1)) == len(registry)
    checks["registry_signal_id_unique"] = not registry["signal_id"].duplicated().any()
    actual_status_counts = {
        str(key): int(value) for key, value in registry["status"].value_counts().to_dict().items()
    }
    expected_status_counts = {
        str(key): int(value)
        for key, value in (coverage.get("signal_registry_status_counts") or {}).items()
    }
    checks["registry_status_counts_reconcile"] = actual_status_counts == expected_status_counts
    if not all(
        checks[key]
        for key in ["registry_rows_reconcile", "registry_signal_id_unique", "registry_status_counts_reconcile"]
    ):
        errors.append("signal registry counts or keys do not reconcile")
    checks["production_database_unmodified"] = coverage.get("production_database_modified") is False
    if not checks["production_database_unmodified"]:
        errors.append("coverage does not confirm production database was unmodified")
    gate = coverage.get("signal_registration_gate") or {}
    gate_reasons = "; ".join(str(reason) for reason in gate.get("reasons", []))
    if not registry.empty:
        checks["registry_gate_status_reconciles"] = bool(
            registry["global_registration_gate_status"].eq(gate.get("status")).all()
        )
        checks["registry_gate_reasons_reconcile"] = bool(
            registry["global_registration_gate_reasons"].eq(gate_reasons).all()
        )
        if not checks["registry_gate_status_reconciles"] or not checks["registry_gate_reasons_reconcile"]:
            errors.append("signal registry global gate does not reconcile to coverage.json")
    else:
        checks["registry_gate_status_reconciles"] = True
        checks["registry_gate_reasons_reconcile"] = True

    comparison_audit = None if comparison_path is None else audit_comparison(comparison_path)
    if comparison_audit is not None and comparison_audit["status"] != "ok":
        errors.extend(str(error) for error in comparison_audit["errors"])
    return {
        "version": "hkex_event_study_output_audit.v1",
        "output_dir": str(output_dir),
        "status": "failed" if errors else "ok",
        "errors": errors,
        "checks": checks,
        "event_rows": int(len(result)),
        "registered_signal_rows": int(registered.sum()),
        "signal_gate_status": gate.get("status"),
        "comparison_audit": comparison_audit,
        "production_database_modified": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--comparison-json", type=Path)
    parser.add_argument("--write-audit", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    audit = audit_output(args.output_dir, comparison_path=args.comparison_json)
    if args.write_audit:
        (args.output_dir / "post_write_audit.json").write_text(
            json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(json.dumps(audit, indent=2, ensure_ascii=False))
    raise SystemExit(0 if audit["status"] == "ok" else 1)
