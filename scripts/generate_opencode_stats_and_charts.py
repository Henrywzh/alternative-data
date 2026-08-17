import pathlib
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# Set matplotlib style
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.sans-serif'] = 'Helvetica, Arial, DejaVu Sans'
plt.rcParams['axes.edgecolor'] = '#cccccc'
plt.rcParams['axes.linewidth'] = 0.8

base_dir = pathlib.Path(".")
data_dir = base_dir / "data" / "normalized" / "opencode"
artifacts_dir = pathlib.Path("/Users/henrywzh/.gemini/antigravity/brain/79920c81-d15b-4034-95d6-b2df1537097f")

def generate_charts_and_tables():
    # 1. Market Share Trend
    ms_path = data_dir / "opencode_market_share.csv"
    if ms_path.exists():
        ms_df = pd.read_csv(ms_path)
        # Filter for 3M timeframe daily
        m3_df = ms_df[ms_df["timeframe"] == "3M"].copy()
        if not m3_df.empty:
            pivot_ms = m3_df.pivot(index="usage_date", columns="author", values="share_pct").fillna(0)
            
            fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
            colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22"]
            pivot_ms.plot(kind="area", stacked=True, ax=ax, alpha=0.85, color=colors[:len(pivot_ms.columns)])
            
            ax.set_title("OpenCode Model Market Share Trend (Last 90 Days)", fontsize=14, fontweight="bold", pad=12)
            ax.set_xlabel("Date", fontsize=11, labelpad=8)
            ax.set_ylabel("Token Volume Share (%)", fontsize=11, labelpad=8)
            ax.set_ylim(0, 100)
            ax.legend(title="Model Author / Lab", bbox_to_anchor=(1.02, 1), loc="upper left", frameon=True)
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            img_path = artifacts_dir / "opencode_market_share_trend.png"
            plt.savefig(img_path, dpi=300)
            plt.close()
            print(f"Generated chart: {img_path}")

    # 2. Top Model Deepdives - Token Mix
    dd_path = data_dir / "opencode_model_deepdives.csv"
    if dd_path.exists():
        dd_df = pd.read_csv(dd_path)
        if not dd_df.empty and "model_slug" in dd_df.columns:
            top_dd = dd_df.sort_values(by="sessions", ascending=False).head(8)
            
            models = top_dd["model_slug"].values
            cached = top_dd["cached_tokens"].fillna(0).values / 1e12
            input_t = top_dd["input_tokens"].fillna(0).values / 1e12
            output_t = top_dd["output_tokens"].fillna(0).values / 1e12
            reasoning_t = top_dd["reasoning_tokens"].fillna(0).values / 1e12
            
            fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
            x = np.arange(len(models))
            width = 0.55
            
            p1 = ax.bar(x, cached, width, label="Cached Tokens (Prompt Caching)", color="#2b5c8f")
            p2 = ax.bar(x, input_t, width, bottom=cached, label="Input Tokens", color="#4682b4")
            p3 = ax.bar(x, output_t, width, bottom=cached+input_t, label="Output Tokens", color="#57a0d3")
            p4 = ax.bar(x, reasoning_t, width, bottom=cached+input_t+output_t, label="Reasoning Tokens (Chain of Thought)", color="#e056fd")
            
            ax.set_title("Token Volume & Mix Composition by Model (Trillion Tokens)", fontsize=14, fontweight="bold", pad=12)
            ax.set_xticks(x)
            ax.set_xticklabels(models, rotation=30, ha="right", fontsize=10)
            ax.set_ylabel("Tokens (Trillions)", fontsize=11)
            ax.legend(frameon=True)
            plt.tight_layout()
            
            img_path = artifacts_dir / "opencode_token_mix.png"
            plt.savefig(img_path, dpi=300)
            plt.close()
            print(f"Generated chart: {img_path}")

    # 3. Country Breakdown
    country_path = data_dir / "opencode_country_usage.csv"
    if country_path.exists():
        c_df = pd.read_csv(country_path)
        c_1m = c_df[c_df["timeframe"] == "1M"].head(10).copy()
        if not c_1m.empty:
            fig, ax = plt.subplots(figsize=(9, 4.5), dpi=300)
            ax.barh(c_1m["country_code"][::-1], c_1m["share_pct"][::-1], color="#20bf6b", alpha=0.85)
            ax.set_title("Top 10 Countries by Developer Usage Share (Last 30 Days)", fontsize=14, fontweight="bold", pad=12)
            ax.set_xlabel("Usage Share (%)", fontsize=11)
            ax.set_ylabel("Country ISO Code", fontsize=11)
            plt.tight_layout()
            
            img_path = artifacts_dir / "opencode_geo_distribution.png"
            plt.savefig(img_path, dpi=300)
            plt.close()
            print(f"Generated chart: {img_path}")

if __name__ == "__main__":
    generate_charts_and_tables()
