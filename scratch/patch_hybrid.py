import sys
import re

with open("dashboard/app.py", "r") as f:
    content = f.read()

# We want to replace the block starting at '# --- Revenue Estimator Logic ---'
# and ending right before 'def render_leaderboard('

start_pattern = r"# --- Revenue Estimator Logic ---\n.*?\n\s+views\[\"revenue_estimator\"\] = \{\n\s+\"pivot_rev\": pd\.DataFrame\(\),\n\s+\"total_revenue\": 0,\n\s+\"has_activity\": False,\n\s+\"merged_count\": 0\n\s+\}\n\n\n\s*def render_leaderboard"

new_block = """# --- Revenue Estimator Logic ---
    activity_res = datasets.get("app_usage_daily")
    macro_res = datasets.get("top_models")
    pricing_res = datasets.get("raw_openrouter_models")

    if activity_res and not activity_res.frame.empty and pricing_res and not pricing_res.frame.empty:
        pricing = pricing_res.frame.copy()
        
        # Get latest pricing per model
        latest_pricing = pricing.sort_values("snapshot_ts").groupby("model_id").tail(1)
        pricing_model_ids = set(latest_pricing["model_id"].tolist())
        
        def normalize_slug(slug):
            slug_str = str(slug)
            if pd.isna(slug_str) or slug_str == "nan":
                return slug_str
            if slug_str in pricing_model_ids:
                return slug_str
            import re
            base = re.sub(r'-\d{4,8}$', '', slug_str)
            if base in pricing_model_ids:
                return base
            if base.startswith("anthropic/claude-"):
                m = re.match(r'anthropic/claude-([\\d\\.]+)-(opus|sonnet|haiku)', base)
                if m:
                    permuted = f"anthropic/claude-{m.group(2)}-{m.group(1)}"
                    if permuted in pricing_model_ids:
                        return permuted
            if base.startswith("qwen/qwen"):
                if "plus" in base and "qwen/qwen-plus" in pricing_model_ids:
                    return "qwen/qwen-plus"
                if "max" in base and "qwen/qwen-max" in pricing_model_ids:
                    return "qwen/qwen-max"
            return slug_str
            
        def process_revenue_df(df, slug_col, tokens_col, date_col, is_macro=False):
            df["fuzzy_slug"] = df[slug_col].apply(normalize_slug)
            df_cols = [c for c in df.columns if c not in ["pricing_prompt", "pricing_completion", "top_provider_id", "model_id"]]
            
            merged = df[df_cols].merge(
                latest_pricing[["model_id", "pricing_prompt", "pricing_completion", "top_provider_id"]],
                left_on="fuzzy_slug", right_on="model_id", how="inner"
            )
            merged = merged[(merged["pricing_prompt"].notna()) & (merged["pricing_prompt"] >= 0)].copy()
            if merged.empty:
                return pd.DataFrame()
                
            if not is_macro and "prompt_tokens" in merged.columns and "completion_tokens" in merged.columns and merged["prompt_tokens"].notna().any():
                merged["revenue_usd"] = (
                    (merged["prompt_tokens"] * merged["pricing_prompt"].astype(float) / 1e6) +
                    (merged["completion_tokens"] * merged["pricing_completion"].astype(float) / 1e6)
                )
            else:
                merged["revenue_usd"] = (
                    (merged[tokens_col] * 0.977 * merged["pricing_prompt"].astype(float) / 1e6) +
                    (merged[tokens_col] * 0.023 * merged["pricing_completion"].astype(float) / 1e6)
                )
                
            merged["provider_label"] = merged.apply(
                lambda x: _derive_provider_name(x["model_id"], x["top_provider_id"]), axis=1
            )
            
            merged["usage_date_dt"] = pd.to_datetime(merged[date_col], errors="coerce")
            merged = merged.dropna(subset=["usage_date_dt"])
            merged = merged[merged["revenue_usd"] > 0].copy()
            if merged.empty:
                return pd.DataFrame()
            merged["usage_date_str"] = merged["usage_date_dt"].dt.strftime('%Y-%m-%d')
            merged["usage_week"] = merged["usage_date_dt"].dt.to_period('W').dt.start_time.dt.strftime('%Y-%m-%d')
            merged["usage_month"] = merged["usage_date_dt"].dt.strftime('%Y-%m')
            return merged
        
        # 1. Micro Scope (Daily)
        activity = activity_res.frame.copy()
        merged_daily = process_revenue_df(activity, "model_permaslug", "total_tokens", "usage_date")
        pivot_rev_daily = pd.DataFrame()
        if not merged_daily.empty:
            pivot_rev_daily = (
                merged_daily.pivot_table(index="usage_date_str", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0).sort_index()
            )

        # 2. Macro Scope (Weekly / Monthly)
        pivot_rev_weekly = pd.DataFrame()
        pivot_rev_monthly = pd.DataFrame()
        if macro_res and not macro_res.frame.empty:
            macro = macro_res.frame.copy()
            macro = macro[macro["entity_id"] != "Others"].copy()
            merged_macro = process_revenue_df(macro, "entity_id", "metric_value", "week_start_date", is_macro=True)
            if not merged_macro.empty:
                pivot_rev_weekly = (
                    merged_macro.pivot_table(index="usage_week", columns="provider_label", values="revenue_usd", aggfunc="sum")
                    .fillna(0).sort_index()
                )
                pivot_rev_monthly = (
                    merged_macro.pivot_table(index="usage_month", columns="provider_label", values="revenue_usd", aggfunc="sum")
                    .fillna(0).sort_index()
                )
                
        # Fallback if macro failed
        if pivot_rev_weekly.empty and not merged_daily.empty:
            pivot_rev_weekly = merged_daily.pivot_table(index="usage_week", columns="provider_label", values="revenue_usd", aggfunc="sum").fillna(0).sort_index()
        if pivot_rev_monthly.empty and not merged_daily.empty:
            pivot_rev_monthly = merged_daily.pivot_table(index="usage_month", columns="provider_label", values="revenue_usd", aggfunc="sum").fillna(0).sort_index()
        
        views["revenue_estimator"] = {
            "pivot_rev": pivot_rev_daily,
            "pivot_rev_daily": pivot_rev_daily,
            "pivot_rev_weekly": pivot_rev_weekly,
            "pivot_rev_monthly": pivot_rev_monthly,
            "total_revenue": merged_daily["revenue_usd"].sum() if not merged_daily.empty else 0,
            "has_activity": not activity.empty,
            "merged_count": len(merged_daily) if not merged_daily.empty else 0
        }
    else:
        views["revenue_estimator"] = {
            "pivot_rev": pd.DataFrame(),
            "total_revenue": 0,
            "has_activity": False,
            "merged_count": 0
        }


def render_leaderboard"""

replaced_content = re.sub(start_pattern, new_block, content, flags=re.DOTALL)

if replaced_content == content:
    print("Error: No replacement made, regex didn't match.")
else:
    with open("dashboard/app.py", "w") as f:
        f.write(replaced_content)
    print("Success: App payload replaced.")
