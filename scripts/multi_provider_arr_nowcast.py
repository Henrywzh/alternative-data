#!/usr/bin/env python3
"""Calculate multi-provider OpenRouter ARR and latest-month nowcasts.

The primary source is ``daily_provider_revenue_estimates.parquet``. Complete
calendar months use ``(month revenue / calendar days) * 365``. The latest source
date is treated as incomplete and excluded. For the resulting latest-month MTD,
this script calculates four independent provider nowcasts:

1. Simple MTD daily average annualized by 365.
2. Provider-specific historical first-18-day pacing model with a 95% CI.
3. Weekday/weekend seasonally adjusted completion model with a 95% CI.
4. Latest-seven-day daily run-rate annualized by 365.

Method 3's interval uses the pooled residual standard error from the latest
seven days around separate weekday and weekend means. That residual SE is
propagated to the remaining weekdays and weekend days in the latest calendar
month, then multiplied by 12 with the rest of the projected month.

Usage::

    python scripts/multi_provider_arr_nowcast.py
    python scripts/multi_provider_arr_nowcast.py --source /path/to/file.parquet

"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openrouter_arr_nowcast import (
    build_monthly_history as _build_monthly_history,
    calculate_nowcasts as _calculate_nowcasts,
    calculate_pacing as _calculate_pacing,
    latest_month_window,
    month_is_complete as _month_is_complete,
    pacing_periods,
    prepare_target_daily,
)


RELATIVE_SOURCE = Path("data/normalized/marts/daily_provider_revenue_estimates.parquet")
DEFAULT_SOURCE = ROOT / RELATIVE_SOURCE
FALLBACK_SOURCE = Path.home() / "Quant" / "alternative-data" / RELATIVE_SOURCE

TARGETS: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "deepseek": "DeepSeek",
    "z-ai": "Z.ai",
    "moonshotai": "Moonshot",
    "xiaomi": "Xiaomi",
    "minimax": "MiniMax",
    "x-ai": "xAI",
    "tencent": "Tencent",
    "qwen": "Qwen",
    "meta": "Meta",
}

PROVIDER_COLORS = {
    "openai": "#0f766e",
    "anthropic": "#d97706",
    "google": "#2563eb",
    "deepseek": "#7c3aed",
    "z-ai": "#db2777",
    "moonshotai": "#059669",
    "xiaomi": "#ea580c",
    "minimax": "#0284c7",
    "x-ai": "#475569",
    "tencent": "#16a34a",
    "qwen": "#0891b2",
    "meta": "#6366f1",
}

Z_95 = 1.959963984540054


@dataclass(frozen=True)
class Nowcast:
    provider: str
    display_name: str
    mtd_revenue: float
    observed_days: int
    m1: float
    m2: float
    m2_low: float
    m2_high: float
    m3: float
    m3_low: float
    m3_high: float
    m4: float
    latest_7_daily_avg: float
    projected_latest_revenue_m3: float
    weekday_avg: float
    weekend_avg: float


def resolve_source(explicit: str | None) -> Path:
    """Return an existing source path, including the machine's data mount."""

    candidates = [
        Path(explicit).expanduser().resolve() if explicit else None,
        DEFAULT_SOURCE,
        FALLBACK_SOURCE,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    attempted = "\n".join(f"  - {path}" for path in candidates if path is not None)
    raise FileNotFoundError(
        "Could not find daily_provider_revenue_estimates.parquet. Tried:\n" + attempted
    )


def load_target_daily(source: Path) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Load and aggregate target-provider revenue to one provider/day row."""

    raw = pd.read_parquet(source)
    # ``provider_slug`` is the canonical company identity used by the
    # dashboard (for example, it combines ``meta`` and ``meta-llama``).
    # ``entity_id`` can retain legacy aliases and would undercount those labs.
    provider_col = "provider_slug" if "provider_slug" in raw.columns else "entity_id"
    if provider_col not in raw.columns:
        raise ValueError("Source has neither entity_id nor provider_slug")

    daily, max_date = prepare_target_daily(
        raw, provider_column=provider_col, targets=TARGETS
    )
    found = set(daily["provider"].unique())
    absent = set(TARGETS) - found
    if absent:
        raise ValueError(f"Target providers absent from source: {sorted(absent)}")
    return daily, max_date


def month_is_complete(dates: Iterable[pd.Timestamp], period: pd.Period) -> bool:
    """Check that every calendar day in a month is present."""

    return _month_is_complete(dates, period)


def build_monthly_history(
    daily: pd.DataFrame, max_date: pd.Timestamp
) -> tuple[pd.DataFrame, pd.Period]:
    """Build complete-month revenue and ARR history for every provider."""

    history, latest_period = _build_monthly_history(daily, max_date, TARGETS)
    if history.empty:
        raise ValueError("No historical observations before the latest source date")
    return history, latest_period


def calculate_pacing(
    daily: pd.DataFrame,
    history: pd.DataFrame,
    latest_period: pd.Period,
    max_date: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Calculate pacing from the six calendar months before the latest month."""

    source_latest_date = pd.Timestamp(
        max_date if max_date is not None else daily["usage_date"].max()
    ).normalize()
    observed_days = max(
        (source_latest_date - latest_period.start_time.normalize()).days, 1
    )
    return _calculate_pacing(
        daily,
        history,
        latest_period,
        source_latest_date,
        TARGETS,
        observed_days=observed_days,
    )


def validate_latest_window(
    daily: pd.DataFrame, max_date: pd.Timestamp
) -> tuple[pd.Period, pd.DatetimeIndex, pd.DatetimeIndex]:
    """Return latest month, observed MTD days, and remaining calendar days."""

    return latest_month_window(daily, max_date, TARGETS)


# Keep the old helper name for callers that imported it, while making the
# implementation and labels month-agnostic.
validate_aug_window = validate_latest_window


def calculate_nowcasts(
    daily: pd.DataFrame,
    max_date: pd.Timestamp,
    pacing: pd.DataFrame,
) -> tuple[list[Nowcast], pd.DatetimeIndex, pd.DatetimeIndex]:
    """Calculate all four latest-month nowcasts independently by provider."""

    history, latest_period = build_monthly_history(daily, max_date)
    shared_results, observed_dates, remaining_dates, _ = _calculate_nowcasts(
        daily, max_date, pacing, history, TARGETS
    )
    results = [
        Nowcast(
            provider=item.provider,
            display_name=item.display_name,
            mtd_revenue=item.mtd_revenue,
            observed_days=item.observed_days,
            m1=item.m1_arr,
            m2=item.m2_arr,
            m2_low=item.m2_low,
            m2_high=item.m2_high,
            m3=item.m3_arr,
            m3_low=item.m3_low,
            m3_high=item.m3_high,
            m4=item.m4_arr,
            latest_7_daily_avg=item.latest_7_daily_avg,
            projected_latest_revenue_m3=item.projected_latest_revenue_m3,
            weekday_avg=item.weekday_avg,
            weekend_avg=item.weekend_avg,
        )
        for item in shared_results
    ]
    return results, observed_dates, remaining_dates


def dollars_m(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return "—"
    return f"${value / 1e6:,.{digits}f}M"


def range_m(low: float, high: float, digits: int = 1) -> str:
    if pd.isna(low) or pd.isna(high):
        return "—"
    return f"${low / 1e6:,.{digits}f}–${high / 1e6:,.{digits}f}M"


def percent(value: float, digits: int = 1) -> str:
    if pd.isna(value):
        return "—"
    return f"{value * 100:+.{digits}f}%"


def print_history(history: pd.DataFrame, latest_period: pd.Period) -> None:
    print("\n1) HISTORICAL MONTHLY ARR — COMPLETE CALENDAR MONTHS ONLY ($M)")
    table_start = history["month"].min()
    complete = history[
        history["complete"]
        & history["month"].between(table_start, latest_period - 1)
    ].copy()
    pivot = complete.pivot(index="month", columns="provider", values="arr")
    output = (
        pivot.reindex(columns=list(TARGETS))
        .rename(columns=TARGETS)
        .rename_axis("Month")
        / 1e6
    )
    print(output.to_string(float_format=lambda value: f"{value:,.1f}", na_rep="—"))


def print_pacing(pacing: pd.DataFrame, latest_period: pd.Period | None = None) -> None:
    if latest_period is None:
        pacing_label = "historical calendar-month pacing"
    else:
        periods = pacing_periods(latest_period)
        pacing_label = f"{periods[0]}–{periods[-1]} pacing"
    print(f"\n2) HISTORICAL PACING RATIOS — {pacing_label}")
    rows = []
    for provider, row in pacing.iterrows():
        rows.append(
            {
                "Provider": TARGETS[provider],
                "N": int(row["n"]),
                "Mean": f"{row['mean']:.4f}",
                "Std": f"{row['std']:.4f}" if pd.notna(row["std"]) else "—",
                "SE": f"{row['se']:.4f}" if pd.notna(row["se"]) else "—",
                "95% CI": f"[{row['ci_low']:.4f}, {row['ci_high']:.4f}]",
                "Valid months": row["detail"],
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))


def print_nowcasts(
    history: pd.DataFrame,
    latest_period: pd.Period,
    nowcasts: list[Nowcast],
) -> pd.DataFrame:
    latest_label = latest_period.strftime("%B %Y")
    prior_period = latest_period - 1
    prior_label = prior_period.strftime("%B %Y")
    prior = history[
        history["complete"] & history["month"].eq(prior_period)
    ].set_index("provider")["arr"]

    print(
        f"\n3) {prior_label.upper()} ARR VS {latest_label.upper()} NOWCASTS (ARR, $M)\n"
        f"M1=Simple MTD | M2={nowcasts[0].observed_days if nowcasts else 'latest'}-day pacing | "
        "M3=weekday/weekend completion | "
        "M4=latest 7-day run-rate"
    )
    rows = []
    for item in nowcasts:
        prior_arr = float(prior.get(item.provider, 0.0))
        rows.append(
            {
                "Provider": item.display_name,
                f"{prior_label} Complete ARR": dollars_m(prior_arr) if prior_arr > 0 else "—",
                "M1": dollars_m(item.m1),
                "M2": dollars_m(item.m2),
                "M2 (95% CI)": range_m(item.m2_low, item.m2_high),
                "M3": dollars_m(item.m3),
                "M3 (95% CI)": range_m(item.m3_low, item.m3_high),
                "M4": dollars_m(item.m4),
                f"M3 vs {prior_label}": percent(item.m3 / prior_arr - 1.0) if prior_arr > 0 else "N/A",
                f"M4 vs {prior_label}": percent(item.m4 / prior_arr - 1.0) if prior_arr > 0 else "N/A",
            }
        )
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    return table


def print_market_share(
    nowcasts: list[Nowcast], latest_period: pd.Period | None = None
) -> pd.DataFrame:
    frame = pd.DataFrame([item.__dict__ for item in nowcasts])
    m3_total = frame["m3"].sum()
    m4_total = frame["m4"].sum()
    frame["m3_share"] = frame["m3"] / m3_total
    frame["m4_share"] = frame["m4"] / m4_total
    frame = frame.sort_values("m4", ascending=False)

    period_label = latest_period.strftime("%B %Y") if latest_period is not None else "latest month"
    print(f"\n4) {period_label.upper()} MARKET SHARE WITHIN THE TARGET PROVIDERS")
    rows = []
    for rank, item in enumerate(frame.itertuples(index=False), start=1):
        rows.append(
            {
                "Rank": rank,
                "Provider": TARGETS[item.provider],
                "M3 ARR": dollars_m(item.m3),
                "M3 share": f"{item.m3_share:.1%}",
                "M4 ARR": dollars_m(item.m4),
                "M4 share": f"{item.m4_share:.1%}",
            }
        )
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    return frame


def comparison_chart(
    shares: pd.DataFrame,
    output: Path,
    source: Path,
    as_of: pd.Timestamp,
    dpi: int,
) -> None:
    ordered = shares.sort_values("m4", ascending=True).reset_index(drop=True)
    y = np.arange(len(ordered))
    height = 0.36

    fig, (ax, share_ax) = plt.subplots(
        2,
        1,
        figsize=(15, 12),
        dpi=dpi,
        gridspec_kw={"height_ratios": [1.45, 1.0]},
        constrained_layout=True,
    )
    fig.patch.set_facecolor("white")

    ax.barh(
        y - height / 2,
        ordered["m3"] / 1e6,
        height=height,
        color="#2563eb",
        alpha=0.9,
        label="M3: seasonally adjusted nowcast",
    )
    ax.barh(
        y + height / 2,
        ordered["m4"] / 1e6,
        height=height,
        color="#f59e0b",
        alpha=0.95,
        label="M4: latest 7-day run-rate",
    )
    ax.errorbar(
        ordered["m3"] / 1e6,
        y - height / 2,
        xerr=(
            (ordered["m3"] - ordered["m3_low"]) / 1e6,
            (ordered["m3_high"] - ordered["m3"]) / 1e6,
        ),
        fmt="none",
        ecolor="#1e3a8a",
        elinewidth=1.5,
        capsize=3.5,
        label="M3 95% CI",
    )
    ax.set_yticks(y, ordered["display_name"])
    ax.invert_yaxis()
    ax.set_xlabel("Annualized ARR ($M)")
    ax.set_title(
        f"{as_of.strftime('%B %Y')} ARR Nowcasts by Provider",
        loc="left",
        fontsize=18,
        fontweight="bold",
        pad=16,
    )
    ax.text(
        0,
        1.012,
        "OpenRouter estimated revenue; M3 fills remaining days with latest weekday/weekend averages, M4 annualizes latest 7 days.",
        transform=ax.transAxes,
        fontsize=9.5,
        color="#4b5563",
    )
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    ax.set_xlim(0, max(ordered[["m3", "m4"]].max().max() / 1e6 * 1.18, 5))
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=True, facecolor="white", edgecolor="#cbd5e1", loc="lower right", ncol=1)

    share_ax.barh(
        y - height / 2,
        ordered["m3_share"] * 100,
        height=height,
        color="#2563eb",
        alpha=0.55,
        label="Share by M3",
    )
    share_ax.barh(
        y + height / 2,
        ordered["m4_share"] * 100,
        height=height,
        color="#f59e0b",
        alpha=0.65,
        label="Share by M4",
    )
    for index, row in ordered.iterrows():
        share_ax.text(row["m3_share"] * 100 + 0.25, index - height / 2, f"{row['m3_share']:.1%}")
        share_ax.text(row["m4_share"] * 100 + 0.25, index + height / 2, f"{row['m4_share']:.1%}")
    share_ax.set_yticks(y, ordered["display_name"])
    share_ax.invert_yaxis()
    share_ax.set_xlim(0, max(ordered[["m3_share", "m4_share"]].max().max() * 100 * 1.16, 5))
    share_ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
    share_ax.set_xlabel("Share of combined target-provider ARR")
    share_ax.set_title("Implied Market Share Within Target Group", loc="left", fontsize=15, fontweight="bold")
    share_ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    share_ax.spines[["top", "right"]].set_visible(False)
    share_ax.legend(frameon=True, facecolor="white", edgecolor="#cbd5e1", loc="lower right", ncol=2)

    fig.text(
        0.01,
        0.002,
        f"Source: {source} | Incomplete latest source day excluded; calculations through {as_of.date()}",
        fontsize=8.5,
        color="#6b7280",
    )
    fig.savefig(output, dpi=dpi, facecolor="white")
    plt.close(fig)


def trajectory_chart(
    history: pd.DataFrame,
    nowcasts: list[Nowcast],
    output: Path,
    source: Path,
    as_of: pd.Timestamp,
    dpi: int,
) -> None:
    frame = pd.DataFrame([item.__dict__ for item in nowcasts])
    top_providers = frame.sort_values("m4", ascending=False).head(6)["provider"].tolist()
    start = pd.Period(f"{as_of.year - 1}-01")
    end = as_of.to_period("M") - 1
    months = pd.period_range(start, end, freq="M")

    complete = history[
        history["complete"] & history["month"].isin(months)
    ].copy()
    pivot = complete.pivot(index="month", columns="provider", values="arr").reindex(
        months, columns=top_providers
    )

    fig, ax = plt.subplots(figsize=(16, 9), dpi=dpi, constrained_layout=True)
    fig.patch.set_facecolor("white")
    x = np.array([month.to_timestamp() for month in months])
    for provider in top_providers:
        values = pivot[provider].to_numpy(dtype=float) / 1e6
        ax.plot(
            x,
            values,
            color=PROVIDER_COLORS[provider],
            linewidth=2.3,
            marker="o",
            markersize=3.8,
            label=TARGETS[provider],
        )

    latest_period = as_of.to_period("M")
    latest_label = latest_period.strftime("%B %Y")
    latest_x = latest_period.to_timestamp()
    top_frame = frame.set_index("provider").loc[top_providers]
    ax.errorbar(
        [latest_x] * len(top_frame),
        top_frame["m3"] / 1e6,
        yerr=(
            (top_frame["m3"] - top_frame["m3_low"]) / 1e6,
            (top_frame["m3_high"] - top_frame["m3"]) / 1e6,
        ),
        fmt="o",
        markersize=6.5,
        markerfacecolor="white",
        markeredgecolor="#111827",
        ecolor="#111827",
        elinewidth=1.2,
        capsize=3,
        label=f"{latest_label} M3 nowcast (95% CI)",
    )
    ax.scatter(
        [latest_x] * len(top_frame),
        top_frame["m4"] / 1e6,
        marker="D",
        s=42,
        color="#f59e0b",
        edgecolor="white",
        linewidth=0.8,
        zorder=5,
        label=f"{latest_label} M4 run-rate",
    )

    ax.set_title(
        f"Monthly ARR Trajectories and {latest_label} Nowcasts — Top 6 Providers",
        loc="left",
        fontsize=18,
        fontweight="bold",
        pad=16,
    )
    ax.text(
        0,
        1.012,
        f"Complete months annualized ×365; {latest_label} uses independent M3 weekday/weekend completion and M4 latest-7-day run-rate.",
        transform=ax.transAxes,
        fontsize=9.5,
        color="#4b5563",
    )
    ax.set_ylabel("Annualized ARR ($M)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}M"))
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=True, facecolor="white", edgecolor="#cbd5e1", ncol=4, loc="upper left")
    fig.text(
        0.01,
        0.002,
        f"Source: {source} | History through {end} | Incomplete latest source day excluded; MTD through {as_of.date()}",
        fontsize=8.5,
        color="#6b7280",
    )
    fig.savefig(output, dpi=dpi, facecolor="white")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Path to daily_provider_revenue_estimates.parquet")
    parser.add_argument("--output-dir", type=Path, default=ROOT, help="PNG output directory")
    parser.add_argument("--dpi", type=int, default=240, help="Chart resolution (240+ recommended)")
    args = parser.parse_args()
    if args.dpi < 72:
        parser.error("--dpi must be at least 72")
    return args


def main() -> None:
    args = parse_args()
    source = resolve_source(args.source)
    daily, max_date = load_target_daily(source)
    history, latest_period = build_monthly_history(daily, max_date)
    pacing = calculate_pacing(daily, history, latest_period, max_date)
    nowcasts, observed_dates, remaining_dates = calculate_nowcasts(daily, max_date, pacing)
    as_of = observed_dates[-1]
    remaining_weekdays = sum(date.weekday() < 5 for date in remaining_dates)
    remaining_weekends = len(remaining_dates) - remaining_weekdays

    print(f"Source: {source}")
    print(f"Rows retained for targets: {len(daily):,}")
    print(f"Latest source date (excluded as incomplete): {max_date.date()}")
    print(f"Nowcast window: {observed_dates[0].date()} to {as_of.date()} ({len(observed_dates)} days)")
    print(
        "Remaining days to complete month: "
        f"{len(remaining_dates)} ({remaining_weekdays} weekdays, {remaining_weekends} weekend days)"
    )
    print(
        "Latest 7-day weekday/weekend window: "
        f"{observed_dates[-7].date()} to {as_of.date()}"
    )

    print_history(history, latest_period)
    print_pacing(pacing, latest_period)
    print_nowcasts(history, latest_period, nowcasts)
    shares = print_market_share(nowcasts, latest_period)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = args.output_dir / "multi_provider_arr_comparison.png"
    trajectory_path = args.output_dir / "multi_provider_arr_trajectories.png"
    comparison_chart(shares, comparison_path, source, as_of, args.dpi)
    trajectory_chart(history, nowcasts, trajectory_path, source, as_of, args.dpi)

    print("\nOUTPUTS")
    print(f"Saved: {comparison_path}")
    print(f"Saved: {trajectory_path}")


if __name__ == "__main__":
    main()
