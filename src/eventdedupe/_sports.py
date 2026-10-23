"""Sports games: "A vs B", "A v. B", "B at A" and "B @ A" name the same game."""
from __future__ import annotations

import re

from ._text import tokens

_SPLIT = re.compile(r"\s+(vs?\.?|versus|at|@)\s+", re.I)
_TAIL = re.compile(r"\s+(?:-|–|—|\||\(|:).*$")
SPORT_WORDS = frozenset({
    "hockey", "basketball", "football", "soccer", "volleyball", "lacrosse", "baseball", "softball",
    "rugby", "tennis", "squash", "rowing", "fencing", "golf", "swimming", "wrestling", "polo",
})
_GENDER = {"men": "m", "mens": "m", "women": "w", "womens": "w"}
_FILLER = SPORT_WORDS | set(_GENDER) | {
    "s", "the", "field", "ice", "nfl", "nba", "nhl", "mlb", "wnba", "mls", "nwsl", "pwhl",
    "preseason", "game",
}
# Something sold around a game is not the game: a museum "Gameday Pass", a fan shuttle,
# parking, a tailgate or a watch party that names both teams.
_ADDON = re.compile(r"\b(?:pass|shuttle|bus|parking|tailgate|watch party)\b", re.I)

# (the two sides, sport words, men's/women's marks, whether the title said "vs"/"v"/"versus")
Matchup = tuple[list[frozenset], set, set, bool]


def matchup(title: str | None) -> Matchup | None:
    """The two sides of a game title, plus any sport and men's/women's words, or None."""
    parts = _SPLIT.split(title or "", maxsplit=1)
    if len(parts) != 3:
        return None
    a, sep, b = parts[0], parts[1], _TAIL.sub("", parts[2])
    words = tokens(f"{a} {b}", ())
    # Singular forms, so "Red Bulls" matches "Red Bull New York".
    sides = [frozenset(w[:-1] if len(w) > 3 and w.endswith("s") else w
                       for w in tokens(s, ()) if w not in _FILLER) for s in (a, b)]
    if not all(sides):
        return None
    versus = sep.lower().rstrip(".") in ("v", "vs", "versus")
    return (sides, {w for w in words if w in SPORT_WORDS}, {_GENDER[w] for w in words if w in _GENDER},
            versus)


def _side_match(x: frozenset, y: frozenset) -> bool:
    small, big = (x, y) if len(x) <= len(y) else (y, x)
    return small <= big and len("".join(small)) >= 4


def same_matchup(title_a: str | None, title_b: str | None) -> bool:
    """Both titles name the same two sides, in either order, and nothing contradicts it
    (a different sport, men's vs women's, or a pass/shuttle/watch party)."""
    ma, mb = matchup(title_a), matchup(title_b)
    return bool(ma and mb) and matchups_agree(ma, mb, title_a, title_b)


def matchups_agree(ma: Matchup, mb: Matchup, title_a: str | None, title_b: str | None) -> bool:
    """same_matchup() on already-parsed matchups."""
    if _ADDON.search(title_a or "") or _ADDON.search(title_b or ""):
        return False
    (a1, a2), sport_a, sex_a, vs_a = ma
    (b1, b2), sport_b, sex_b, vs_b = mb
    # "Comedy at The Independent" also splits on "at": without a "vs" or a sport word on either
    # side it is a show at a venue, not a game, and the ordinary rules decide.
    if not (vs_a or vs_b or sport_a or sport_b):
        return False
    if (sport_a and sport_b and not sport_a & sport_b) or (sex_a and sex_b and sex_a != sex_b):
        return False
    return (_side_match(a1, b1) and _side_match(a2, b2)) or (_side_match(a1, b2) and _side_match(a2, b1))
