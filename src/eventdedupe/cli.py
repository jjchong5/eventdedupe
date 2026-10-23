"""eventdedupe command line: JSON or JSON Lines in, merged events out."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from ._core import dedupe


def _read(text: str) -> tuple[list[dict[str, Any]], bool]:
    """Events and whether the input was a JSON array (else JSON Lines)."""
    stripped = text.lstrip()
    if stripped.startswith("["):
        return json.loads(stripped), True
    return [json.loads(line) for line in text.splitlines() if line.strip()], False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="eventdedupe",
        description="Merge duplicate event listings. Reads a JSON array or JSON Lines; "
                    "writes the same format.")
    p.add_argument("input", nargs="?", default="-", help="input file (default: stdin)")
    p.add_argument("-o", "--output", default="-", help="output file (default: stdout)")
    p.add_argument("--explain", action="store_true",
                   help="add _matches to each merged event: which pairs joined and why")
    p.add_argument("--key", action="append", default=[], metavar="FIELD=NAME",
                   help="read FIELD (title, date, start, venue, link, source, first_seen) from "
                        "NAME; dotted paths work, e.g. --key venue=location.name")
    p.add_argument("--version", action="version", version=f"eventdedupe {__version__}")
    args = p.parse_args(argv)

    key_map = {}
    for item in args.key:
        field, sep, name = item.partition("=")
        if not sep or not name:
            p.error(f"--key wants FIELD=NAME, got {item!r}")
        key_map[field.strip()] = name.strip()

    if args.input == "-":
        raw = getattr(sys.stdin, "buffer", None)
        text = raw.read().decode("utf-8-sig") if raw else sys.stdin.read()
    else:
        with open(args.input, encoding="utf-8-sig") as f:
            text = f.read()
    events, is_array = _read(text)
    merged = dedupe(events, key_map=key_map or None, explain_matches=args.explain)

    if is_array:
        out = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    else:
        out = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in merged)
    if args.output == "-":
        raw = getattr(sys.stdout, "buffer", None)
        if raw:  # UTF-8 even on a Windows console code page
            sys.stdout.flush()
            raw.write(out.encode("utf-8"))
            raw.flush()
        else:
            sys.stdout.write(out)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    print(f"{len(events)} listing{'s' * (len(events) != 1)} -> "
          f"{len(merged)} event{'s' * (len(merged) != 1)}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
