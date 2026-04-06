from dataclasses import dataclass
from typing import Optional


@dataclass
class TrendingRepo:
    """Represents a GitHub repository extracted from the trending page."""
    
    scrape_date: str          # YYYY-MM-DD
    period: str               # daily, weekly, monthly
    author: str               # Repo owner
    name: str                 # Repo name
    link: str                 # Full GitHub URL
    description: Optional[str] # Repo description (if any)
    stars_today: int          # Stars gained in the current period (the label is often "stars today" but matches the period)
    total_stars: int          # Total overall stars
