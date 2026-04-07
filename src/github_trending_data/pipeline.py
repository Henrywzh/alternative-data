import logging
from pathlib import Path
from typing import List

from .scraper import GithubTrendingScraper
from .storage import GithubTrendingStorage

logger = logging.getLogger(__name__)

class GithubTrendingPipeline:
    def __init__(self, data_dir: str = "data"):
        self.scraper = GithubTrendingScraper()
        
        # Determine the base directory
        # If running from alternative-data root, it will use that data_dir relative to current working directory
        cwd = Path.cwd()
        base_dir = cwd / data_dir
        self.storage = GithubTrendingStorage(base_dir)

    def run(self, periods: List[str]):
        """
        Runs the extraction pipeline for the given periods.
        """
        has_error = False
        for period in periods:
            try:
                logger.info(f"Starting pipeline for {period} trending repos")
                repos = self.scraper.scrape(period)
                self.storage.save(period, repos)
                logger.info(f"Successfully completed {period} extraction")
            except Exception as e:
                logger.error(f"Error extracting {period} data: {e}", exc_info=True)
                has_error = True
                
        if has_error:
            raise RuntimeError("One or more period extractions failed")
