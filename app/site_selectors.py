"""Per-site gallery extraction strategies for the Playwright fetcher. Unknown
domains fall back to a full-page screenshot in fetcher.py.

Strategies:
  "jsonld" — read the page's schema.org JSON-LD (<script type="application/
             ld+json">), walk any @graph entries, and take the first "image"
             array found. Confirmed against a real test listing on 2026-10-10:
             maklarhuset.se embeds the full gallery (at full resolution) this
             way — the rendered DOM carousel only ever shows a handful at a
             time, so scraping <img> tags misses most of the gallery.
  "css"    — query_selector_all(selector), read `attr`, pass through
             `upgrade`. Kept for sites without usable JSON-LD.
"""
from typing import Callable, TypedDict


class SiteConfig(TypedDict, total=False):
    strategy: str
    image_selector: str
    attr: str
    upgrade: Callable[[str], str]


SITE_SELECTORS: dict[str, SiteConfig] = {
    "maklarhuset.se": {
        "strategy": "jsonld",
    },
}
