"""The Boardwire newsroom.

A multi-stage editorial pipeline that turns clusters of feed items into deeply
researched stories — the way a real media agency works:

  News Desk  → selects story leads (cluster + beat + angle)
  Reporter   → deep multi-source research → ResearchDossier
  Fact-Check → verifies claims                     (later phase)
  Editor     → short post / article / thread        (later phase)
  Story Memory → tracks running storylines for follow-ups

Everything here is gated behind ``BOARDWIRE_ENABLE_NEWSROOM`` and runs
alongside — never instead of — the existing pipeline.
"""
