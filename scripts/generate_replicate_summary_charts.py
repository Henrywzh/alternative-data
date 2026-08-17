import pathlib
import matplotlib.pyplot as plt
import pandas as pd

artifacts_dir = pathlib.Path("/Users/henrywzh/.gemini/antigravity/brain/79920c81-d15b-4034-95d6-b2df1537097f")
data_dir = pathlib.Path("data/normalized/replicate")

def generate_replicate_summary_visuals():
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    plt.rcParams['font.sans-serif'] = 'Helvetica, Arial, DejaVu Sans'

    # Load normalized datasets
    df_cat = pd.read_csv(data_dir / "replicate_model_catalog.csv")
    df_col = pd.read_csv(data_dir / "replicate_collections_summary.csv")

    # 1. Top Replicate Collections by Model Count
    top_cols = df_col.head(10).iloc[::-1]
    
    fig, ax = plt.subplots(figsize=(9.5, 5), dpi=300)
    bars = ax.barh(top_cols["collection_slug"], top_cols["total_models"], color="#6c5ce7", edgecolor="#4834d4", linewidth=1.2, alpha=0.85)
    ax.set_title("Replicate AI: Model Catalog Breakdown by Collection Category", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Number of Models Hosted", fontsize=11)
    
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 3, bar.get_y() + bar.get_height()/2, f"{int(w)}", ha="left", va="center", fontsize=10, fontweight="bold")

    plt.tight_layout()
    img1_path = artifacts_dir / "replicate_collections_models_count.png"
    plt.savefig(img1_path, dpi=300)
    plt.close()

    # 2. Top Models across all collections by Cumulative Runs
    top_models = df_cat.sort_values(by="run_count", ascending=False).head(12).iloc[::-1]
    top_models["runs_m"] = top_models["run_count"] / 1_000_000.0

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=300)
    bars2 = ax.barh(top_models["slug"], top_models["runs_m"], color="#00b894", edgecolor="#00876c", linewidth=1.2, alpha=0.85)
    ax.set_title("Replicate AI: Top Hosted Models by Cumulative Execution Count (Millions of Runs)", fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel("Cumulative Executions (Millions of Runs)", fontsize=11)

    for bar in bars2:
        w = bar.get_width()
        ax.text(w + 0.3, bar.get_y() + bar.get_height()/2, f"{w:.1f}M", ha="left", va="center", fontsize=9.5, fontweight="bold")

    plt.tight_layout()
    img2_path = artifacts_dir / "replicate_top_models_by_runs.png"
    plt.savefig(img2_path, dpi=300)
    plt.close()

    print(f"Generated Replicate summary charts:\n- {img1_path}\n- {img2_path}")

if __name__ == "__main__":
    generate_replicate_summary_visuals()
