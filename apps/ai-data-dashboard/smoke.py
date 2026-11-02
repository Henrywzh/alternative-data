"""Open every page and subtab of a built dist/ in headless Chromium.

A view fails if it throws, logs a console error, shows NaN/undefined/Infinity,
or leaves a visible chart without a canvas. Exits non-zero on any failure, so
the deploy workflow publishes only a site that rendered cleanly. Run after
build.py:

    python apps/ai-data-dashboard/smoke.py [--dist apps/ai-data-dashboard/dist]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import threading
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

PAGES = ["openrouter", "ramp", "semis", "downloads", "gpu"]
BAD_TEXT = ("NaN", "undefined", "Infinity")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def serve(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def check_view(page, url: str) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(f"exception: {exc}"))
    page.on("console", lambda msg: errors.append(f"console: {msg.text}") if msg.type == "error" else None)
    try:
        # Not "networkidle": the CDN's analytics can keep the network busy.
        page.goto(url, wait_until="load", timeout=60_000)
        page.wait_for_function("() => document.querySelector('.stat, .lede, table, canvas')", timeout=30_000)
    except PlaywrightError as exc:
        return errors + [f"did not load: {str(exc).splitlines()[0]}"]
    page.wait_for_timeout(800)
    text = page.inner_text("main") if page.query_selector("main") else page.inner_text("body")
    errors += [f"shows {word}" for word in BAD_TEXT if f" {word}" in f" {text}" or f"{word}%" in text]
    # A chart with no canvas never drew: ECharts adds one on init.
    blank = page.eval_on_selector_all(
        ".view.on .chart, body:not(:has(.view)) .chart",
        "nodes => nodes.filter(n => n.offsetParent !== null && !n.querySelector('canvas')).map(n => n.id)",
    )
    errors += [f"chart #{name} did not render" for name in blank]
    if not text.strip():
        errors.append("rendered nothing")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path(__file__).resolve().parent / "dist")
    args = parser.parse_args()
    server, base = serve(args.dist)
    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name in PAGES:
            probe = browser.new_page()
            probe.goto(f"{base}/{name}/", wait_until="load", timeout=60_000)
            views = probe.eval_on_selector_all(".subtab[data-view]", "nodes => nodes.map(n => n.dataset.view)") or [""]
            probe.close()
            for view in views:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                url = f"{base}/{name}/" + (f"#{view}" if view else "")
                problems = check_view(page, url)
                page.close()
                failures += bool(problems)
                print(f"{'FAIL' if problems else 'ok  '} {name}/{('#' + view) if view else ''}")
                for problem in problems:
                    print(f"     {problem}")
        browser.close()
    server.shutdown()
    if failures:
        raise SystemExit(f"{failures} view(s) failed")


if __name__ == "__main__":
    main()
