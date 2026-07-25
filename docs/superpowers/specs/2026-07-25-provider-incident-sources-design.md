# Moonshot AI and MiniMax Incident Sources

## Goal

Extend the provider incident tracker with two verified, official status feeds: Moonshot AI (Kimi) and MiniMax.

## Scope

- Add Moonshot AI using its Atlassian Statuspage incidents API:
  `https://status.moonshot.cn/api/v2/incidents.json`.
- Add MiniMax using its Atlassian Statuspage incidents API:
  `https://status.minimax.io/api/v2/incidents.json`.
- Reuse the existing `statuspage` parser, source-health checks, storage keys, and dashboard controls.
- Update dashboard copy from eight to ten official provider feeds.
- Add regression coverage for source registration and successful Statuspage extraction.
- Keep Z.ai out of the registry until an official, reachable status endpoint is verified.

## Data and reliability rules

- The two new feeds are polled on the existing two-hour provider-incidents schedule.
- Provider IDs are stable slugs: `moonshot` and `minimax`.
- Display names are `Moonshot AI (Kimi)` and `MiniMax`.
- A source failure is recorded in source health and does not erase historical incidents.
- The existing majority-source guard remains unchanged.

## UI

The provider selector and coverage table should discover the new providers from the normalized data automatically. The section subtitle will state that it covers ten official public status feeds after the additions.

## Verification

- Unit tests must confirm both source specifications use the Statuspage parser and expected URLs.
- Fixture-based extraction must confirm the common parser produces incident rows and updates for both providers.
- Run the provider incident tests plus the dashboard smoke tests.
- Run one live, read-only fetch/extraction check against both official endpoints before completion.
