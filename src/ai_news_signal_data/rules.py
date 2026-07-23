from __future__ import annotations

import pandas as pd

# ai_news_hf_trending_models is a numeric leaderboard snapshot, not narrative
# text, so it's flagged by threshold instead of spending a guard LLM call on it.
TOP_N = 10
MIN_TRENDING_SCORE = 200


def flag_trending_models(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.assign(importance=pd.Series(dtype="string"))
    ranked = df.sort_values("trending_score", ascending=False).reset_index(drop=True)
    is_top = ranked.index < TOP_N
    score = pd.to_numeric(ranked["trending_score"], errors="coerce")
    ranked["importance"] = "low"
    ranked.loc[is_top | (score >= MIN_TRENDING_SCORE), "importance"] = "high"
    return ranked
