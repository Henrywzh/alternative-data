import sys
import os
import pandas as pd
import re

sys.path.append(os.getcwd())

from dashboard.data import load_all_datasets

def validate_missing_population():
    print("Loading datasets...")
    datasets = load_all_datasets()
    
    activity_res = datasets.get("openrouter_model_activity")
    pricing_res = datasets.get("raw_openrouter_models")
    
    if not activity_res or activity_res.frame.empty:
        print("Error: No activity data.")
        return
    if not pricing_res or pricing_res.frame.empty:
        print("Error: No pricing data.")
        return
        
    activity = activity_res.frame.copy()
    pricing = pricing_res.frame.copy()
    
    latest_pricing = pricing.sort_values("snapshot_ts").groupby("model_id").tail(1)
    pricing_model_ids = set(latest_pricing["model_id"].tolist())
    
    # 1. Exact Match
    exact_matched = activity[activity["model_permaslug"].isin(pricing_model_ids)]
    unmatched = activity[~activity["model_permaslug"].isin(pricing_model_ids)]
    
    print(f"\n--- MATCHING STATS ---")
    print(f"Total Activity Rows: {len(activity)}")
    print(f"Exact Mapped Rows: {len(exact_matched)} ({(len(exact_matched)/len(activity))*100:.1f}%)")
    print(f"Unmatched Rows: {len(unmatched)} ({(len(unmatched)/len(activity))*100:.1f}%)")
    
    print("\n--- TOP UNMATCHED MODELS (by frequency) ---")
    top_unmatched = unmatched["model_permaslug"].value_counts().head(20)
    print(top_unmatched)
    
    # 2. Fuzzy Match Attempt
    print("\n--- FUZZY MATCH EXPERIMENT ---")
    # Base strategy: strip date suffixes (e.g., -20260305)
    def fuzzy_match(slug):
        # Remove trailing date patterns like -YYYYMMDD or just -YYYY
        base_slug = re.sub(r'-\d{4,8}$', '', str(slug))
        # Remove trailing :beta, :free from the check base if necessary, but pricing might have them
        
        # Check against available pricing IDs
        if base_slug in pricing_model_ids:
            return base_slug
            
        # Try to find a pricing model that starts with this base slug if the pricing model implies it
        # Actually a common issue is pricing might have "openai/gpt-4o" but activity has "openai/gpt-4o-20240513"
        # Let's see if stripping date finds a match
        return base_slug

    unmatched = unmatched.copy()
    unmatched["fuzzy_slug"] = unmatched["model_permaslug"].apply(fuzzy_match)
    
    fuzzy_recovered = unmatched[unmatched["fuzzy_slug"].isin(pricing_model_ids)]
    still_unmatched = unmatched[~unmatched["fuzzy_slug"].isin(pricing_model_ids)]
    
    print(f"Recovered Rows via subset stripping: {len(fuzzy_recovered)} ({(len(fuzzy_recovered)/len(unmatched))*100:.1f}% of unmatched)")
    
    if not fuzzy_recovered.empty:
        print("\nTop Recovered:")
        print(fuzzy_recovered[["model_permaslug", "fuzzy_slug"]].drop_duplicates().head(15))
        
    if not still_unmatched.empty:
        print("\nStill Unmatched (Top 10):")
        print(still_unmatched["model_permaslug"].value_counts().head(10))

if __name__ == "__main__":
    validate_missing_population()
