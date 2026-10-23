#!/usr/bin/env python3
"""
shared/feed_registry.py — Known official publication feeds for the
universal-parser regions.

Scope (2026-10-23): only feeds VERIFIED against a live source are
listed. Most coordinators publish through HTML pages rather than plain
text; those are recorded with type 'html*' and status 'reference_only'
— the generic scraper REFUSES them (fail-closed: an HTML page fed into
the text pipeline would parse garbage). When a plain-text endpoint is
verified for one of these regions, flip its entry to
{'type': 'url_text', 'status': 'active'} and it becomes schedulable via
scripts/navarea_universal_scraper.py.

Dedicated-parser regions are NOT listed here (they already have their own
scrapers):
  NAVAREA IV  https://msi.nga.mil/apology_objects/DailyMemIV.txt
  NAVAREA XII https://msi.nga.mil/apology_objects/DailyMemXII.txt
  (NAVAREA 1 / 8 / XI / Baltic: dedicated scrapers in scripts/)
"""

FEEDS = {
    # Spain — NAVAREA III warnings portal (HTML/XML page; the bulletin
    # itself advertises this URL). Plain-text endpoint not yet verified.
    "iii": {
        "url": "https://armada.defensa.gob.es/ihm/aplicaciones/navareas/index_navareas_xml_en.html",
        "type": "html",
        "status": "reference_only",
        "note": "NAVAREA III 0157/26 advertises this page for full texts.",
    },
    # Australia — AMSA NAVAREA X warnings are published as web pages.
    "x": {
        "url": "https://www.amsa.gov.au",
        "type": "html",
        "status": "reference_only",
        "note": "NAVAREA X 112/26: complete texts at WWW.AMSA.GOV.AU.",
    },
    # Norway — Kystverket NAVAREA XIX report page (HTML table view).
    "xix": {
        "url": "https://kyvreports.kystverket.no/NavcoReport/navareaxixvarsler.aspx",
        "type": "html_table",
        "status": "reference_only",
        "note": "Renders the same 'Number:n/yy' corpus the universal "
                "parser ingests; needs an HTML-to-text extractor before "
                "it can be a url_text feed.",
    },
}


def get_text_feed(region_key: str):
    """Returns the verified plain-text feed config for a region, or None.

    Fail-closed: 'reference_only' and 'html*' entries return None — only
    verified plain-text endpoints are scrapable by the generic scraper.
    """
    feed = FEEDS.get(region_key)
    if not feed:
        return None
    if feed.get("status") != "active" or feed.get("type") != "url_text":
        return None
    return feed
