"""Reusable, read-only UI components for Research Control Tower V1.

The package initializer is the approved Task 6 style boundary; a separate
``styles.py`` is intentionally deferred so the exact plan path contract stays
unchanged.
"""

from __future__ import annotations

import streamlit as st


# Keep all responsive rules in this module.  The CSS namespace is intentionally
# private to the app and uses Streamlit theme variables as fallbacks.
CONTROL_TOWER_CSS = r"""
<style>
:root {
  --ct-bg: var(--background-color, #f6f8fb);
  --ct-surface: var(--secondary-background-color, #ffffff);
  --ct-surface-muted: color-mix(in srgb, var(--ct-surface) 86%, #64748b 14%);
  --ct-ink: var(--text-color, #172033);
  --ct-muted: color-mix(in srgb, var(--ct-ink) 58%, transparent);
  --ct-border: color-mix(in srgb, var(--ct-ink) 16%, transparent);
  --ct-accent: #2563eb;
  --ct-hard: #0f766e;
  --ct-provisional: #b45309;
  --ct-thesis: #7c3aed;
  --ct-observed: #2563eb;
  --ct-warning: #b45309;
  --ct-danger: #b91c1c;
  --ct-radius: 14px;
}
.ct-shell { max-width: 1480px; margin: 0 auto; padding-bottom: 3rem; }
.ct-eyebrow { color: var(--ct-muted); font-size: .72rem; letter-spacing: .12em;
  text-transform: uppercase; font-weight: 700; margin: 0 0 .35rem; }
.ct-subtle { color: var(--ct-muted); font-size: .82rem; }
.ct-flight-deck { display: grid; grid-template-columns: 1.25fr .75fr .9fr .9fr 1.8fr;
  gap: 1px; border: 1px solid var(--ct-border); border-radius: var(--ct-radius);
  overflow: hidden; background: var(--ct-border); margin: .75rem 0 1.25rem; }
.ct-flight-slot { background: var(--ct-surface); padding: .9rem 1rem; min-width: 0; }
.ct-flight-slot--catalyst { background: color-mix(in srgb, var(--ct-accent) 7%, var(--ct-surface)); }
.ct-metric-label { color: var(--ct-muted); font-size: .72rem; text-transform: uppercase;
  letter-spacing: .08em; font-weight: 700; }
.ct-metric-value { color: var(--ct-ink); font-size: 1.05rem; line-height: 1.25;
  font-weight: 750; margin-top: .25rem; overflow-wrap: anywhere; }
.ct-metric-detail { color: var(--ct-muted); font-size: .77rem; line-height: 1.35;
  margin-top: .28rem; overflow-wrap: anywhere; }
.ct-layout { display: grid; gap: 1.1rem; }
.ct-today-layout { grid-template-columns: minmax(0, 1.9fr) minmax(260px, .9fr); }
.ct-timeline-layout { grid-template-columns: minmax(260px, .8fr) minmax(0, 1.8fr); }
.ct-panel { background: var(--ct-surface); border: 1px solid var(--ct-border);
  border-radius: var(--ct-radius); padding: 1rem 1.05rem; min-width: 0; }
.ct-panel h3 { margin: 0 0 .75rem; font-size: 1rem; }
.ct-panel-heading { display: flex; align-items: baseline; justify-content: space-between;
  gap: .7rem; margin-bottom: .7rem; }
.ct-panel-heading h3 { margin: 0; }
.ct-count { color: var(--ct-muted); font-size: .76rem; white-space: nowrap; }
.ct-event-list { display: grid; gap: .65rem; }
.ct-event-row { display: grid; grid-template-columns: 104px minmax(0, 1fr) 250px;
  gap: .9rem; border: 1px solid var(--ct-border); border-left: 3px solid var(--ct-border);
  border-radius: 11px; padding: .78rem .85rem; background: var(--ct-surface); min-width: 0; }
.ct-event-row--hard { border-left-color: var(--ct-hard); }
.ct-event-row--provisional { border-left: 3px dashed var(--ct-provisional); }
.ct-event-row--thesis_checkpoint { border-left: 3px dashed var(--ct-thesis); }
.ct-event-row--observed { border-left-color: var(--ct-observed); }
.ct-event-date { color: var(--ct-ink); font-size: .86rem; font-weight: 750; }
.ct-t-minus { color: var(--ct-accent); font-size: .78rem; font-weight: 750; margin-top: .22rem; }
.ct-event-title { color: var(--ct-ink); font-size: .94rem; font-weight: 750; line-height: 1.32;
  overflow-wrap: anywhere; }
.ct-event-description { color: var(--ct-muted); font-size: .82rem; line-height: 1.42;
  margin-top: .25rem; overflow-wrap: anywhere; }
.ct-event-meta { color: var(--ct-muted); font-size: .75rem; line-height: 1.45;
  min-width: 0; overflow-wrap: anywhere; }
.ct-badges, .ct-chips { display: flex; flex-wrap: wrap; gap: .33rem; margin-top: .48rem; }
.ct-badge, .ct-chip { display: inline-flex; align-items: center; max-width: 100%;
  border: 1px solid var(--ct-border); border-radius: 999px; padding: .18rem .48rem;
  font-size: .69rem; line-height: 1.25; overflow-wrap: anywhere; }
.ct-badge--hard { color: var(--ct-hard); border-color: color-mix(in srgb, var(--ct-hard) 45%, var(--ct-border)); }
.ct-badge--provisional { color: var(--ct-provisional); border-style: dashed; }
.ct-badge--thesis_checkpoint { color: var(--ct-thesis); border-style: dashed; }
.ct-badge--observed { color: var(--ct-observed); }
.ct-badge--warning { color: var(--ct-warning); border-color: color-mix(in srgb, var(--ct-warning) 45%, var(--ct-border)); }
.ct-chip { background: var(--ct-surface-muted); color: var(--ct-ink); }
.ct-source-line { color: var(--ct-muted); font-size: .74rem; line-height: 1.4; margin-top: .36rem; }
.ct-source-line a { color: var(--ct-accent); text-decoration: none; }
.ct-source-line a:hover, .ct-source-line a:focus { text-decoration: underline; }
.ct-watch { border-top: 1px solid var(--ct-border); margin-top: .65rem; padding-top: .55rem; }
.ct-watch summary { color: var(--ct-ink); cursor: pointer; font-size: .78rem; font-weight: 700; }
.ct-watch ul { color: var(--ct-muted); margin: .45rem 0 0 1.1rem; padding: 0; font-size: .78rem; }
.ct-watch li { margin: .2rem 0; overflow-wrap: anywhere; }
.ct-change-list { display: grid; gap: .55rem; }
.ct-change { border-bottom: 1px solid var(--ct-border); padding: .6rem 0; }
.ct-change:last-child { border-bottom: 0; padding-bottom: 0; }
.ct-change-title { color: var(--ct-ink); font-size: .88rem; font-weight: 700; overflow-wrap: anywhere; }
.ct-change-detail { color: var(--ct-muted); font-size: .77rem; line-height: 1.4; margin-top: .18rem; }
.ct-alert-strip { border: 1px solid color-mix(in srgb, var(--ct-warning) 45%, var(--ct-border));
  background: color-mix(in srgb, var(--ct-warning) 8%, var(--ct-surface));
  color: var(--ct-ink); border-radius: 10px; padding: .65rem .75rem; font-size: .78rem;
  line-height: 1.4; margin-top: .75rem; overflow-wrap: anywhere; }
.ct-empty { border: 1px dashed var(--ct-border); border-radius: 10px; color: var(--ct-muted);
  padding: .8rem; font-size: .82rem; }
.ct-timeline-month { color: var(--ct-ink); font-size: 1rem; font-weight: 760; margin: .25rem 0 .55rem; }
.ct-timeline-month:not(:first-child) { margin-top: 1.25rem; }
.ct-catalyst-rail { align-self: start; }
.ct-catalyst-card { border: 1px solid color-mix(in srgb, var(--ct-accent) 32%, var(--ct-border));
  border-radius: var(--ct-radius); background: color-mix(in srgb, var(--ct-accent) 6%, var(--ct-surface));
  padding: .95rem; }
.ct-catalyst-card .ct-event-title { font-size: 1rem; }
.ct-section-spacer { height: .9rem; }
.ct-inline-link { color: var(--ct-accent); text-decoration: none; }
.ct-inline-link:hover, .ct-inline-link:focus { text-decoration: underline; }
@media (max-width: 1199px) {
  .ct-flight-deck { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ct-flight-slot--catalyst { grid-column: 1 / -1; }
  .ct-today-layout, .ct-timeline-layout { grid-template-columns: 1fr; }
  .ct-catalyst-rail { order: -1; }
  .ct-event-row { grid-template-columns: 104px minmax(0, 1fr); }
  .ct-event-meta { grid-column: 2; }
}
@media (max-width: 759px) {
  .ct-flight-deck { grid-template-columns: 1fr; }
  .ct-flight-slot--catalyst { grid-column: auto; }
  .ct-event-row { grid-template-columns: 1fr; gap: .42rem; }
  .ct-event-meta { grid-column: auto; }
  .ct-panel { padding: .82rem .78rem; }
  .ct-shell { padding-bottom: 2rem; }
}
</style>
"""


def inject_styles() -> None:
    """Inject the static stylesheet into the current Streamlit run."""

    st.markdown(CONTROL_TOWER_CSS, unsafe_allow_html=True)


__all__ = ["CONTROL_TOWER_CSS", "inject_styles"]
