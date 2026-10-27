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
    # South Africa — SANHO 'NAVAREA VII Messages' page. The in-force
    # messages are plain text inside a static HTML page (verified
    # 2026-10-27) — already the exact region 'vii' bulletin format; a
    # dedicated scraper strips and slices the page and runs the
    # universal parser + generic sync:
    #   scripts/navarea_vii_scraper.py  (entry: scripts/run_navarea_vii.py)
    "vii": {
        "url": "https://www.sanho.co.za/notices_mariners/navarea_v11_messages.htm?b2=NAVAREA+VII",
        "type": "html",
        "status": "reference_only",
        "note": "In-force NAVAREA VII messages as text in a static HTML "
                "page. Scraped by scripts/navarea_vii_scraper.py, which "
                "extracts the message region (page-anchor slicing) and "
                "feeds the universal parser. NOT url_text: the generic "
                "scraper must not feed raw HTML into the text pipeline.",
    },
    # Australia — AMSA publishes in-force NAVAREA X warnings inside
    # the RCC Australia MSI publication page (the backend behind the
    # amsa.gov.au 'Maritime safety information database'); verified
    # 2026-10-27. A dedicated scraper slices 'Part 2. NAVAREA X
    # warnings' out of the page and runs the universal parser +
    # generic sync:
    #   scripts/navarea_x_scraper.py  (entry: scripts/run_navarea_x.py)
    "x": {
        "url": "https://www.operations.amsa.gov.au/AMSA.Web.MSIPublication/Home",
        "type": "html",
        "status": "reference_only",
        "note": "In-force NAVAREA X warnings (Part 2 of the RCC Australia "
                "MSI publication) as text inside a static HTML page. "
                "Scraped by scripts/navarea_x_scraper.py, which slices "
                "Part 2 between the page's own anchors and feeds the "
                "universal parser. NOT url_text: the generic scraper must "
                "not feed raw HTML into the text pipeline.",
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
    # Pakistan — NHO 'NAVAREA IX Warnings' page. The page is a metadata
    # table; each row links a plain-text document that is already the
    # exact region 'ix' bulletin block format (verified 2026-10-27).
    # A dedicated scraper resolves the row documents (follows the row
    # links, or derives the URLs from the row DTG when the raw HTML
    # ships no href) and runs the universal parser + generic sync:
    #   scripts/navarea_ix_scraper.py  (entry: scripts/run_navarea_ix.py)
    "ix": {
        "url": "https://hydrography.paknavy.gov.pk/navarea-ix-warnings/",
        "type": "html_table",
        "status": "reference_only",
        "note": "In-force NAVAREA IX metadata table; each 'View "
                "Document' link points to a plain-text warning file "
                "under the navarea-warnings plugin. Scraped by "
                "scripts/navarea_ix_scraper.py, which resolves the row "
                "documents and concatenates them. NOT url_text: "
                "the generic scraper must not feed the table HTML into "
                "the text pipeline.",
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
