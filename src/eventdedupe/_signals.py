"""Signals beyond title, time and venue name: event links, coordinates, online vs in person, status."""
from __future__ import annotations

import math
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit

# Query parameters that track a click rather than name a page.
_TRACKING = re.compile(r"^(?:utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|aff|affiliate|source|src)$", re.I)
# Paths that list many events rather than one ("/events", "/calendar/"): sharing one is no evidence.
_LISTING_PATH = re.compile(r"^/?(?:(?:events?|community|city)[-_]?)?(?:events?|calendar|shows?|whats-on|"
                           r"schedule|tickets?|upcoming|concerts?|programs?|activities)?/?$", re.I)


def canonical_link(url: Any) -> str | None:
    """A comparable form of an event page URL, or None when it can't identify one event.

    Lower-cased host without "www.", no fragment (unless it is a "#/route"), no trailing slash, tracking parameters
    (utm_*, fbclid, ref, ...) dropped. A site root or a bare listing path ("/events") is None:
    many events share those pages.
    """
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = parts.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    path = parts.path.rstrip("/")
    # Single-page calendars route by fragment ("/event-calendar#/details/open-mic/123"): there
    # the fragment names the event and must be kept. Any other fragment ("#tickets") is dropped.
    frag = parts.fragment
    route = frag.lstrip("!").rstrip("/") if frag.lstrip("!").startswith("/") else ""
    if route:
        path = f"{path}#{route}"
    elif _LISTING_PATH.match(path):
        return None
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not _TRACKING.match(k)))
    return f"{host}{path}" + (f"?{query}" if query else "")


def _float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def coordinates(lat: Any, lon: Any, location: Any) -> tuple[float, float] | None:
    """(lat, lon) from explicit fields or a schema.org Place's `geo`, or None.

    (0, 0) and out-of-range values are treated as missing: they are almost always a failed geocode.
    """
    if (lat is None or lon is None) and isinstance(location, Mapping):
        geo = location.get("geo")
        if isinstance(geo, Mapping):
            lat, lon = geo.get("latitude"), geo.get("longitude")
    la, lo = _float(lat), _float(lon)
    if la is None or lo is None or (la == 0 and lo == 0) or abs(la) > 90 or abs(lo) > 180:
        return None
    return la, lo


def distance_km(a: tuple[float, float] | None, b: tuple[float, float] | None) -> float | None:
    """Great-circle distance in km, or None if either point is missing."""
    if a is None or b is None:
        return None
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(h)))


# A venue that is nothing but an online marker ("Online", "Zoom", "Virtual event"). Matched against
# the whole name so "Zoom Room Bar" or "Virtual Reality Arcade" stay physical places.
_ONLINE_VENUE = re.compile(r"^\W*(?:online|virtual|zoom|livestream|live\s*stream|webinar|google\s*meet|"
                           r"(?:ms|microsoft)\s*teams)(?:\s+(?:only|event|meeting|session|webinar))?\W*$", re.I)


def attendance_mode(mode: Any, location: Any, venue: str | None) -> str | None:
    """"online", "offline", "mixed" or None (unknown).

    From schema.org eventAttendanceMode (or an attendance_mode field) when present; otherwise a
    VirtualLocation or a venue named "Online"/"Zoom"/"Livestream" means online. A plain venue
    name is not evidence of in person: plenty of online listings carry the host's address.
    """
    if isinstance(mode, str) and mode.strip():
        m = mode.rsplit("/", 1)[-1].lower()
        if "mixed" in m or "hybrid" in m:
            return "mixed"
        if "online" in m or "virtual" in m:
            return "online"
        if "offline" in m or "person" in m:
            return "offline"
    if isinstance(location, list):
        types = {str(x.get("@type", "")).lower() for x in location if isinstance(x, Mapping)}
        if "virtuallocation" in types and "place" in types:
            return "mixed"
        location = location[0] if location else None
    if isinstance(location, Mapping) and str(location.get("@type", "")).lower() == "virtuallocation":
        return "online"
    if venue and _ONLINE_VENUE.match(re.split(r"[,(]", venue, maxsplit=1)[0]):
        return "online"
    return None


def modes_conflict(a: str | None, b: str | None) -> bool:
    """One listing is explicitly online and the other explicitly in person."""
    return {a, b} == {"online", "offline"}


# How bad a status is, for merging: the worst one any source reports wins.
_SEVERITY = {"scheduled": 0, "movedonline": 1, "rescheduled": 2, "postponed": 3, "cancelled": 4}
_TITLE_STATUS = re.compile(r"^\W*(cancell?ed|postponed|rescheduled)\b", re.I)


def status_name(value: Any) -> str | None:
    """"cancelled", "postponed", "rescheduled", "movedonline", "scheduled" or None.

    Accepts schema.org values ("https://schema.org/EventCancelled", "EventPostponed") and
    plain words ("canceled", "Postponed").
    """
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.rsplit("/", 1)[-1].strip().lower().replace("_", "").replace(" ", "")
    v = v[5:] if v.startswith("event") else v
    v = "cancelled" if v in ("canceled", "cancel") else v
    return v if v in _SEVERITY else None


def title_status(title: str | None) -> str | None:
    """A status a title announces up front ("CANCELLED: ...", "Postponed - ..."), or None."""
    m = _TITLE_STATUS.match(title or "")
    if not m:
        return None
    word = m.group(1).lower()
    return "cancelled" if word.startswith("cancel") else word


def severity(name: str | None) -> int:
    return _SEVERITY.get(name or "", -1)
