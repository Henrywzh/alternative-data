"""Display prices from current and historical Ramp Tokenomics records."""

from __future__ import annotations

import pandas as pd


def effective_token_prices(frame: pd.DataFrame) -> pd.DataFrame:
    """Prefer Ramp's published price, with cost/count for older observations.

    The source publishes its own blend. For history where only the legacy
    cost/count pairs exist, reconstruct the blend from both makers' weights.
    """
    keys = ["usage_date", "token_type", "model_maker"]
    costs = ["token_cost_usd_7d", "token_count_7d"]
    price_column = "price_per_million"
    data = frame.reindex(columns=[*keys, *costs, price_column]).copy()
    for column in [*costs, price_column]:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    grouped = data.groupby(keys)
    published = grouped[price_column].first()
    legacy = grouped[costs].sum(min_count=1)
    both_makers = legacy.loc[
        legacy.index.get_level_values("model_maker").isin(["openai", "anthropic"])
    ].dropna()
    by_day = both_makers.groupby(level=keys[:2])
    blended = by_day.sum(min_count=1).loc[by_day.size().eq(2)]
    count = blended["token_count_7d"].where(blended["token_count_7d"].gt(0))
    blended_price = (blended["token_cost_usd_7d"] / count * 1_000_000).rename(price_column)
    blended_price = blended_price.reset_index().assign(model_maker="blend").set_index(keys)[price_column]

    count = legacy["token_count_7d"].where(legacy["token_count_7d"].gt(0))
    legacy_price = legacy["token_cost_usd_7d"] / count * 1_000_000
    return published.combine_first(legacy_price).combine_first(blended_price).rename(price_column).reset_index()
