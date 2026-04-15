import sys
from pathlib import Path
import pandas as pd

# Add project root to path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from dashboard.data import load_dataset, dataset_ids

def test_loading():
    print(f"Dataset IDs in registry: {dataset_ids()}")
    
    target_ds = "semiconductor_memory_regime_monthly"
    if target_ds not in dataset_ids():
        print(f"ERROR: {target_ds} not found in registry")
        return

    result = load_dataset(target_ds)
    print(f"Label: {result.label}")
    print(f"Domain: {result.domain}")
    print(f"Row count: {result.row_count}")
    print(f"Columns: {result.frame.columns.tolist()[:10]}...")
    
    if result.row_count > 0:
        print("Data loading: SUCCESS")
    else:
        print("Data loading: FAILED or EMPTY")

    img_ds = "adata_marketwatch_images"
    result_img = load_dataset(img_ds)
    print(f"\n{img_ds} count: {result_img.row_count}")

if __name__ == "__main__":
    test_loading()
