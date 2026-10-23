"""Text normalization and similarity for titles and venue names."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable

# Words that change between listings of the same event without changing the event.
TITLE_NOISE = frozenset({
    "a", "an", "and", "at", "the", "with", "presents", "present", "live", "tickets", "ticket",
    "feat", "featuring", "ft", "w", "plus", "special", "guest", "guests", "event", "show",
})
VENUE_NOISE = frozenset({"the", "at"})
# Spellings that differ between listings of the same place.
VENUE_SPELLINGS = {
    "st": "street", "ave": "avenue", "blvd": "boulevard", "rd": "road", "ctr": "center",
    "centre": "center", "theatre": "theater", "amphitheatre": "amphitheater", "mt": "mount",
    "ft": "fort", "intl": "international",
}
# Leading words that don't identify an act ("The", "Live", "Salsa Night"): a shared headliner
# has to be more than these.
GENERIC_LEAD = frozenset({
    "the", "a", "an", "live", "comedy", "open", "night", "dance", "class", "music", "show", "free",
    "salsa", "bachata", "tango", "swing", "jazz", "tour", "presents", "sunday", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "weekly", "annual",
})
# Words ignored when two venue strings are compared word by word ("Heart Health Park" vs
# "Heart Health Park at Cal Expo").
PLACE_STOP = frozenset({"the", "at", "of", "and", "for", "in", "center", "centre", "hall", "room",
                        "building"})

try:  # optional speed-up, used only when Config(fast=True)
    from rapidfuzz.fuzz import ratio as _rf_ratio
except ImportError:  # pragma: no cover - depends on the environment
    _rf_ratio = None


def tokens(text: str | None, noise: Iterable[str] = TITLE_NOISE) -> list[str]:
    """Accent-free, case-folded word tokens with noise words removed."""
    if not text:
        return []
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ").replace("'", "").replace("’", "")
    words = re.findall(r"[^\W_]+", text)
    noise = noise if isinstance(noise, (set, frozenset)) else set(noise)
    return [w for w in words if w not in noise]


def venue_tokens(venue: str | None, spellings: dict[str, str] = VENUE_SPELLINGS) -> list[str]:
    """Tokens of the venue name: the part before the first comma, spellings unified.

    "Birdland Jazz Club, 315 W 44th St, New York" -> ["birdland", "jazz", "club"].
    """
    return [spellings.get(w, w) for w in tokens((venue or "").split(",")[0], VENUE_NOISE)]


def venue_prefix_match(a: list[str], b: list[str], min_chars: int = 6) -> bool:
    """One venue name is the start of the other, word for word: "Birdland" / "Birdland Jazz
    Club", "Verdi Club" / "Verdi Club Ballroom". Short names ("Pier") don't count."""
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return longer[:len(shorter)] == shorter and len("".join(shorter)) >= min_chars


def joined(title: str | None) -> str:
    """All title words run together: "Salsa Crazy" and "SalsaCrazy" compare equal."""
    return "".join(tokens(title, ()))


def _ratio(a: str, b: str, fast: bool) -> float:
    if fast and _rf_ratio is not None:
        return _rf_ratio(a, b) / 100.0
    return SequenceMatcher(None, a, b).ratio()


def similarity(a: list[str], b: list[str], containment: bool = True, fast: bool = False) -> float:
    """0..1. The better of an order-free edit ratio and token containment.

    Containment catches a listing that adds words ("Jazz Night" vs "Jazz Night with the Trio"),
    but only when the shorter side has at least two tokens, so "Trivia" can't swallow
    "Harry Potter Trivia Championship". Callers turn it off when nothing else (a venue)
    confirms the match, because added words can also mean a different event.
    """
    if not a or not b:
        return 0.0
    ratio = _ratio(" ".join(sorted(a)), " ".join(sorted(b)), fast)
    sa, sb = set(a), set(b)
    shorter = min(len(sa), len(sb))
    contain = len(sa & sb) / shorter if containment and shorter >= 2 else 0.0
    return max(ratio, contain)


def one_contains_other(a: str | None, b: str | None, min_chars: int = 8) -> bool:
    """The shorter title, run together, is the start of the longer one.

    "Lindy in the Park" / "Lindy in the Park Swing Dance Party (Golden Gate Park)";
    a venue page's "Zolita" / a ticket site's "ZOLITA - The Hell's Belles Tour".
    """
    ja, jb = joined(a), joined(b)
    shorter, longer = (ja, jb) if len(ja) <= len(jb) else (jb, ja)
    return len(shorter) >= min_chars and longer.startswith(shorter)


def shared_lead_in(a: str | None, b: str | None, min_chars: int = 12) -> bool:
    """Both titles start with the same run of at least `min_chars` letters.

    Recurring nights get re-posted with very different wording after a common lead-in
    ("SalsaCrazy Saturday - Dance Lessons..." vs "Salsa Crazy Saturday - SF's Hottest..."),
    which whole-title similarity scores far too low.
    """
    ja, jb = joined(a), joined(b)
    return len(ja) >= min_chars and len(jb) >= min_chars and ja[:min_chars] == jb[:min_chars]


def shared_headliner(a: str | None, b: str | None, min_chars: int = 7,
                     generic: Iterable[str] = GENERIC_LEAD) -> bool:
    """Both titles open with the same act name.

    Ticket sites title one show differently ("Mumford & Sons - Prizefighter Tour" vs
    "Mumford & Sons with Sierra Ferrell"). The shared leading words, minus generic ones,
    must add up to `min_chars`; a whole title that starts the other needs only 4.
    """
    generic = set(generic)

    def words(t: str | None) -> list[str]:
        w = [x for x in tokens(t, ()) if x != "and"]
        return w[1:] if w[:1] == ["the"] and len(w) > 1 else w

    wa, wb = words(a), words(b)
    run: list[str] = []
    for x, y in zip(wa, wb):
        if x != y:
            break
        run.append(x)
    kept = "".join(w for w in run if w not in generic)
    whole = bool(run) and len(run) == min(len(wa), len(wb))
    return len(kept) >= (4 if whole else min_chars)


def place_overlap(a: str | None, b: str | None) -> bool:
    """Two venue strings that name one place in different words.

    "John Natsoulas Gallery" / "John Natsoulas Center for the Arts": at least two shared words
    in the name, covering 60% of the shorter name.
    """
    def toks(v: str | None) -> set[str]:
        return set(tokens((v or "").split(",")[0], ())) - PLACE_STOP

    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return False
    shared = ta & tb
    return len(shared) >= 2 and len(shared) / min(len(ta), len(tb)) >= 0.6
