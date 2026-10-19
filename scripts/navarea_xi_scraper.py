#!/usr/bin/env python3
"""
navarea_xi_scraper.py — Japan Coast Guard NAVAREA XI Scraper
Automates human-mimicking browser navigation with Bézier mouse movements,
random 30s–40s dwell times, and "All Display" interaction on kaiho.mlit.go.jp.
"""

import sys
import os
import re
import math
import random
import asyncio
from datetime import datetime

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Optional browser automation via Playwright
try:
    from playwright.async_api import async_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

# HTTP fallback libraries
try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    try:
        import requests as cffi_requests
        HAS_CURL_CFFI = False
    except ImportError:
        cffi_requests = None
        HAS_CURL_CFFI = False

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

URL_PORTAL = "https://www1.kaiho.mlit.go.jp/TUHO/keiho/navarea11_en.html"
URL_DISP = "https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/disp_warnings.cgi"
JCG_ENCODING = "cp932"


def _collect_from_text_lines(blocks):
    collected = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        block = re.sub(r'<.*?>', '', block)
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        id_match = re.search(r'(NO\.\d{2}-\d{4})', lines[0])
        if not id_match:
            continue
        wid = id_match.group(1)
        header = f"NAVAREA XI {wid}"
        body = "\n".join(lines[1:]).strip()
        collected[header] = {"header": header, "date_line": lines[0], "body": body}
    return collected


def _parse_html_warnings(html_content: str) -> dict:
    if not html_content:
        return {}
    html = re.sub(r'<br\s*/?>', '\n', html_content, flags=re.IGNORECASE)
    html = re.sub(r'</?STRONG>', '', html, flags=re.IGNORECASE)
    blocks = re.split(r'<hr\s*/?>', html, flags=re.IGNORECASE)
    return _collect_from_text_lines(blocks)


def _write_output(collected, output_filename):
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with open(output_filename, "w", encoding="utf-8") as f:
        for warn in collected.values():
            f.write(f"--- {warn['header']} ---\n{warn['date_line']}\n{warn['body']}\n\n")


async def _human_mouse_move(page, start_x: float, start_y: float, target_x: float, target_y: float, steps: int = 25):
    """
    Simulates human-like mouse movement using a quadratic Bézier curve
    with random control points and micro-sleep jitter.
    """
    # Control point for natural curve
    cx = (start_x + target_x) / 2.0 + random.uniform(-60.0, 60.0)
    cy = (start_y + target_y) / 2.0 + random.uniform(-60.0, 60.0)

    for i in range(1, steps + 1):
        t = i / float(steps)
        # Quadratic Bézier: B(t) = (1-t)^2 * P0 + 2(1-t)t * P1 + t^2 * P2
        x = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * cx + (t ** 2) * target_x
        y = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * cy + (t ** 2) * target_y
        await page.mouse.move(x, y)
        await asyncio.sleep(random.uniform(0.008, 0.025))


async def fetch_via_browser(year=None) -> dict:
    """
    Visits navarea11_en.html, simulates human browsing with curved cursor paths,
    waits 30s-40s random delay, clicks 'All Display', and extracts warnings from disp_warnings.cgi.
    """
    if not HAS_PLAYWRIGHT:
        print("ℹ️ Playwright library not installed in environment; skipping browser automation.")
        return {}

    current_year = year or datetime.now().year
    print(f"🌐 Launching Chromium browser (target year: {current_year})...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            print(f"👉 1. Visiting {URL_PORTAL}...")
            await page.goto(URL_PORTAL, wait_until="networkidle", timeout=45000)

            # Initial cursor placement
            curr_x = random.uniform(150, 350)
            curr_y = random.uniform(100, 250)
            await page.mouse.move(curr_x, curr_y)

            # Natural exploratory mouse wander and small scroll
            wander_x = curr_x + random.uniform(-40, 150)
            wander_y = curr_y + random.uniform(50, 180)
            await _human_mouse_move(page, curr_x, curr_y, wander_x, wander_y, steps=20)
            curr_x, curr_y = wander_x, wander_y

            # Allow user to override delay for testing via NAVAREA_XI_DELAY env var
            custom_delay = os.environ.get("NAVAREA_XI_DELAY")
            if custom_delay is not None:
                dwell_time = float(custom_delay)
            else:
                dwell_time = random.uniform(30.0, 40.0)

            print(f"⏳ 2. Simulating human reading dwell time ({dwell_time:.1f}s) between actions...")

            # Divide dwell time into chunks with realistic occasional cursor jitters
            intervals = max(1, int(dwell_time / 5))
            chunk_time = dwell_time / intervals
            for _ in range(intervals):
                await asyncio.sleep(chunk_time)
                # Small human idle micro-adjustment
                next_x = max(50, min(1200, curr_x + random.uniform(-25, 25)))
                next_y = max(50, min(650, curr_y + random.uniform(-25, 25)))
                await _human_mouse_move(page, curr_x, curr_y, next_x, next_y, steps=10)
                curr_x, curr_y = next_x, next_y

            # Locate "All Display" submit button for current year
            print("🔍 3. Locating 'All Display' button...")
            btn_selector = f"#ALLMAP_{current_year}"
            btn = await page.query_selector(btn_selector)

            if not btn:
                # Fallback to general All Display button
                btn = await page.query_selector("input[value='All Display']")

            if not btn:
                print("⚠️ Could not find 'All Display' button in DOM.")
                return {}

            # Scroll button into view if needed
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)

            box = await btn.bounding_box()
            if not box:
                print("⚠️ Button has no bounding box.")
                return {}

            target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)

            print(f"🖱️ 4. Moving mouse along Bézier curve to button ({target_x:.1f}, {target_y:.1f})...")
            await _human_mouse_move(page, curr_x, curr_y, target_x, target_y, steps=30)
            # Dwell/hover over button before clicking
            await asyncio.sleep(random.uniform(0.6, 1.4))

            print("🎯 5. Clicking 'All Display' and awaiting disp_warnings.cgi...")
            disp_page = None
            try:
                # The form uses target="_blank", which triggers a popup tab
                async with context.expect_page(timeout=25000) as new_page_info:
                    await page.mouse.click(target_x, target_y)
                disp_page = await new_page_info.value
                await disp_page.wait_for_load_state("networkidle", timeout=30000)
            except Exception as e:
                print(f"ℹ️ Popup note ({e}), checking current page...")
                disp_page = page

            final_url = disp_page.url
            print(f"📄 Reached final endpoint: {final_url}")
            html_content = await disp_page.content()
            collected = _parse_html_warnings(html_content)
            return collected

        except Exception as e:
            print(f"⚠️ Browser automation error: {e}")
            return {}
        finally:
            await browser.close()


def fetch_direct_disp():
    """HTTP fallback if browser automation or Playwright is not available."""
    print("Direct HTTP fetch from official Japan Coast Guard (kaiho.mlit.go.jp)...")
    if cffi_requests is None:
        return {}
    if HAS_CURL_CFFI:
        response = cffi_requests.get(URL_DISP, impersonate="chrome", timeout=30, verify=True)
    else:
        response = cffi_requests.get(URL_DISP, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, verify=True)
    response.raise_for_status()
    html = response.content.decode(JCG_ENCODING, errors="replace")
    return _parse_html_warnings(html)


def scrape_xi_warnings(output_filename="navareas/navarea_xi/navarea_xi_warnings.txt", year=None):
    print("=" * 60)
    print("⚓ Japan Coast Guard (JCG Kaiho) NAVAREA XI Scraper")
    print("=" * 60)
    if year is None:
        year = datetime.now().year
    collected = {}

    # 1. Try humanized browser automation if Playwright is installed
    if HAS_PLAYWRIGHT:
        try:
            collected = asyncio.run(fetch_via_browser(year=year))
            if collected:
                print(f"✅ Successfully harvested {len(collected)} bulletins via browser automation.")
        except Exception as e:
            print(f"⚠️ Browser harvest attempt failed: {e}")

    # 2. Seamless HTTP fallback if browser was unavailable or yielded zero results
    if not collected:
        try:
            collected = fetch_direct_disp()
            if collected:
                print(f"✅ Successfully harvested {len(collected)} bulletins directly via HTTP fallback.")
        except Exception as e:
            print(f"⚠️ Direct JCG Kaiho HTTP fetch failed: {e}")

    if not collected:
        print("ℹ️ No active warnings harvested from JCG Kaiho or site unavailable; writing valid empty harvest.")
        _write_output({}, output_filename)
        return {}

    print(f"Total warnings: {len(collected)}")
    _write_output(collected, output_filename)
    print(f"✅ Wrote to {output_filename}")
    return collected


if __name__ == "__main__":
    scrape_xi_warnings()

