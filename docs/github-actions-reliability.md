# GitHub Actions refresh reliability

The September/October 2026 failures had distinct causes:

- CI used the current date to validate a fixed March 2026 labour-market
  fixture. The fixture crossed its 180-day freshness limit. Those tests now
  pass a fixed reference date; production validation still uses today's date.
- OpenCode changed its leaderboard from user-tier groups to `daily` and
  `weekly` groups. The extractor handles both schemas and retains the empty
  core-dataset guard. The October 2 failed run's raw payload yields 36 valid
  leaderboard rows with the repaired extractor.
- ETF spot fallbacks attempted three of four configured hosts because they
  inherited the primary source's retry budget. Both direct fallbacks now
  attempt every configured host. Incomplete/unavailable quotes still block
  the report. Use the intraday workflow's `diagnostics_only` input for a
  live GitHub-runner probe without sending email.
- PyPIStats HTTP 500 responses were not retried. The source now retries
  429/500/502/503/504 and connection/time-out failures with bounded backoff.
  After exhaustion, an unavailable package is omitted, its retained history
  stays unchanged, and the raw manifest records partial coverage and missing
  packages. An entirely empty update fails without refreshing retained data.
  Independent npm, Hugging Face and GitHub steps still run after a PyPI
  failure. Derived metrics require successful PyPI and GitHub steps. Healthy
  source updates and artifacts are published even when another source fails;
  the overall job retains the failure.

Dashboard artifact publishers share concurrency protection; the provider
adoption publisher also serializes its own scheduled/manual runs and retries
pushes when other data workflows advance the default branch.

A successful PR check does not repair scheduled runs until the code is
integrated into the repository's default branch. Validate both the CI checks
and fresh runs of the affected scheduled workflows after integration.
