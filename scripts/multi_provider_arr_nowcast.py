#!/usr/bin/env python3
"""Calculate multi-provider OpenRouter ARR and August nowcasts.

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
propagated to the nine remaining weekdays and four remaining weekend days in
August 2026, then multiplied by 12 with the rest of the projected month.

Usage::

    python scripts/multi_provider_arr_nowcast.py
    python scripts/multi_provider_arr_nowcast.py --source /path/to/file.parquet

"""

from __future__ import annotations

import argparse
import calendar
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parents[1]
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
    projected_august_revenue_m3: float
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
    required = {"usage_date", "estimated_revenue"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Source is missing required columns: {sorted(missing)}")

    provider_col = "entity_id" if "entity_id" in raw.columns else "provider_slug"
    if provider_col not in raw.columns:
        raise ValueError("Source has neither entity_id nor provider_slug")

    raw["usage_date"] = pd.to_datetime(raw["usage_date"], errors="coerce").dt.normalize()
    raw["estimated_revenue"] = pd.to_numeric(raw["estimated_revenue"], errors="coerce")
    max_date = raw["usage_date"].max()
    if pd.isna(max_date):
        raise ValueError("usage_date contains no valid dates")

    target = raw[
        raw[provider_col].astype("string").str.casefold().isin(TARGETS)
        & raw["usage_date"].notna()
        & raw["estimated_revenue"].notna()
    ].copy()
    target = target.rename(columns={provider_col: "provider"})
    target["provider"] = target["provider"].astype(str).str.casefold()

    found = set(target["provider"].unique())
    absent = set(TARGETS) - found
    if absent:
        raise ValueError(f"Target providers absent from source: {sorted(absent)}")

    daily = (
        target.groupby(["provider", "usage_date"], as_index=False)["estimated_revenue"]
        .sum()
        .sort_values(["provider", "usage_date"])
        .reset_index(drop=True)
    )
    return daily, max_date


def month_is_complete(dates: Iterable[pd.Timestamp], period: pd.Period) -> bool:
    """Check that every calendar day in a month is present."""

    expected = pd.DatetimeIndex(
        pd.date_range(period.start_time, period.end_time.normalize(), freq="D")
    )
    return pd.DatetimeIndex(dates).sort_values().equals(expected.sort_values())


def build_monthly_history(
    daily: pd.DataFrame, max_date: pd.Timestamp
) -> tuple[pd.DataFrame, pd.Period]:
    """Build complete-month revenue and ARR history for every provider."""

    latest_period = max_date.to_period("M")
    retained = daily[daily["usage_date"] < max_date].copy()
    retained["month"] = retained["usage_date"].dt.to_period("M")

    rows: list[dict[str, object]] = []
    for (provider, period), group in retained.groupby(["provider", "month"]):
        days_in_month = calendar.monthrange(period.year, period.month)[1]
        observed_days = group["usage_date"].nunique()
        complete = month_is_complete(group["usage_date"], period)
        revenue = float(group["estimated_revenue"].sum())
        rows.append(
            {
                "provider": provider,
                "display_name": TARGETS[provider],
                "month": period,
                "month_label": str(period),
                "revenue": revenue,
                "observed_days": int(observed_days),
                "days_in_month": days_in_month,
                "complete": complete,
                "arr": revenue / days_in_month * 365.0 if complete else np.nan,
            }
        )

    history = pd.DataFrame(rows)
    if history.empty:
        raise ValueError("No historical observations before the latest source date")
    return history, latest_period


def calculate_pacing(
    daily: pd.DataFrame, history: pd.DataFrame, latest_period: pd.Period
) -> pd.DataFrame:
    """Calculate provider-specific first-18-day pacing ratios for Feb-Jul 2026."""

    year = latest_period.year
    pacing_months = [pd.Period(f"{year}-{month:02d}") for month in range(2, 8)]
    complete_history = history[history["complete"] & history["month"].isin(pacing_months)]
    retained = daily[daily["usage_date"] < daily["usage_date"].max()].copy()
    retained["month"] = retained["usage_date"].dt.to_period("M")

    records: list[dict[str, object]] = []
    for provider in TARGETS:
        provider_history = complete_history[complete_history["provider"].eq(provider)]
        ratios: list[float] = []
        detail: list[str] = []
        for period in pacing_months:
            month_data = retained[
                retained["provider"].eq(provider) & retained["month"].eq(period)
            ]
            if not provider_history["month"].eq(period).any():
                detail.append(f"{period}: incomplete")
                continue
            first_18 = float(
                month_data.loc[month_data["usage_date"].dt.day <= 18, "estimated_revenue"].sum()
            )
            total = float(month_data["estimated_revenue"].sum())
            if total <= 0:
                detail.append(f"{period}: zero revenue")
                continue
            ratios.append(first_18 / total)
            detail.append(f"{period}: {first_18 / total:.3f}")

        values = np.asarray(ratios, dtype=float)
        n = len(values)
        if n == 0 or np.all(values == 0):
            mean, std, se, ci_low, ci_high = 0.55, 0.10, 0.05, 0.35, 0.75
            detail.append("fallback estimate used (insufficient history)")
        else:
            mean = float(values.mean())
            std = float(values.std(ddof=1)) if n > 1 else 0.10
            se = std / np.sqrt(n) if n > 1 else 0.05
            ci_low = max(mean - Z_95 * se if n > 1 else mean * 0.7, 0.15)
            ci_high = min(mean + Z_95 * se if n > 1 else mean * 1.3, 0.95)
        records.append(
            {
                "provider": provider,
                "display_name": TARGETS[provider],
                "n": n,
                "mean": mean,
                "std": std,
                "se": se,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "detail": "; ".join(detail),
            }
        )

    return pd.DataFrame(records).set_index("provider")


def validate_aug_window(
    daily: pd.DataFrame, max_date: pd.Timestamp
) -> tuple[pd.Period, pd.DatetimeIndex, pd.DatetimeIndex]:
    """Return latest month, observed MTD days, and remaining calendar days."""

    latest_period = max_date.to_period("M")
    if latest_period.start_time.year != 2026 or latest_period.month != 8:
        # The calculations remain dynamic; this explicit warning aids operational use.
        print(
            f"Warning: source latest month is {latest_period}, not August 2026; "
            "day counts are derived from the source."
        )

    observed_end = max_date - pd.Timedelta(days=1)
    observed_dates = pd.date_range(latest_period.start_time, observed_end, freq="D")
    remaining_dates = pd.date_range(
        observed_end + pd.Timedelta(days=1), latest_period.end_time.normalize(), freq="D"
    )

    for provider in TARGETS:
        provider_dates = pd.DatetimeIndex(
            daily.loc[daily["provider"].eq(provider), "usage_date"]
        ).normalize()
        missing_observed = observed_dates.difference(provider_dates)
        if not missing_observed.empty:
            raise ValueError(
                f"{provider} is missing latest-month complete days: "
                f"{[date.date().isoformat() for date in missing_observed]}"
            )
    return latest_period, observed_dates, remaining_dates


def calculate_nowcasts(
    daily: pd.DataFrame,
    max_date: pd.Timestamp,
    pacing: pd.DataFrame,
) -> tuple[list[Nowcast], pd.DatetimeIndex, pd.DatetimeIndex]:
    """Calculate all four latest-month nowcasts independently by provider."""

    latest_period, observed_dates, remaining_dates = validate_aug_window(daily, max_date)
    latest_7_dates = observed_dates[-7:]
    remaining_weekday_count = sum(date.weekday() < 5 for date in remaining_dates)
    remaining_weekend_count = sum(date.weekday() >= 5 for date in remaining_dates)
    observed_days = len(observed_dates)

    results: list[Nowcast] = []
    for provider, display_name in TARGETS.items():
        provider_daily = daily[daily["provider"].eq(provider)].set_index("usage_date")
        mtd_revenue = float(provider_daily.loc[observed_dates, "estimated_revenue"].sum())
        latest_7 = provider_daily.loc[latest_7_dates, "estimated_revenue"].astype(float)
        weekday_values = latest_7[latest_7.index.weekday < 5].to_numpy(dtype=float)
        weekend_values = latest_7[latest_7.index.weekday >= 5].to_numpy(dtype=float)
        if len(weekday_values) < 2 or len(weekend_values) < 2:
            raise ValueError(
                f"Latest 7-day window for {provider} lacks both weekday and weekend replicates"
            )

        weekday_avg = float(weekday_values.mean())
        weekend_avg = float(weekend_values.mean())
        projected_revenue = mtd_revenue + (
            remaining_weekday_count * weekday_avg
            + remaining_weekend_count * weekend_avg
        )

        # Pooled residual SE around the two day-type means. Two group means use
        # two degrees of freedom, leaving five in this seven-day window.
        residuals = np.concatenate(
            [weekday_values - weekday_avg, weekend_values - weekend_avg]
        )
        residual_df = len(latest_7) - 2
        residual_se = float(np.sqrt(np.square(residuals).sum() / residual_df))
        weekday_mean_se = residual_se / np.sqrt(len(weekday_values))
        weekend_mean_se = residual_se / np.sqrt(len(weekend_values))
        projected_revenue_se = np.sqrt(
            (remaining_weekday_count * weekday_mean_se) ** 2
            + (remaining_weekend_count * weekend_mean_se) ** 2
        )
        projected_low = projected_revenue - Z_95 * projected_revenue_se
        projected_high = projected_revenue + Z_95 * projected_revenue_se

        pace = pacing.loc[provider]
        pace_mean = float(pace["mean"])
        pace_low = float(pace["ci_low"])
        pace_high = float(pace["ci_high"])
        m2 = mtd_revenue / pace_mean * 12.0
        m2_low = mtd_revenue / pace_high * 12.0
        m2_high = mtd_revenue / pace_low * 12.0

        latest_7_avg = float(latest_7.mean())
        results.append(
            Nowcast(
                provider=provider,
                display_name=display_name,
                mtd_revenue=mtd_revenue,
                observed_days=observed_days,
                m1=mtd_revenue / observed_days * 365.0,
                m2=m2,
                m2_low=m2_low,
                m2_high=m2_high,
                m3=projected_revenue * 12.0,
                m3_low=max(0.0, projected_low * 12.0),
                m3_high=projected_high * 12.0,
                m4=latest_7_avg * 365.0,
                latest_7_daily_avg=latest_7_avg,
                projected_august_revenue_m3=projected_revenue,
                weekday_avg=weekday_avg,
                weekend_avg=weekend_avg,
            )
        )

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


def print_pacing(pacing: pd.DataFrame) -> None:
    print("\n2) HISTORICAL 18-DAY PACING RATIOS — FEB–JUL 2026")
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
    july = history[
        history["complete"] & history["month"].eq(latest_period - 1)
    ].set_index("provider")["arr"]

    print(
        f"\n3) JULY ARR VS AUGUST {latest_period.year} NOWCASTS (ARR, $M)\n"
        "M1=Simple MTD | M2=18-day pacing | M3=weekday/weekend completion | "
        "M4=latest 7-day run-rate"
    )
    rows = []
    for item in nowcasts:
        july_arr = float(july.get(item.provider, 0.0))
        rows.append(
            {
                "Provider": item.display_name,
                "July": dollars_m(july_arr) if july_arr > 0 else "—",
                "M1": dollars_m(item.m1),
                "M2": dollars_m(item.m2),
                "M2 (95% CI)": range_m(item.m2_low, item.m2_high),
                "M3": dollars_m(item.m3),
                "M3 (95% CI)": range_m(item.m3_low, item.m3_high),
                "M4": dollars_m(item.m4),
                "M3 vs July": percent(item.m3 / july_arr - 1.0) if july_arr > 0 else "N/A",
                "M4 vs July": percent(item.m4 / july_arr - 1.0) if july_arr > 0 else "N/A",
            }
        )
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    return table


def print_market_share(nowcasts: list[Nowcast]) -> pd.DataFrame:
    frame = pd.DataFrame([item.__dict__ for item in nowcasts])
    m3_total = frame["m3"].sum()
    m4_total = frame["m4"].sum()
    frame["m3_share"] = frame["m3"] / m3_total
    frame["m4_share"] = frame["m4"] / m4_total
    frame = frame.sort_values("m4", ascending=False)

    print("\n4) AUGUST MARKET SHARE WITHIN THE 10 TARGET PROVIDERS")
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
        "August 2026 ARR Nowcasts by Provider",
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

    august_x = as_of.to_period("M").to_timestamp()
    top_frame = frame.set_index("provider").loc[top_providers]
    ax.errorbar(
        [august_x] * len(top_frame),
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
        label="August M3 nowcast (95% CI)",
    )
    ax.scatter(
        [august_x] * len(top_frame),
        top_frame["m4"] / 1e6,
        marker="D",
        s=42,
        color="#f59e0b",
        edgecolor="white",
        linewidth=0.8,
        zorder=5,
        label="August M4 run-rate",
    )

    ax.set_title(
        "Monthly ARR Trajectories and August 2026 Nowcasts — Top 6 Providers",
        loc="left",
        fontsize=18,
        fontweight="bold",
        pad=16,
    )
    ax.text(
        0,
        1.012,
        "Complete months annualized ×365; August uses independent M3 weekday/weekend completion and M4 latest-7-day run-rate.",
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
    pacing = calculate_pacing(daily, history, latest_period)
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
    print_pacing(pacing)
    print_nowcasts(history, latest_period, nowcasts)
    shares = print_market_share(nowcasts)

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
