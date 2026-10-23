"""Collapse duplicate event listings that come from different places.

The same concert shows up on the venue's own calendar, a ticketing page and a community listing,
each with its own spelling: "The Birdland Latin Jazz Orchestra" at "Birdland Jazz Club, New York"
vs "BIRDLAND LATIN JAZZ ORCHESTRA" at "Birdland". eventdedupe groups such listings and merges
each group into one event that keeps every source link.

    from eventdedupe import dedupe, explain
    merged = dedupe(listings)          # list of dicts in, list of dicts out
    explain(listings[0], listings[1])  # why two listings did or didn't match
"""
from ._core import Config, dedupe, explain, groups, merge, same_event
from ._text import similarity, tokens

__all__ = ["Config", "dedupe", "explain", "groups", "merge", "same_event", "similarity", "tokens"]
__version__ = "0.2.0"
