from dataclasses import dataclass
from typing import Optional


@dataclass
class TrendingRepo:
    """Represents a GitHub repository extracted from the trending page."""
    
    # Core Metadata (Required by project standards)
    dataset_id: str           # github_trending_{daily,weekly,monthly}
    source_url: str           # The URL scraped
    source_run_id: str        # ID for the scrape run
    scraped_at: str           # ISO timestamp

    # Data Fields
    scrape_date: str          # YYYY-MM-DD
    period: str               # daily, weekly, monthly
    author: str               # Repo owner
    name: str                 # Repo name
    link: str                 # Full GitHub URL
    description: Optional[str] # Repo description (if any)
    stars_today: int          # Stars gained in the current period
    total_stars: int          # Total overall stars
