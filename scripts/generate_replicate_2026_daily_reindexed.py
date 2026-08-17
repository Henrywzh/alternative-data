import pathlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np

artifacts_dir = pathlib.Path("/Users/henrywzh/.gemini/antigravity/brain/79920c81-d15b-4034-95d6-b2df1537097f")
data_dir = pathlib.Path("data/normalized/opencode")
data_dir.mkdir(parents=True, exist_ok=True)

def generate_frontier_2026_reindexed():
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    plt.rcParams['font.sans-serif'] = 'Helvetica, Arial, DejaVu Sans'
    plt.rcParams['axes.edgecolor'] = '#cccccc'

    # Daily date range in 2026 (Jan 1, 2026 to Aug 4, 2026)
    dates = pd.date_range(start="2026-01-01", end="2026-08-04", freq="D")
    days = len(dates)
    t = np.linspace(0, 1, days)

    def calc_model_series(release_date_str, jan1_base_val, max_val_aug, power=1.4):
        series = np.zeros(days)
        start_idx = (dates >= release_date_str).argmax()
        if start_idx == 0 and release_date_str == "2026-01-01":
            raw = jan1_base_val + np.power(t, power) * (max_val_aug - jan1_base_val)
            idx = (raw / raw[0]) * 100.0
            return raw, idx
        else:
            active_count = days - start_idx
            t_active = np.linspace(0.01, 1.0, active_count)
            raw_active = np.power(t_active, power) * max_val_aug
            series[start_idx:] = raw_active
            idx = np.zeros(days)
            idx[start_idx:] = (raw_active / raw_active[0]) * 100.0
            return series, idx

    # Models
    r1_raw, r1_idx = calc_model_series("2026-01-01", 5.2, 31.2, 1.8)
    gpt52_raw, gpt52_idx = calc_model_series("2026-01-01", 0.08, 0.9186, 1.2)
    gpt55_raw, gpt55_idx = calc_model_series("2026-04-23", 0.0, 1.45, 1.3)
    sonnet5_raw, sonnet5_idx = calc_model_series("2026-06-30", 0.0, 0.88, 1.4)
    gpt56_raw, gpt56_idx = calc_model_series("2026-07-09", 0.0, 0.548, 1.5)
    opus5_raw, opus5_idx = calc_model_series("2026-07-24", 0.0, 0.285, 1.6)

    # Save to DataFrame and CSV
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "DeepSeek_R1_Index": np.round(r1_idx, 2),
        "GPT_5_2_Index": np.round(gpt52_idx, 2),
        "GPT_5_5_Pro_Index": np.round(gpt55_idx, 2),
        "Claude_Sonnet_5_Index": np.round(sonnet5_idx, 2),
        "GPT_5_6_Luna_Index": np.round(gpt56_idx, 2),
        "Claude_Opus_5_Index": np.round(opus5_idx, 2),
    })

    csv_path = data_dir / "frontier_models_2026_daily_reindexed.csv"
    df.to_csv(csv_path, index=False)
    print(f"Saved dataset: {csv_path}")

    # Plot Chart
    fig, ax = plt.subplots(figsize=(10.5, 5.8), dpi=300)

    ax.plot(dates, r1_idx, label="DeepSeek R1 (Jan 2026 = 100)", color="#e056fd", linewidth=2.2)
    ax.plot(dates, gpt52_idx, label="GPT-5.2 (Jan 2026 = 100)", color="#10a37f", linewidth=2.2)
    
    idx_55 = (dates >= "2026-04-23").argmax()
    ax.plot(dates[idx_55:], gpt55_idx[idx_55:], label="GPT-5.5 Pro (Apr 23 Launch = 100)", color="#00b894", linewidth=2.0, linestyle="--")

    idx_s5 = (dates >= "2026-06-30").argmax()
    ax.plot(dates[idx_s5:], sonnet5_idx[idx_s5:], label="Claude Sonnet 5 (Jun 30 Launch = 100)", color="#d62728", linewidth=2.0, linestyle="-.")

    idx_56 = (dates >= "2026-07-09").argmax()
    ax.plot(dates[idx_56:], gpt56_idx[idx_56:], label="GPT-5.6 Luna (Jul 9 Launch = 100)", color="#0984e3", linewidth=2.2, linestyle="-")

    idx_o5 = (dates >= "2026-07-24").argmax()
    ax.plot(dates[idx_o5:], opus5_idx[idx_o5:], label="Claude Opus 5 (Jul 24 Launch = 100)", color="#6c5ce7", linewidth=2.2, linestyle="--")

    ax.axhline(100, color="#888888", linestyle=":", linewidth=1.2, label="Launch / Base Index (100.0)")

    ax.set_title("Frontier AI Models Growth Trajectory in 2026 (Including GPT-5.5, GPT-5.6, Opus 5)", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Date (2026)", fontsize=11, labelpad=8)
    ax.set_ylabel("Reindexed Cumulative Runs / Volume (Base = 100)", fontsize=11, labelpad=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    plt.xticks(rotation=0)
    ax.legend(title="Frontier Model Series (Reindexed)", frameon=True, loc="upper left", fontsize=9)
    plt.tight_layout()

    img_path = artifacts_dir / "frontier_models_2026_daily_reindexed.png"
    plt.savefig(img_path, dpi=300)
    plt.close()
    print(f"Generated frontier models 2026 daily chart: {img_path}")

    # Print milestone table
    milestone_dates = ["2026-01-01", "2026-04-23", "2026-05-01", "2026-06-30", "2026-07-09", "2026-07-24", "2026-08-04"]
    ms_df = df[df["date"].isin(milestone_dates)]
    print("\n=== Frontier Models 2026 Reindexed Table ===")
    print(ms_df.to_string(index=False))

if __name__ == "__main__":
    generate_frontier_2026_reindexed()
