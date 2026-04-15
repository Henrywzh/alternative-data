import pandas as pd
import sys
from pathlib import Path

# Add repo root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dashboard.app import compute_compute_availability_views, DatasetLoadResult

def test_views():
    # Mock datasets
    mock_datasets = {
        "raw_aws_spot_price_history": DatasetLoadResult(
            dataset_id="raw_aws_spot_price_history",
            label="AWS Spot Pricing",
            domain="compute_availability",
            primary_date_column="price_timestamp",
            metric_column="spot_price",
            frame=pd.DataFrame({
                "price_timestamp": ["2026-04-15T22:00:00Z"],
                "instance_type": ["p5.48xlarge"],
                "spot_price": [10.0],
                "availability_zone": ["us-east-1a"]
            }),
            source_format="csv",
            source_path=Path("dummy.csv"),
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-04-15T22:00:00Z",
            latest_date="2026-04-15T22:00:00Z",
            latest_scraped_at="2026-04-15T22:00:00Z",
            row_count=1
        ),
        "raw_lambda_instance_types": DatasetLoadResult(
            dataset_id="raw_lambda_instance_types",
            label="Lambda GPU Stock",
            domain="compute_availability",
            primary_date_column="snapshot_ts",
            metric_column="gpu_count",
            frame=pd.DataFrame({
                "snapshot_ts": ["2026-04-15T22:00:00Z"],
                "instance_type_name": ["gpu_8x_h100"],
                "gpu_count": [8],
                "region": ["us-east-1"]
            }),
            source_format="csv",
            source_path=Path("dummy.csv"),
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-04-15T22:00:00Z",
            latest_date="2026-04-15T22:00:00Z",
            latest_scraped_at="2026-04-15T22:00:00Z",
            row_count=1
        ),
        "raw_openrouter_models": DatasetLoadResult(
            dataset_id="raw_openrouter_models",
            label="OpenRouter Catalog",
            domain="compute_availability",
            primary_date_column="snapshot_ts",
            metric_column="pricing_prompt",
            frame=pd.DataFrame({
                "snapshot_ts": ["2026-04-15T22:00:00Z"],
                "model_id": ["openai/gpt-4"],
                "pricing_prompt": [0.00003],
                "context_length": [128000]
            }),
            source_format="csv",
            source_path=Path("dummy.csv"),
            missing_columns=[],
            duplicate_rows=0,
            first_date="2026-04-15T22:00:00Z",
            latest_date="2026-04-15T22:00:00Z",
            latest_scraped_at="2026-04-15T22:00:00Z",
            row_count=1
        )
    }
    
    print("Testing compute_compute_availability_views...")
    views = compute_compute_availability_views(mock_datasets)
    print("Views generated successfully!")
    for k, v in views.items():
        if isinstance(v, pd.DataFrame):
            print(f"  {k}: {len(v)} rows")
        else:
            print(f"  {k}: {type(v)}")

if __name__ == "__main__":
    try:
        test_views()
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
