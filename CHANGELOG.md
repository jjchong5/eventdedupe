# Changelog

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
