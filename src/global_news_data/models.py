from dataclasses import dataclass, asdict
from typing import Any, Optional
import json

@dataclass
class UnifiedNewsRecord:
    """A standard unified representation of a financial news article or feed item."""
    article_id: str
    source: str                 # 'guardian' | 'marketaux' | 'currents'
    published_at: str           # ISO8601 string
    title: str
    summary: str
    body_text: Optional[str]
    url: str
    entities: str               # JSON-serialized list of entities (e.g., stock tickers, sentiment)
    sentiment_score: Optional[float] # Normalized from -1.0 to 1.0
    language: str
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
