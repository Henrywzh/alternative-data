import argparse
import logging
import sys

from .pipeline import GithubTrendingPipeline

def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)]
    )

def main():
    parser = argparse.ArgumentParser(description="Fetch GitHub trending repositories")
    parser.add_argument(
        '--period',
        choices=['daily', 'weekly', 'monthly', 'all'],
        default='all',
        help="The time period for trending data to fetch (default: all)"
    )
    parser.add_argument(
        '--data-dir',
        default='data',
        help="Base directory for data storage (default: ./data)"
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help="Enable debug logging"
    )

    args = parser.parse_args()
    setup_logging(level=logging.DEBUG if args.debug else logging.INFO)
    
    pipeline = GithubTrendingPipeline(data_dir=args.data_dir)
    
    periods = ['daily', 'weekly', 'monthly'] if args.period == 'all' else [args.period]
    pipeline.run(periods)

if __name__ == '__main__':
    main()
