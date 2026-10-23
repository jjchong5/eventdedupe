# eventdedupe

Merge duplicate event listings that come from different sources, and see why each pair matched.

The same concert shows up on the venue's calendar, a ticketing site and a community listing, each
spelled its own way, sometimes with a different start time. `eventdedupe` groups those listings
and merges each group into one event that keeps every source link. Plain dicts in, plain dicts
out, no dependencies.

It comes out of [What's Up In](https://whatsupin.ai), which merges listings from 1,500+ sources
across 57 cities. The rules here are the generic ones from that pipeline, rewritten as a small
library with tests.

## Quickstart

```bash
pip install eventdedupe
```

```python
from eventdedupe import dedupe, explain

listings = [
    {"title": "The Birdland Latin Jazz Orchestra", "start": "2026-10-18T17:30:00-04:00",
     "venue": "Birdland Jazz Club, 315 W 44th St", "link": "https://venue.example/latin-jazz"},
    {"title": "BIRDLAND LATIN JAZZ ORCHESTRA", "start": "2026-10-18T17:30:00-04:00",
     "venue": "Birdland", "link": "https://tickets.example/e/1001", "price": "$35"},
]
events = dedupe(listings)        # one event, with links from both listings and the price
explain(listings[0], listings[1])  # {'match': True, 'rule': 'title_venue', 'reason': ..., ...}
```

Or from the shell, with a JSON array or JSON Lines file:

```bash
eventdedupe listings.jsonl > events.jsonl
eventdedupe listings.json --explain -o events.json   # adds _matches: which pairs joined, and why
```

## Before and after

[`examples/three_sources.json`](examples/three_sources.json) has 9 listings from a venue site, a
ticketing site, a team site and a community calendar. `eventdedupe` turns them into 5 events:

| Listings | Became | Rule |
|---|---|---|
| "The Birdland Latin Jazz Orchestra" at "Birdland Jazz Club, 315 W 44th St" 17:30 -04:00; "BIRDLAND LATIN JAZZ ORCHESTRA" at "Birdland"; a schema.org Event at 21:30 UTC | 1 event, 3 links | `title_venue` (times compared by instant) |
| "Velvet Lanterns" 19:00; "Velvet Lanterns with Glass Harbor and Dune Choir" 20:00, same club | 1 event, 2 links | `doors_vs_show` |
| "Harbor Town Hawks at Bay City Bears" 13:00; "Bay City Bears vs. Harbor Town Hawks" 13:05 | 1 event, 2 links | `sports_matchup` |
| "Late Night Laughs: Comedy Showcase" 19:00 and 21:30, same club, same source | 2 events | early and late show stay apart |

## How it differs from hand-rolled title + date matching

Most aggregators dedupe with "same date, fuzzy title, maybe same venue". That catches the easy
cases. These are the ones it misses or gets wrong, each handled by a named rule you can see in
`explain()` and switch off in `Config`:

| Rule | What it catches |
|---|---|
| `title_venue` | Word order, case, accents, "&" vs "and", noise words ("live", "presents", "tickets"), venue spellings ("Theatre"/"Theater", "St"/"Street"), a venue name with or without its address, and "Birdland" vs "Birdland Jazz Club". |
| `title_only` | One listing has no venue: only a near-identical title counts. |
| `lead_in` | A recurring night re-posted with different wording after the same opening ("SalsaCrazy Saturday - Dance Lessons..." / "Salsa Crazy Saturday - Best Dance Party..."), at the same venue and time. |
| `headliner` | Ticket sites retitling one show ("Marigold Echo - Northern Lights Tour" / "Marigold Echo with Pale Season"): same venue, start within 30 min, same act name. |
| `place_overlap` | One venue named two ways ("John Natsoulas Gallery" / "John Natsoulas Center for the Arts") with a near-identical title. |
| `sports_matchup` | "A vs. B", "A v B", "B at A", "B @ A"; plural vs singular team names; without merging a doubleheader, a watch party, a fan shuttle, a different sport or the women's game. |
| `ampm_flip` | One source writes 06:30 for 18:30. |
| `time_drift` | One source is an hour off. |
| `doors_vs_show` | One source lists doors (19:00), the other the show (20:00) and adds the support acts to the title. |

Guards that keep it from over-merging:

- **Two times more than 45 minutes apart are two events** unless both listings carry a different
  `source`. The cross-source time rules (`ampm_flip`, `time_drift`, `doors_vs_show`,
  `headliner`) only run when they do; the same source posting a title twice in one day means two
  sessions (an early and a late show, a morning and an afternoon class).
- **Session words keep shows apart across sources too**: "Late Show", "2nd Seating", "Set 2" or
  "Matinee" in one title and not the other blocks the cross-source time rules.
- **"X at Y" is only a game with a "vs" or a sport word**: "Comedy Night at The Independent" is a
  show at a venue, not a matchup.
- **Short, generic titles never merge across different venues** ("Zumba" at two parks is two
  classes), and the time rules need a title at least 12 letters long.
- **Times with offsets compare by instant**: "20:00 -07:00" and "03:00Z the next day" are the same
  start, even across midnight.
- **Matches are transitive**: if A~B and B~C, all three merge.

## Input shapes

Each listing is a dict. Fields are found by name, in this order:

| Field | Keys tried |
|---|---|
| title (required) | `title`, `name`, `summary` |
| date | `date`, `start_date`; else the date part of the start |
| start | `start`, `startDate`, `start_time`, `starts_at`, `dtstart` (ISO 8601, any offset, or a `datetime`) |
| venue | `venue`, `location`, `venue_name`, `place` (a string, or a schema.org `Place` dict) |
| link | `link`, `url` |
| source | `source` (any id for where the listing came from) |
| first_seen | `first_seen` |

So schema.org `Event` JSON-LD works as is. For anything else, map the names, dotted paths allowed:

```python
dedupe(rows, key_map={"title": "headline", "start": "when", "venue": "place.label", "link": "href"})
```

```bash
eventdedupe rows.jsonl --key title=headline --key venue=place.label
```

## Output

`dedupe()` returns one dict per event, in order of first appearance. Each is the most complete
listing of its group, with empty fields filled from the others, plus:

- `links`: every listing's link, in input order
- `duplicates`: how many listings were folded in
- `first_seen`: the earliest, when listings have one
- `_matches` (with `explain_matches=True` or `--explain`): the pairs that joined, with rule and reason

`groups()` returns just the index groups, if you'd rather merge yourself. `same_event(a, b)` and
`explain(a, b)` compare two listings.

## Tuning

```python
from eventdedupe import Config, dedupe

dedupe(rows, config=Config(time_tolerance_min=30, title_match=0.9, sports=False))
```

Every threshold and rule switch is a `Config` field with a docstring. `Config(fast=True)` uses
[rapidfuzz](https://github.com/rapidfuzz/RapidFuzz) for the edit ratio when installed
(`pip install eventdedupe[fast]`); the default is the standard library's `difflib`.

## Speed

Listings are only compared within a date (plus the next date, for offset-aware starts), so the work
grows with the busiest day, not the whole calendar. 5,000 listings over 28 days take a few seconds
in pure Python.

## Limits

- No geocoding: two venue strings are compared as text. Coordinates are carried along but unused.
- Multi-day events are matched by start date only.
- Recurring series are not detected as series; each night is its own event.
- The rules are tuned for English listing conventions.

These are the generic rules. Source-specific fixes (one site's time-zone quirk, another's
placeholder venue) belong in your scrapers, before deduplication.

## Development

```bash
pip install -e . pytest
pytest
```

MIT licensed. Issues and pull requests welcome.
