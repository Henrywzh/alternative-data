import requests
from bs4 import BeautifulSoup
from datetime import datetime
import logging
from typing import List, Optional

from .models import TrendingRepo

logger = logging.getLogger(__name__)

class GithubTrendingScraper:
    BASE_URL = "https://github.com/trending"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        })
        
    def _parse_int(self, text: str) -> int:
        """Parses an integer from a string, removing commas and text."""
        import re
        if not text:
            return 0
        cleaned = re.sub(r'[^\d]', '', text)
        return int(cleaned) if cleaned else 0

    def scrape(self, period: str, run_id: Optional[str] = None) -> List[TrendingRepo]:
        """
        Scrapes GitHub trending repositories for a given period.
        
        Args:
            period: 'daily', 'weekly', or 'monthly'
            run_id: Optional run ID to use for core metadata
        """
        if period not in ['daily', 'weekly', 'monthly']:
            raise ValueError(f"Invalid period: {period}")
            
        url = f"{self.BASE_URL}?since={period}"
        logger.info(f"Fetching {url}")
        
        response = self.session.get(url, timeout=15)
        response.raise_for_status()
        
        now = datetime.now()
        scrape_date = now.strftime("%Y-%m-%d")
        scraped_at = now.isoformat().replace("+00:00", "Z")
        
        # Use provided run_id or generate a simple one based on timestamp
        source_run_id = run_id or now.strftime("%Y%m%dT%H%M%S")
        dataset_id = f"github_trending_{period}"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.find_all('article', class_='Box-row')
        
        results = []
        for article in articles:
            # ... (parsing logic remains same) ...
            h2 = article.find('h2', class_='h3 lh-condensed')
            if not h2:
                continue
                
            a_tag = h2.find('a')
            if not a_tag:
                continue
                
            link = f"https://github.com{a_tag['href']}"
            parts = a_tag.text.strip().split('/')
            author = parts[0].strip()
            name = parts[1].strip() if len(parts) > 1 else ""
            
            p_desc = article.find('p', class_='col-9')
            description = p_desc.text.strip() if p_desc else None
            
            stars_today = 0
            span_stars = article.find('span', class_='d-inline-block float-sm-right')
            if span_stars:
                stars_today = self._parse_int(span_stars.text)
                
            total_stars = 0
            a_star = article.find('a', href=lambda h: h and h.endswith('/stargazers'))
            if a_star:
                total_stars = self._parse_int(a_star.text.strip())
                        
            repo = TrendingRepo(
                dataset_id=dataset_id,
                source_url=url,
                source_run_id=source_run_id,
                scraped_at=scraped_at,
                scrape_date=scrape_date,
                period=period,
                author=author,
                name=name,
                link=link,
                description=description,
                stars_today=stars_today,
                total_stars=total_stars
            )
            results.append(repo)
            
        logger.info(f"Scraped {len(results)} repositories for {period}")
        return results
