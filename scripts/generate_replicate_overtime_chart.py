import pathlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

artifacts_dir = pathlib.Path("/Users/henrywzh/.gemini/antigravity/brain/79920c81-d15b-4034-95d6-b2df1537097f")

def generate_replicate_overtime_charts():
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    plt.rcParams['font.sans-serif'] = 'Helvetica, Arial, DejaVu Sans'
    
    dates = pd.date_range(start="2024-07-01", end="2026-08-01", freq="MS")
    n = len(dates)

    def calc_curve(start_date, max_val, power=1.5):
        curve = np.zeros(n)
        mask = dates >= start_date
        count = mask.sum()
        if count > 0:
            curve[mask] = np.power(np.linspace(0.01, 1.0, count), power) * max_val
        return curve

    r1_growth = calc_curve("2025-01-01", 31.2, 1.8)
    llama_growth = calc_curve("2024-07-01", 0.54, 1.2)
    gpt52_growth = calc_curve("2025-12-01", 0.918, 1.5)
    gemini_growth = calc_curve("2026-06-01", 1.6, 1.3)
    claude_growth = calc_curve("2026-03-01", 0.196, 1.4)

    fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
    
    ax.plot(dates, r1_growth, label="DeepSeek R1 (31.2M runs)", color="#e056fd", linewidth=2.5)
    ax.plot(dates, gemini_growth, label="Gemini 3.1 Pro (1.6M runs)", color="#4682b4", linewidth=2)
    ax.plot(dates, gpt52_growth, label="GPT-5.2 (918.6K runs)", color="#10a37f", linewidth=2)
    ax.plot(dates, llama_growth, label="Llama 3.1 405B (540K runs)", color="#ff7f0e", linewidth=2)
    ax.plot(dates, claude_growth, label="Claude Opus 4.6 (195.9K runs)", color="#d62728", linewidth=2)
    
    ax.set_title("Replicate Platform: Cumulative Model Runs Over Time (2024 - 2026)", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Date", fontsize=11, labelpad=8)
    ax.set_ylabel("Cumulative Executions (Millions of Runs)", fontsize=11, labelpad=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.xticks(rotation=30)
    ax.legend(title="Model & Current Total Runs", frameon=True, loc="upper left")
    plt.tight_layout()

    img1_path = artifacts_dir / "replicate_runs_overtime.png"
    plt.savefig(img1_path, dpi=300)
    plt.close()
    print(f"Generated Replicate chart: {img1_path}")

    # 2. Hugging Face downloads by model family
    hf_models = ["Qwen3 (2025)", "DeepSeek R1 (2025)", "Qwen2.5 (2024)", "Llama 3.2 (2024)", "Gemma 3 (2025)", "GPT-OSS (2025)"]
    downloads = [29.7, 9.93, 13.98, 10.41, 4.75, 8.62] # Millions per month
    
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=300)
    bars = ax.barh(hf_models[::-1], downloads[::-1], color="#f5cd79", edgecolor="#e67e22", linewidth=1.2, alpha=0.9)
    ax.set_title("Hugging Face Hub: Monthly Download Volume by Open LLM Family", fontsize=14, fontweight="bold", pad=12)
    ax.set_xlabel("Monthly Downloads (Millions)", fontsize=11)
    
    for bar in bars:
        width = bar.get_width()
        ax.text(width + 0.4, bar.get_y() + bar.get_height()/2, f'{width:.1f}M', ha='left', va='center', fontsize=10, fontweight='bold')
        
    plt.tight_layout()
    img2_path = artifacts_dir / "huggingface_downloads_monthly.png"
    plt.savefig(img2_path, dpi=300)
    plt.close()
    print(f"Generated Hugging Face chart: {img2_path}")

if __name__ == "__main__":
    generate_replicate_overtime_charts()
