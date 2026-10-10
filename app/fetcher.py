"""Auto-fetches a listing's photo gallery with Playwright.

Known sites use a gallery-extraction strategy from site_selectors.py; anything
else falls back to a full-page screenshot so there's still some visual signal
for Photo findings.
"""
import json
import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from site_selectors import SITE_SELECTORS

logger = logging.getLogger(__name__)

NAV_TIMEOUT_MS = 20_000
DEFAULT_MAX_PHOTOS = 10
CHROMIUM_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


def _site_config(url: str) -> Optional[dict]:
    host = (urlparse(url).hostname or "").lower()
    for domain, config in SITE_SELECTORS.items():
        if host == domain or host.endswith("." + domain):
            return config
    return None


async def fetch_gallery(url: str, cwd: Path, max_photos: int = DEFAULT_MAX_PHOTOS) -> List[str]:
    """Downloads up to max_photos gallery images into cwd, or saves a
    full-page screenshot as a fallback. Returns the saved filenames, in the
    order they should be read, or [] if nothing could be captured."""
    cwd.mkdir(parents=True, exist_ok=True)
    config = _site_config(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=CHROMIUM_ARGS)
        try:
            page = await browser.new_page()
            await page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")

            if config:
                image_urls = await _extract_image_urls(page, config, max_photos)
                if image_urls:
                    filenames = await _download_images(page, image_urls, cwd)
                    if filenames:
                        return filenames
                logger.info("no gallery images found for %s, falling back to screenshot", url)

            screenshot_path = cwd / "fallback_screenshot.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            return [screenshot_path.name]
        finally:
            await browser.close()


async def _extract_image_urls(page, config: dict, max_photos: int) -> List[str]:
    strategy = config.get("strategy", "css")
    if strategy == "jsonld":
        urls = await _extract_jsonld_images(page)
    else:
        urls = await _extract_css_images(page, config)
    return urls[:max_photos]


async def _extract_jsonld_images(page) -> List[str]:
    scripts = await page.locator('script[type="application/ld+json"]').all_inner_texts()
    for text in scripts:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        for node in _flatten_jsonld(data):
            image = node.get("image")
            urls = _coerce_image_urls(image)
            if urls:
                return urls
    return []


def _flatten_jsonld(data):
    if isinstance(data, list):
        for item in data:
            yield from _flatten_jsonld(item)
    elif isinstance(data, dict):
        yield data
        for value in data.get("@graph", []):
            yield from _flatten_jsonld(value)


def _coerce_image_urls(image) -> List[str]:
    if isinstance(image, str):
        return [image] if image.startswith("http") else []
    if isinstance(image, list):
        return [u for u in image if isinstance(u, str) and u.startswith("http")]
    if isinstance(image, dict) and isinstance(image.get("url"), str):
        return [image["url"]]
    return []


async def _extract_css_images(page, config: dict) -> List[str]:
    elements = await page.query_selector_all(config["image_selector"])
    seen = set()
    urls = []
    for el in elements:
        value = await el.get_attribute(config["attr"])
        if not value or value in seen:
            continue
        seen.add(value)
        urls.append(config.get("upgrade", lambda u: u)(value))
    return urls


async def _download_images(page, image_urls: List[str], cwd: Path) -> List[str]:
    filenames = []
    for i, image_url in enumerate(image_urls, start=1):
        try:
            response = await page.context.request.get(image_url)
        except Exception:
            logger.exception("gallery image request failed: %s", image_url)
            continue
        if not response.ok:
            logger.warning("gallery image fetch failed (%s): %s", response.status, image_url)
            continue
        filename = f"gallery_{i:02d}.jpg"
        (cwd / filename).write_bytes(await response.body())
        filenames.append(filename)
    return filenames
