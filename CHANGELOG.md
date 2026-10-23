# Changelog

## 0.2.0 (2026-10-23)

- `same_link`: the same event page on the same date and time, with related titles, is one event.
  Tracking parameters, `www.` and plain fragments are ignored; hash-routed calendars keep their
  route; site roots, bare listing pages and shared profile links don't count.
- `title_coordinates`: listing coordinates within 150 m confirm a place whose names disagree;
  more than 3 km apart blocks a merge with no venue name on one side.
- Online vs in person: an explicitly online listing never merges with an explicitly in-person one.
- Status: the merge keeps the worst status any listing reports (cancelled > postponed >
  rescheduled); "CANCELLED: ..." titles still match their twin.
- `Config.strict()` and `Config.lenient()` presets.
- `explain()` reports `distance_km`.
- Fix: a bounded title score could be reused for a stricter threshold within one comparison.

## 0.1.0 (2026-10-22)

First release.

- `dedupe`, `groups`, `merge`, `same_event`, `explain`, `Config`.
- Rules: `title_venue`, `title_only`, `lead_in`, `headliner`, `place_overlap`, `sports_matchup`,
  `ampm_flip`, `time_drift`, `doors_vs_show`.
- Offset-aware start times; schema.org Event input; `key_map` for other shapes.
- `eventdedupe` command line (JSON or JSON Lines, `--explain`, `--key`).
- Optional `rapidfuzz` speed-up (`eventdedupe[fast]`).
- Guards: session words ("Late Show", "2nd Seating", "Set 2", "Matinee") block the cross-source
  time rules; "X at Y" counts as a game only with a "vs" or a sport word.
- Command line reads and writes UTF-8 regardless of the console code page.
