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
    # Spain — NAVAREA III warnings portal. The interactive page renders
    # its 'display all' view from a plain XML snapshot (verified
    # 2026-10-27); a dedicated scraper converts it to the region 'iii'
    # bulletin text and runs the universal parser + generic sync:
    #   scripts/navarea_iii_scraper.py  (entry: scripts/run_navarea_iii.py)
    "iii": {
        "url": "https://armada.defensa.gob.es/ihm/XML/navareas_crudo.xml",
        "type": "xml",
        "status": "reference_only",
        "note": "In-force NAVAREA III XML snapshot (one NAVAREASVIGOR record "
                "per warning, bilingual). Scraped by "
                "scripts/navarea_iii_scraper.py, which synthesizes the "
                "universal bulletin text. NOT url_text: the generic "
                "scraper must not feed raw XML into the text pipeline.",
    },
    # Brazil — CHM 'Avisos-Radio Nauticos e SAR' portal. The page is
    # fed by a Drupal JSON attachment ('avradio_NN.json', NN increments
    # per publish); a dedicated scraper discovers the link, keeps the
    # bare-numbered NAVAREA V records and runs the universal parser +
    # generic sync:
    #   scripts/navarea_v_scraper.py  (entry: scripts/run_navarea_v.py)
    "v": {
        "url": "https://www.marinha.mil.br/chm/dados-do-segnav-aviso-radio-nautico-tela/avisos-radio-nauticos-e-sar",
        "type": "json",
        "status": "reference_only",
        "note": "In-force Brazilian radio navigational warnings (bare "
                "NAVAREA V series, SAR, costeiros), one record per "
                "warning, bilingual. Scraped by "
                "scripts/navarea_v_scraper.py, which synthesizes the "
                "universal bulletin text. NOT url_text: the generic "
                "scraper must not feed raw JSON into the text pipeline.",
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

    Fail-closed: 'reference_only' and non-'url_text' entries return None —
    only verified plain-text endpoints are scrapable by the generic scraper.
    """
    feed = FEEDS.get(region_key)
    if not feed:
        return None
    if feed.get("status") != "active" or feed.get("type") != "url_text":
        return None
    return feed
