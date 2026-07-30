import logging
import pandas as pd

logger = logging.getLogger(__name__)

IA_PREMIUM_COLUMNS = ["quarter", "mainland_visitor_premium_mhkd", "share_of_total_new_office_pct"]


def fetch_ia_mainland_visitor_premiums() -> pd.DataFrame:
    """
    Insurance Authority quarterly new business premiums for Mainland Visitors.

    The IA suspended this series: every provisional release since Q1 2025
    states it is "conducting a comprehensive review of the scope and
    criteria concerning data collection on non-local policyholders" and that
    separate Mainland Visitor statistics "will not be published pending
    completion of that exercise" (confirmed live, still current as of the
    most recent release). The last real figure is the FY2024 full-year total
    of HK$62.8 billion (28.6% of new individual office premiums), published
    April 2025 -- not a quarterly breakdown, and IA does not publish a
    machine-readable historical CSV for the pre-suspension quarterly series
    either. There is no real substitute source for this feature (the
    C&SD table sometimes suggested as an alternative, 645-92111, is actually
    "Number of authorized insurers/brokers/agents" -- headcounts of
    licensees, not premiums -- and does not contain this data).

    This is intentionally not shipped as a dashboard feature: rather than
    fabricate a plausible-looking recovering series for quarters that were
    never published (as the previous version of this module did), it
    returns empty. Downstream callers must not backfill this with invented
    numbers.
    """
    logger.warning(
        "IA Mainland Visitor premium statistics are suspended by the regulator "
        "since Q1 2025 (comprehensive review of scope and criteria for non-local "
        "policyholder data); no live quarterly series exists to fetch."
    )
    return pd.DataFrame(columns=IA_PREMIUM_COLUMNS)
