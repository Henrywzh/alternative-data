import sys
import os
import pandas as pd
import re

sys.path.append(os.getcwd())
from dashboard.app import compute_openrouter_views
from dashboard.data import load_all_datasets

print("Loading datasets...")
datasets = load_all_datasets()
views = compute_openrouter_views(datasets)
rev_data = views["revenue_estimator"]

print(f"Total Revenue: {rev_data['total_revenue']}")
print(f"Merged Count: {rev_data['merged_count']}")
print(f"Pivot Daily nulls:\n{rev_data['pivot_rev_daily'].isnull().sum()}")

# To see why if it's 0:
act = datasets.get("app_usage_daily").frame
print(f"Activity total_tokens sum: {act['total_tokens'].sum()}")
print(f"Activity total_tokens dtype: {act['total_tokens'].dtype}")
