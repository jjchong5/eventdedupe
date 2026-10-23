"""Matching, grouping and merging."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping

from . import _text
from ._sports import matchup, matchups_agree
from ._time import date_of, gap_minutes, parse_start

EMPTY = (None, "", [], {})


@dataclass(frozen=True)
class Config:
    """Every threshold the matcher uses. The defaults are the tested ones."""

    time_tolerance_min: float = 45
    """Two starts further apart than this are two shows (unless a cross-source rule applies)."""
    title_match: float = 0.85
    """Title similarity needed when both venues agree."""
    title_match_no_venue: float = 0.93
    """Stricter title similarity when one listing has no venue to confirm it."""
    venue_match: float = 0.8
    """Venue-name similarity for two venues to count as the same place."""

    strong_title: float = 0.95
    """Near-identical title, for the cross-source rules below."""
    strong_title_min_chars: int = 12
    """...and long enough to be specific ("Zumba" is not)."""
    drift_window_min: float = 90
    """Cross-source: a strong title match may drift this far (an hour's error in one listing)."""
    ampm_flip: bool = True
    """Cross-source: accept starts 12 hours apart (06:30 vs 18:30) on a strong title match."""
    doors_vs_show: bool = True
    """Cross-source: accept doors vs show times when one title starts the other."""
    headliner_window_min: float = 30
    """Cross-source: same venue, start within this, same opening act name."""
    lead_in_chars: int = 12
    """Same venue and same opening run of letters: one recurring night re-posted."""
    sports: bool = True
    """"A vs B" and "B at A" are one game when the sides, sport and time agree."""
    sports_window_min: float = 90

    title_noise: frozenset = _text.TITLE_NOISE
    venue_spellings: Mapping[str, str] = field(default_factory=lambda: dict(_text.VENUE_SPELLINGS))
    fast: bool = False
    """Use rapidfuzz for the edit ratio when it is installed (pip install eventdedupe[fast])."""


DEFAULT = Config()

# Where each field is looked for, in order, when no key_map names it. Covers the plain shape
# (title/date/start/venue/link), schema.org Event (name/startDate/location/url) and a few
# common scraper spellings.
FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "title": ("title", "name", "summary"),
    "date": ("date", "start_date"),
    "start": ("start", "startDate", "start_time", "starts_at", "dtstart"),
    "venue": ("venue", "location", "venue_name", "place"),
    "link": ("link", "url"),
    "source": ("source",),
    "first_seen": ("first_seen",),
}


def _get(event: Mapping[str, Any], path: str) -> Any:
    value: Any = event
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def _venue_text(value: Any) -> str | None:
    """A venue string from a plain string or a schema.org Place."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, Mapping):
        name = value.get("name")
        address = value.get("address")
        if isinstance(address, Mapping):
            address = address.get("streetAddress")
        return name or (address if isinstance(address, str) else None)
    return value if isinstance(value, str) else None


class _View:
    """One listing, read once into everything the matcher compares."""

    __slots__ = ("title", "title_tokens", "title_sorted", "title_set", "title_joined", "venue",
                 "venue_tokens", "venue_sorted", "venue_set", "date", "start", "aware", "source",
                 "link", "first_seen", "matchup")

    def __init__(self, event: Mapping[str, Any], key_map: Mapping[str, str] | None, cfg: Config):
        def pick(name: str) -> Any:
            if key_map and name in key_map:
                return _get(event, key_map[name])
            for key in FIELD_KEYS[name]:
                v = event.get(key)
                if v not in EMPTY:
                    return v
            return None

        raw_title = pick("title")
        self.title = raw_title if isinstance(raw_title, str) else (str(raw_title) if raw_title else "")
        self.title_tokens = _text.tokens(self.title, cfg.title_noise)
        self.title_sorted = " ".join(sorted(self.title_tokens))
        self.title_set = frozenset(self.title_tokens)
        self.title_joined = _text.joined(self.title)
        self.venue = _venue_text(pick("venue"))
        self.venue_tokens = _text.venue_tokens(self.venue, cfg.venue_spellings)
        self.venue_sorted = " ".join(sorted(self.venue_tokens))
        self.venue_set = frozenset(self.venue_tokens)
        raw_start = pick("start")
        self.start = parse_start(raw_start)
        self.aware = self.start is not None and self.start.tzinfo is not None
        self.date = date_of(pick("date")) or date_of(raw_start)
        src = pick("source")
        self.source = str(src) if src not in EMPTY else None
        self.link = pick("link")
        self.first_seen = pick("first_seen")
        self.matchup = matchup(self.title) if cfg.sports else None


def _sim(a_sorted: str, a_set: frozenset, b_sorted: str, b_set: frozenset, containment: bool,
         fast: bool, need: float | None = None) -> float:
    """similarity() on precomputed parts. With `need`, it may return any value below `need`
    as soon as the score is known to fall short (cheap upper bounds first)."""
    if not a_set or not b_set:
        return 0.0
    if a_sorted == b_sorted:
        return 1.0
    shorter = min(len(a_set), len(b_set))
    contain = len(a_set & b_set) / shorter if containment and shorter >= 2 else 0.0
    if need is not None and contain >= need:
        return contain
    if need is not None and not fast:
        sm = SequenceMatcher(None, a_sorted, b_sorted)
        if sm.real_quick_ratio() < need or sm.quick_ratio() < need:
            return contain
        return max(contain, sm.ratio())
    return max(contain, _text._ratio(a_sorted, b_sorted, fast))


def _strong(a: _View, b: _View, cfg: Config) -> bool:
    return (min(len(a.title_joined), len(b.title_joined)) >= cfg.strong_title_min_chars
            and _sim(a.title_sorted, a.title_set, b.title_sorted, b.title_set, False, cfg.fast,
                     cfg.strong_title) >= cfg.strong_title)


def _decide(a: _View, b: _View, cfg: Config, full: bool = True) -> dict[str, Any]:
    """The decision for one pair, with the evidence behind it.

    `full=False` (bulk grouping) skips evidence the decision did not need.
    """
    gap = gap_minutes(a.start, b.start)
    same_source = (a.source == b.source) if (a.source and b.source) else None
    cross_source = same_source is False
    both_venues = bool(a.venue_set and b.venue_set)
    out: dict[str, Any] = {
        "match": False, "rule": None, "reason": "",
        "dates": [a.date, b.date], "start_gap_minutes": None if gap is None else round(gap, 1),
        "same_source": same_source, "title_similarity": None, "venue_similarity": None,
    }
    memo: dict[str, Any] = {}

    def title_sim(need: float | None = None) -> float:
        if "t" not in memo or (need is None and memo["t_bound"]):
            memo["t"] = _sim(a.title_sorted, a.title_set, b.title_sorted, b.title_set, True,
                             cfg.fast, None if full else need)
            memo["t_bound"] = need is not None and not full
        return memo["t"]

    def venue_ok() -> bool:
        if "v" not in memo:
            v = _sim(a.venue_sorted, a.venue_set, b.venue_sorted, b.venue_set, True, cfg.fast,
                     None if full else cfg.venue_match)
            memo["vs"] = v
            memo["v"] = v >= cfg.venue_match or _text.venue_prefix_match(a.venue_tokens, b.venue_tokens)
        return memo["v"]

    def overlap() -> bool:
        if "o" not in memo:
            memo["o"] = both_venues and not venue_ok() and _text.place_overlap(a.venue, b.venue)
        return memo["o"]

    def place_ok() -> bool:
        return not both_venues or venue_ok() or overlap()

    def finish(match: bool, rule: str | None, reason: str) -> dict[str, Any]:
        out.update(match=match, rule=rule, reason=reason)
        if full:
            out["title_similarity"] = round(title_sim(), 3)
            if both_venues:
                venue_ok()
                out["venue_similarity"] = round(memo["vs"], 3)
        return out

    def yes(rule: str, reason: str) -> dict[str, Any]:
        return finish(True, rule, reason)

    def no(reason: str) -> dict[str, Any]:
        return finish(False, None, reason)

    if a.date != b.date and not (a.aware and b.aware and gap is not None
                                 and gap <= cfg.time_tolerance_min):
        return no("different dates")

    if (a.matchup and b.matchup and same_source is not True
            and matchups_agree(a.matchup, b.matchup, a.title, b.title)):
        if gap is not None and gap > cfg.sports_window_min:
            return no(f"same matchup but starts {gap:.0f} min apart (a different game)")
        if not place_ok():
            return no("same matchup at different venues")
        return yes("sports_matchup", "same two sides, sport and time")

    if gap is not None and gap > cfg.time_tolerance_min:
        if not cross_source:
            why = "same source" if same_source else "no source field to tell listings apart"
            return no(f"starts {gap:.0f} min apart ({why}: treated as two sessions)")
        if not place_ok():
            return no(f"starts {gap:.0f} min apart at different venues")
        if cfg.ampm_flip and abs(gap - 720) <= 30 and _strong(a, b, cfg):
            return yes("ampm_flip", "starts 12 h apart, same title and place: one listing flipped AM/PM")
        if gap <= cfg.drift_window_min and _strong(a, b, cfg):
            return yes("time_drift", f"starts {gap:.0f} min apart, same title and place")
        if (cfg.doors_vs_show and gap <= cfg.drift_window_min
                and _text.one_contains_other(a.title, b.title, cfg.strong_title_min_chars)):
            return yes("doors_vs_show", f"starts {gap:.0f} min apart and one title starts the other "
                                        "(doors time vs show time)")
        return no(f"starts {gap:.0f} min apart")

    if both_venues:
        if venue_ok():
            if title_sim(cfg.title_match) >= cfg.title_match:
                return yes("title_venue", "similar title at the same venue")
            if (cross_source and gap is not None and gap <= cfg.headliner_window_min
                    and _text.shared_headliner(a.title, b.title)):
                return yes("headliner", "same venue and time, titles open with the same act")
            if _text.shared_lead_in(a.title, b.title, cfg.lead_in_chars):
                return yes("lead_in", "same venue and time, titles share their opening words "
                                      "(a recurring night posted twice)")
            return no("same venue, titles too different")
        if overlap() and _strong(a, b, cfg):
            return yes("place_overlap", "same title, venue named in different words")
        return no("different venues")

    strict = _sim(a.title_sorted, a.title_set, b.title_sorted, b.title_set, False, cfg.fast,
                  None if full else cfg.title_match_no_venue)
    if strict >= cfg.title_match_no_venue:
        return yes("title_only", "near-identical title, no venue on one side to contradict it")
    return no("no venue to confirm a looser title match")


def _views(events: Iterable[Mapping[str, Any]], key_map, cfg) -> list[_View]:
    return [_View(e, key_map, cfg) for e in events]


def explain(a: Mapping[str, Any], b: Mapping[str, Any], *, key_map: Mapping[str, str] | None = None,
            config: Config | None = None) -> dict[str, Any]:
    """Why two listings are or aren't the same event.

    Returns a dict: `match`, the `rule` that matched (or None), a plain-English `reason`, and the
    evidence (`dates`, `start_gap_minutes`, `same_source`, `title_similarity`, `venue_similarity`).
    """
    cfg = config or DEFAULT
    return _decide(_View(a, key_map, cfg), _View(b, key_map, cfg), cfg)


def same_event(a: Mapping[str, Any], b: Mapping[str, Any], *, key_map: Mapping[str, str] | None = None,
               config: Config | None = None) -> bool:
    """True if the two listings describe the same event."""
    return explain(a, b, key_map=key_map, config=config)["match"]


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[max(ri, rj)] = min(ri, rj)


def _next_day(d: str) -> str | None:
    try:
        return (date.fromisoformat(d) + timedelta(days=1)).isoformat()
    except ValueError:
        return None


def _link(views: list[_View], cfg: Config, edges: list | None = None) -> _UnionFind:
    by_date: dict[str, list[int]] = defaultdict(list)
    for i, v in enumerate(views):
        by_date[v.date or ""].append(i)
    uf = _UnionFind(len(views))

    def try_pair(i: int, j: int) -> None:
        if uf.find(i) == uf.find(j):
            return
        d = _decide(views[i], views[j], cfg, full=False)
        if d["match"]:
            uf.union(i, j)
            if edges is not None:
                edges.append((i, j, d))

    for day, idx in by_date.items():
        for x, i in enumerate(idx):
            for j in idx[x + 1:]:
                try_pair(i, j)
        # Listings in different zones can land on different local dates (20:00 -07:00 is
        # 03:00 UTC the next day): compare offset-aware starts across midnight too.
        nxt = _next_day(day) if day else None
        if nxt and nxt in by_date:
            for i in idx:
                if views[i].aware:
                    for j in by_date[nxt]:
                        if views[j].aware:
                            try_pair(i, j)
    return uf


def groups(events: list[Mapping[str, Any]], *, key_map: Mapping[str, str] | None = None,
           config: Config | None = None) -> list[list[int]]:
    """Indices of the listings that are one event, groups in order of first appearance.

    Matches are transitive: if A~B and B~C, all three group even when A and C alone would not.
    Listings are only compared within a date (plus the next date for offset-aware starts),
    so the work stays small per day instead of quadratic over the whole calendar.
    """
    cfg = config or DEFAULT
    uf = _link(_views(events, key_map, cfg), cfg)
    out: dict[int, list[int]] = defaultdict(list)
    for i in range(len(events)):
        out[uf.find(i)].append(i)
    return [out[root] for root in sorted(out)]


def _richness(event: Mapping[str, Any]) -> int:
    return sum(1 for v in event.values() if v not in EMPTY)


def merge(group: list[Mapping[str, Any]], *, key_map: Mapping[str, str] | None = None,
          config: Config | None = None) -> dict[str, Any]:
    """One event from a group: the most complete listing, gaps filled from the others.

    Adds `links` (every source link, in input order), `duplicates` (how many listings were
    folded in) and keeps the earliest `first_seen`.
    """
    cfg = config or DEFAULT
    primary = max(group, key=_richness)  # max() keeps the first on ties: input order wins
    merged = dict(primary)
    for other in group:
        for k, v in other.items():
            if merged.get(k) in EMPTY and v not in EMPTY:
                merged[k] = v
    links: list[Any] = []
    for e in group:
        for link in [_View(e, key_map, cfg).link, *(e.get("links") or [])]:
            if link and link not in links:
                links.append(link)
    merged["links"] = links
    seen = [s for s in (_View(e, key_map, cfg).first_seen for e in group) if s]
    if seen:
        key = (key_map or {}).get("first_seen", "first_seen")
        merged[key] = min(seen)
    merged["duplicates"] = len(group) - 1
    return merged


def dedupe(events: list[Mapping[str, Any]], *, key_map: Mapping[str, str] | None = None,
           config: Config | None = None, explain_matches: bool = False) -> list[dict[str, Any]]:
    """Merged events, in the order each group first appears in the input.

    With `explain_matches=True` each merged event also carries `_matches`: the pairs that
    joined it (input indices) with the rule and reason for each.
    """
    cfg = config or DEFAULT
    edges: list | None = [] if explain_matches else None
    uf = _link(_views(events, key_map, cfg), cfg, edges)
    by_root: dict[int, list[int]] = defaultdict(list)
    for i in range(len(events)):
        by_root[uf.find(i)].append(i)
    out = []
    for root in sorted(by_root):
        idx = by_root[root]
        merged = merge([events[i] for i in idx], key_map=key_map, config=cfg)
        if edges is not None:
            members = set(idx)
            merged["_matches"] = [{"pair": [i, j], "rule": d["rule"], "reason": d["reason"]}
                                  for i, j, d in edges if i in members]
        out.append(merged)
    return out
