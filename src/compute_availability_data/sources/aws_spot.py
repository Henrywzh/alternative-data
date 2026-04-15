from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from compute_availability_data.models import DatasetRecord, Snapshot


class AwsSpotSource:
    DEFAULT_REGIONS = ["us-east-1", "us-east-2", "us-west-2"]
    WATCHLIST = [
        "p5.48xlarge",
        "p5e.48xlarge",
        "p5en.48xlarge",
        "p6-b200.48xlarge",
    ]

    def fetch_snapshots(self, regions: list[str] | None = None) -> list[Snapshot]:
        regions = regions or self.DEFAULT_REGIONS
        snapshots = []
        
        # We'll pull last 24 hours of history
        start_time = datetime.now(timezone.utc) - timedelta(days=1)
        
        for region in regions:
            try:
                ec2 = boto3.client("ec2", region_name=region)
                response = ec2.describe_spot_price_history(
                    InstanceTypes=self.WATCHLIST,
                    ProductDescriptions=["Linux/UNIX", "Linux/UNIX (Amazon VPC)"],
                    StartTime=start_time,
                )
                
                # Convert datetime objects to strings for JSON serialization
                serializable_response = self._make_serializable(response)
                
                snapshots.append(
                    Snapshot(
                        name=f"aws_spot_history_{region}",
                        source_url=f"aws-ec2://{region}/DescribeSpotPriceHistory",
                        body=json.dumps(serializable_response, indent=2),
                    )
                )
            except (BotoCoreError, ClientError) as e:
                # Log error in body or skip
                snapshots.append(
                    Snapshot(
                        name=f"aws_spot_history_{region}_error",
                        source_url=f"aws-ec2://{region}/DescribeSpotPriceHistory",
                        body=json.dumps({"error": str(e)}),
                    )
                )
        return snapshots

    def extract(self, snapshots: list[Snapshot], run_id: str, scraped_at: str) -> list[DatasetRecord]:
        records = []
        for snapshot in snapshots:
            if snapshot.name.endswith("_error"):
                continue
                
            data = json.loads(snapshot.body)
            history = data.get("SpotPriceHistory", [])
            region = snapshot.name.replace("aws_spot_history_", "")
            
            for entry in history:
                records.append(
                    DatasetRecord(
                        dataset_id="raw_aws_spot_price_history",
                        source_url=snapshot.source_url,
                        source_run_id=run_id,
                        scraped_at=scraped_at,
                        snapshot_ts=scraped_at,
                        region=region,
                        availability_zone=entry.get("AvailabilityZone"),
                        instance_type=entry.get("InstanceType"),
                        product_description=entry.get("ProductDescription"),
                        spot_price=float(entry.get("SpotPrice")) if entry.get("SpotPrice") else None,
                        price_timestamp=entry.get("Timestamp"),
                    )
                )
        return records

    @staticmethod
    def _make_serializable(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: AwsSpotSource._make_serializable(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [AwsSpotSource._make_serializable(i) for i in obj]
        return obj
