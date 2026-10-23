import io
import json
import random
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from eventdedupe import Config, dedupe, explain, groups, same_event
from eventdedupe import _text
from eventdedupe.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "listings.jsonl"


def ev(title, start=None, venue=None, source=None, date="2026-10-18", **kw):
    return {"title": title, "date": date, "start": start, "venue": venue, "source": source, **kw}


class CrossSourceTimes(unittest.TestCase):
    def test_early_and_late_show_stay_apart(self):
        # Without the session words this would pass as doors-vs-show (90 min, one title starts
        # the other, two sources).
        a = ev("Comedy Night at The Independent", "2026-10-18T19:00:00-07:00", "The Independent", "club")
        b = ev("Comedy Night at The Independent - Late Show", "2026-10-18T20:30:00-07:00",
               "The Independent", "tickets")
        d = explain(a, b)
        self.assertFalse(d["match"])
        self.assertIn("different sessions", d["reason"])
        self.assertEqual(_text.session_marker("Jazz Brunch (2nd Seating)"), "2nd seating")
        self.assertEqual(_text.session_marker("Quartet - Set 2"), "set 2")
        self.assertIsNone(_text.session_marker("Showcase Settlers Night"))

    def test_ampm_flip(self):
        a = ev("Sunrise Yoga on the Beach", "2026-10-18T06:30:00-07:00", "Ocean Beach", "studio")
        b = ev("Sunrise Yoga on the Beach", "2026-10-18T18:30:00-07:00", "Ocean Beach", "listings")
        self.assertEqual(explain(a, b)["rule"], "ampm_flip")

    def test_ampm_flip_needs_a_specific_title(self):
        a = ev("Zumba", "2026-10-18T06:30:00-07:00", "Ocean Beach", "studio")
        b = ev("Zumba", "2026-10-18T18:30:00-07:00", "Ocean Beach", "listings")
        self.assertFalse(same_event(a, b))

    def test_ampm_flip_can_be_turned_off(self):
        a = ev("Sunrise Yoga on the Beach", "2026-10-18T06:30:00-07:00", "Ocean Beach", "studio")
        b = ev("Sunrise Yoga on the Beach", "2026-10-18T18:30:00-07:00", "Ocean Beach", "listings")
        self.assertFalse(same_event(a, b, config=Config(ampm_flip=False)))

    def test_hour_drift_across_sources(self):
        a = ev("Harvest Moon Lantern Walk", "2026-10-18T18:00:00-07:00", "Botanical Garden", "garden")
        b = ev("Harvest Moon Lantern Walk", "2026-10-18T19:00:00-07:00", "Botanical Garden", "listings")
        self.assertEqual(explain(a, b)["rule"], "time_drift")

    def test_doors_vs_show(self):
        a = ev("Velvet Lanterns", "2026-10-18T19:00:00-07:00", "The Chapel", "venue")
        b = ev("Velvet Lanterns with Glass Harbor and Dune Choir", "2026-10-18T20:00:00-07:00",
               "The Chapel, 777 Valencia St", "tickets")
        self.assertEqual(explain(a, b)["rule"], "doors_vs_show")

    def test_same_source_twice_is_two_sessions(self):
        a = ev("Historic Chinatown Walking Tour", "2026-10-18T10:00:00-07:00", "Portsmouth Square", "tours")
        b = ev("Historic Chinatown Walking Tour", "2026-10-18T11:15:00-07:00", "Portsmouth Square", "tours")
        d = explain(a, b)
        self.assertFalse(d["match"])
        self.assertIn("same source", d["reason"])

    def test_relaxed_time_rules_need_a_source_field(self):
        # Without `source`, an hour apart at one venue is an early and a late show.
        a = ev("Late Night Laughs Comedy Showcase", "2026-10-18T19:00:00-04:00", "Cellar Comedy Club")
        b = ev("Late Night Laughs Comedy Showcase", "2026-10-18T20:15:00-04:00", "Cellar Comedy Club")
        self.assertFalse(same_event(a, b))

    def test_different_venues_block_the_time_rules(self):
        a = ev("Sunrise Yoga on the Beach", "2026-10-18T06:30:00-07:00", "Ocean Beach", "studio")
        b = ev("Sunrise Yoga on the Beach", "2026-10-18T18:30:00-07:00", "Crissy Field", "listings")
        self.assertFalse(same_event(a, b))


class SameVenueRules(unittest.TestCase):
    def test_shared_headliner(self):
        a = ev("Marigold Echo - Northern Lights Tour", "2026-10-18T20:00:00-07:00", "Fillmore Auditorium", "tickets")
        b = ev("Marigold Echo with Pale Season", "2026-10-18T20:00:00-07:00", "The Fillmore Auditorium", "venue")
        self.assertEqual(explain(a, b)["rule"], "headliner")

    def test_generic_lead_words_are_not_a_headliner(self):
        self.assertFalse(_text.shared_headliner("Live Jazz Night: Trio Uno", "Live Jazz Night: Big Band"))

    def test_recurring_lead_in(self):
        a = ev("SalsaCrazy Saturday - Dance Lessons and Social", "2026-10-18T21:00:00-07:00", "Verdi Club")
        b = ev("Salsa Crazy Saturday - Best Dance Party in Town!", "2026-10-18T21:00:00-07:00",
               "Verdi Club, 2424 Mariposa St")
        self.assertEqual(explain(a, b)["rule"], "lead_in")

    def test_venue_name_prefix(self):
        a = ev("Birdland Latin Jazz Orchestra", venue="Birdland")
        b = ev("BIRDLAND LATIN JAZZ ORCHESTRA", venue="Birdland Jazz Club, 315 W 44th St")
        self.assertTrue(same_event(a, b))
        self.assertFalse(_text.venue_prefix_match(["pier"], ["pier", "70"]))

    def test_place_named_in_different_words(self):
        a = ev("Fall Group Exhibition Opening Reception", venue="John Natsoulas Gallery")
        b = ev("Fall Group Exhibition Opening Reception", venue="John Natsoulas Center for the Arts")
        self.assertEqual(explain(a, b)["rule"], "place_overlap")

    def test_short_generic_title_at_different_venues(self):
        a = ev("ZUMBA®", "2026-10-18T18:00:00-07:00", "Salesforce Park", "park")
        b = ev("Zumba!", "2026-10-18T18:00:00-07:00", "Marin Dance Hall", "meetups")
        self.assertFalse(same_event(a, b))


class Sports(unittest.TestCase):
    def test_vs_and_at_are_one_game(self):
        a = ev("Bay City Bears vs. Harbor Town Hawks", "2026-10-18T13:05:00-07:00", "Bayside Park", "team")
        b = ev("Harbor Town Hawks at Bay City Bears", "2026-10-18T13:00:00-07:00", None, "tickets")
        self.assertEqual(explain(a, b)["rule"], "sports_matchup")

    def test_plural_and_singular_team_names(self):
        a = ev("New York Red Bulls v Seattle Sounders", source="a")
        b = ev("Seattle Sounders FC vs Red Bull New York", source="b")
        self.assertTrue(same_event(a, b))

    def test_doubleheader_stays_two_games(self):
        a = ev("Bay City Bears vs Harbor Town Hawks", "2026-10-18T13:05:00-07:00", "Bayside Park", "team")
        b = ev("Bay City Bears vs Harbor Town Hawks - Game 2", "2026-10-18T18:10:00-07:00", "Bayside Park", "team")
        self.assertFalse(same_event(a, b))

    def test_watch_party_is_not_the_game(self):
        a = ev("Bay City Bears vs Harbor Town Hawks", "2026-10-18T13:00:00-07:00", source="team")
        b = ev("Bay City Bears vs Harbor Town Hawks Watch Party", "2026-10-18T13:00:00-07:00", source="bar")
        self.assertFalse(same_event(a, b))

    def test_show_at_a_venue_is_not_a_game(self):
        # "X at Y" without "vs" or a sport word is a show at a venue, not a matchup.
        from eventdedupe._sports import same_matchup
        self.assertFalse(same_matchup("Comedy Night at The Independent",
                                      "The Independent at Comedy Night"))
        self.assertTrue(same_matchup("Hawks at Bears", "Bears vs Hawks"))
        c = ev("Open Mic at The Rusty Pub", "2026-10-18T19:00:00-07:00")
        d = ev("Open Mic at The Rusty Pub", "2026-10-18T20:15:00-07:00")
        self.assertFalse(same_event(c, d))

    def test_at_with_a_sport_word_is_a_game(self):
        a = ev("Harbor Town Hawks at Bay City Bears Baseball", "2026-10-18T13:00:00-07:00", source="a")
        b = ev("Bay City Bears Baseball at Harbor Town Hawks", "2026-10-18T13:10:00-07:00", source="b")
        self.assertEqual(explain(a, b)["rule"], "sports_matchup")

    def test_different_sport_or_gender(self):
        a = ev("State Hockey vs Tech Hockey", source="a")
        b = ev("State Basketball vs Tech Basketball", source="b")
        self.assertFalse(same_event(a, b))
        c = ev("State Men's Soccer vs Tech", source="a")
        d = ev("State Women's Soccer vs Tech", source="b")
        self.assertFalse(same_event(c, d))

    def test_team_names_spelled_differently(self):
        a = ev("Boston College Eagles Hockey vs. St. Cloud State Huskies Hockey", source="tickets")
        b = ev("Boston College Men's Hockey vs St Cloud State", source="team")
        self.assertEqual(explain(a, b)["rule"], "sports_matchup")
        self.assertFalse(same_event(a, b, config=Config(sports=False)))


class Times(unittest.TestCase):
    def test_offsets_compare_by_instant(self):
        a = ev("Global Product Launch Livestream", "2026-10-18T20:00:00-07:00", "Online")
        b = ev("Global Product Launch Livestream", "2026-10-19T03:00:00Z", "Online", date=None)
        self.assertEqual(explain(a, b)["start_gap_minutes"], 0.0)
        self.assertTrue(same_event(a, b))
        self.assertEqual(len(dedupe([a, b])), 1)  # across the midnight between their local dates

    def test_compact_offset_and_naive_wall_clock(self):
        a = ev("Silent Disco", "2026-10-18T20:00:00+0200", "Pier 39")
        b = ev("Silent Disco", "2026-10-18 20:10", "Pier 39")
        self.assertEqual(explain(a, b)["start_gap_minutes"], 10.0)

    def test_date_comes_from_start_when_missing(self):
        a = {"title": "Ferry Plaza Farmers Market", "start": "2026-10-18T08:00:00-07:00", "venue": "Ferry Building"}
        b = {"title": "Ferry Plaza Farmers Market", "date": "2026-10-18", "venue": "Ferry Building"}
        self.assertTrue(same_event(a, b))


class Explain(unittest.TestCase):
    def test_reports_evidence(self):
        a = ev("Open Mic Night", venue="The Bitter End")
        b = ev("Open Mic Night", venue="Sour Mouse")
        d = explain(a, b)
        self.assertEqual(set(d), {"match", "rule", "reason", "dates", "start_gap_minutes", "same_source",
                                  "title_similarity", "venue_similarity", "distance_km"})
        self.assertFalse(d["match"])
        self.assertIsNone(d["rule"])
        self.assertEqual(d["reason"], "different venues")
        self.assertEqual(d["title_similarity"], 1.0)
        self.assertLess(d["venue_similarity"], 0.8)

    def test_different_dates_reason(self):
        self.assertEqual(explain(ev("Market", date="2026-10-18"), ev("Market", date="2026-10-25"))["reason"],
                         "different dates")

    def test_dedupe_explain_matches(self):
        a = ev("Climate Data Hackathon", venue="Civic Center Library", link="https://a.example")
        b = ev("Climate Data Hackathon 2026", venue="Civic Center Library, Room 4", link="https://b.example")
        (merged,) = dedupe([a, b], explain_matches=True)
        self.assertEqual(merged["_matches"], [{"pair": [0, 1], "rule": "title_venue",
                                               "reason": "similar title at the same venue"}])


class Shapes(unittest.TestCase):
    def test_schema_org_event(self):
        a = {"@type": "Event", "name": "Midnight Movie: The Lost Reel", "startDate": "2026-10-18T23:59:00-07:00",
             "location": {"@type": "Place", "name": "Roxie Theatre"}, "url": "https://roxie.example/r"}
        b = {"title": "Midnight Movie - The Lost Reel", "start": "2026-10-18T23:59:00-07:00",
             "venue": "Roxie Theater", "link": "https://listings.example/r"}
        (merged,) = dedupe([a, b])
        self.assertEqual(merged["links"], ["https://roxie.example/r", "https://listings.example/r"])
        self.assertEqual(merged["duplicates"], 1)

    def test_key_map_with_dotted_path(self):
        a = {"headline": "Author Talk: Rivers of the West", "when": "2026-10-18T18:30:00-07:00",
             "place": {"label": "Green Apple Books"}, "href": "https://a.example"}
        b = dict(a, href="https://b.example", place={"label": "Green Apple Books, 506 Clement St"})
        key_map = {"title": "headline", "start": "when", "venue": "place.label", "link": "href"}
        self.assertEqual(groups([a, b], key_map=key_map), [[0, 1]])
        self.assertEqual(dedupe([a, b], key_map=key_map)[0]["links"], ["https://a.example", "https://b.example"])

    def test_config_thresholds(self):
        a = ev("Midnight Poetry Slam", venue="Blue Note")
        b = ev("Poetry Slam Afterparty", venue="Blue Note")
        self.assertFalse(same_event(a, b))
        self.assertTrue(same_event(a, b, config=Config(title_match=0.6)))


class Fixture(unittest.TestCase):
    def test_fifty_listings_group_as_labelled(self):
        events = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]
        expected = {}
        for i, e in enumerate(events):
            expected.setdefault(e["_group"], []).append(i)
        self.assertEqual(len(events), 50)
        self.assertEqual(sorted(groups(events)), sorted(expected.values()))

    def test_fast_mode_agrees_on_the_fixture(self):
        try:
            import rapidfuzz  # noqa: F401
        except ImportError:
            self.skipTest("rapidfuzz not installed")
        events = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]
        self.assertEqual(groups(events, config=Config(fast=True)), groups(events))

    def test_five_thousand_listings_stay_fast(self):
        # ~180 listings a day for 28 days, a busy city's calendar.
        rng = random.Random(7)
        words = ("jazz salsa poetry market film comedy yoga trivia lecture tour gallery opening family "
                 "festival workshop concert brunch hackathon karaoke cinema choir orchestra").split()
        places = ("Blue Note|Civic Center|Mission Pub|Ferry Building|Verdi Club|Roxie Theater|The Chapel|"
                  "Golden Gate Park|Public Library|Clay Studio|Fillmore Auditorium|Pier 39").split("|")
        events = []
        for i in range(5000):
            day = f"2026-10-{1 + i % 28:02d}"
            events.append(ev(" ".join(rng.sample(words, 3)).title(), f"{day}T{rng.randrange(8, 23):02d}:00:00-07:00",
                             rng.choice(places), f"s{i % 5}", date=day))
        t = time.perf_counter()
        groups(events)
        self.assertLess(time.perf_counter() - t, 20)


class Links(unittest.TestCase):
    def test_same_page_same_time_is_one_event(self):
        a = ev("Fall Makers Market", "2026-10-18T10:00:00-07:00", "Fort Mason", "venue",
               link="https://www.example.org/events/fall-makers-market/?utm_source=x")
        b = ev("Makers Market: Fall Edition at Fort Mason Center", "2026-10-18T10:00:00-07:00", None, "agg",
               link="https://example.org/events/fall-makers-market#tickets")
        self.assertEqual(explain(a, b)["rule"], "same_link")

    def test_same_page_different_times_stays_apart(self):
        link = "https://tickets.example.com/e/late-night-laughs-123"
        a = ev("Late Night Laughs", "2026-10-18T19:00:00-07:00", "Cobb's", "a", link=link)
        b = ev("Late Night Laughs", "2026-10-18T21:30:00-07:00", "Cobb's", "a", link=link)
        self.assertFalse(same_event(a, b))

    def test_listing_pages_and_site_roots_are_not_evidence(self):
        from eventdedupe._signals import canonical_link
        self.assertIsNone(canonical_link("https://venue.example.com/"))
        self.assertIsNone(canonical_link("https://venue.example.com/events/"))
        self.assertIsNone(canonical_link("mailto:hi@example.com"))
        self.assertEqual(canonical_link("HTTPS://WWW.Example.com/e/1/?fbclid=z&b=2&a=1"),
                         "example.com/e/1?a=1&b=2")
        a = ev("Jazz Jam", "2026-10-18T20:00:00-07:00", None, "a", link="https://club.example.com/calendar")
        b = ev("Poetry Slam", "2026-10-18T20:00:00-07:00", None, "b", link="https://club.example.com/calendar")
        self.assertFalse(same_event(a, b))

    def test_links_can_be_switched_off(self):
        a = ev("Fall Makers Market", "2026-10-18T10:00:00-07:00", link="https://x.example/e/1")
        b = ev("Makers Market: Fall Edition at Fort Mason Center", "2026-10-18T10:00:00-07:00",
               link="https://x.example/e/1")
        self.assertEqual(explain(a, b)["rule"], "same_link")
        self.assertFalse(same_event(a, b, config=Config(links=False)))

    def test_shared_profile_link_needs_related_titles(self):
        link = "https://www.instagram.com/some_venue/"
        a = ev("Open Projector Night", "2026-10-18T18:00:00-07:00", None, "a", link=link)
        b = ev("Tinker Night", "2026-10-18T18:00:00-07:00", None, "b", link=link)
        self.assertFalse(same_event(a, b))

    def test_program_page_shared_by_different_places(self):
        # One parks-department page lists the same class at many recreation centers.
        link = "https://sfrecpark.org/1183/Zumba-in-the-Parks"
        a = ev("Zumba - Mission Playground", "2026-10-30T18:30:00-07:00", "Mission Playground", "a", link=link)
        b = ev("Zumba - Cayuga Playground", "2026-10-30T18:30:00-07:00", "Cayuga Playground", "a", link=link)
        self.assertFalse(same_event(a, b))

    def test_hash_routed_calendars_keep_the_route(self):
        from eventdedupe._signals import canonical_link
        a = canonical_link("https://www.mercurynews.com/event-calendar#/details/open-mic/123")
        b = canonical_link("https://www.mercurynews.com/event-calendar#/details/salsa-night/456")
        self.assertNotEqual(a, b)
        self.assertEqual(a, "mercurynews.com/event-calendar#/details/open-mic/123")
        self.assertIsNone(canonical_link("https://www.mercurynews.com/event-calendar"))


class Coordinates(unittest.TestCase):
    def test_close_points_confirm_differently_named_venues(self):
        a = ev("Harvest Lantern Walk", "2026-10-18T18:00:00-07:00", "Botanical Garden", "a", lat=37.7678, lon=-122.4686)
        b = ev("Harvest Lantern Walk", "2026-10-18T18:00:00-07:00", "SF Botanical Garden at Strybing",
               "b", lat=37.7680, lon=-122.4690)
        self.assertIn(explain(a, b)["rule"], ("title_venue", "title_coordinates"))
        c = ev("Harvest Lantern Walk", "2026-10-18T18:00:00-07:00", "Strybing Arboretum", "b",
               lat=37.7680, lon=-122.4690)
        d = explain(a, c)
        self.assertEqual(d["rule"], "title_coordinates")
        self.assertLess(d["distance_km"], 0.15)

    def test_far_points_block_a_title_only_merge(self):
        a = ev("Community Yoga in the Park", "2026-10-18T09:00:00-07:00", None, "a", lat=37.7694, lon=-122.4862)
        b = ev("Community Yoga in the Park", "2026-10-18T09:00:00-07:00", "Dolores Park", "b",
               lat=37.7596, lon=-122.4269)
        d = explain(a, b)
        self.assertFalse(d["match"])
        self.assertIn("km apart", d["reason"])

    def test_agreeing_venue_names_beat_a_bad_geocode(self):
        a = ev("Fall Gala", "2026-10-18T19:00:00-07:00", "Palace of Fine Arts", "a", lat=37.8029, lon=-122.4484)
        b = ev("Fall Gala", "2026-10-18T19:00:00-07:00", "Palace of Fine Arts", "b", lat=37.7749, lon=-122.4194)
        self.assertEqual(explain(a, b)["rule"], "title_venue")

    def test_schema_org_geo_and_null_island(self):
        from eventdedupe._signals import coordinates
        self.assertEqual(coordinates(None, None, {"geo": {"latitude": "40.7", "longitude": "-74.0"}}), (40.7, -74.0))
        self.assertIsNone(coordinates(0, 0, None))


class AttendanceMode(unittest.TestCase):
    def test_online_never_merges_with_in_person(self):
        a = ev("Intro to Pottery Q&A", "2026-10-18T18:00:00-07:00", "Online", "a")
        b = ev("Intro to Pottery Q&A", "2026-10-18T18:00:00-07:00", None, "b",
               eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode")
        self.assertEqual(explain(a, b)["reason"], "one listing is online, the other in person")

    def test_venue_names_with_online_words_stay_physical(self):
        from eventdedupe._signals import attendance_mode
        self.assertIsNone(attendance_mode(None, None, "Zoom Room Bar"))
        self.assertIsNone(attendance_mode(None, None, "Virtual Reality Arcade"))
        self.assertEqual(attendance_mode(None, None, "Online (link after RSVP)"), "online")

    def test_mixed_merges_with_either(self):
        a = ev("City Budget Town Hall", "2026-10-18T18:00:00-07:00", "Zoom", "a")
        b = ev("City Budget Town Hall", "2026-10-18T18:00:00-07:00", None, "b", eventAttendanceMode="MixedEventAttendanceMode")
        self.assertTrue(same_event(a, b))


class Status(unittest.TestCase):
    def test_cancelled_title_still_matches_and_the_merge_keeps_it(self):
        a = ev("Moonlight Cinema: Jaws", "2026-10-18T19:30:00-07:00", "Dolores Park", "a", status="EventScheduled")
        b = ev("CANCELLED: Moonlight Cinema - Jaws", "2026-10-18T19:30:00-07:00", "Dolores Park", "b")
        merged = dedupe([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["status"], "cancelled")

    def test_worst_status_field_wins(self):
        a = ev("Bay Lights Run", "2026-10-18T08:00:00-07:00", "Embarcadero", "a",
               eventStatus="https://schema.org/EventPostponed")
        b = ev("Bay Lights Run", "2026-10-18T08:00:00-07:00", "Embarcadero", "b",
               eventStatus="https://schema.org/EventScheduled")
        merged = dedupe([b, a])
        self.assertEqual(merged[0]["eventStatus"], "https://schema.org/EventPostponed")

    def test_scheduled_everywhere_adds_nothing(self):
        a = ev("Bay Lights Run", "2026-10-18T08:00:00-07:00", "Embarcadero", "a")
        b = ev("Bay Lights Run", "2026-10-18T08:00:00-07:00", "Embarcadero", "b")
        self.assertNotIn("status", dedupe([a, b])[0])


class Presets(unittest.TestCase):
    def test_strict_and_lenient(self):
        a = ev("Velvet Lanterns", "2026-10-18T19:00:00-07:00", "The Chapel", "a")
        b = ev("Velvet Lanterns with Glass Harbor", "2026-10-18T20:00:00-07:00", "The Chapel", "b")
        self.assertTrue(same_event(a, b))
        self.assertFalse(same_event(a, b, config=Config.strict()))
        self.assertEqual(Config.lenient().time_tolerance_min, 60)
        self.assertEqual(Config.strict(title_match=0.95).title_match, 0.95)


class Cli(unittest.TestCase):
    def run_cli(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_jsonl_round_trip_with_explain(self):
        code, out, err = self.run_cli([str(FIXTURE), "--explain"])
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(len(rows), len({json.loads(l)["_group"] for l in FIXTURE.read_text(encoding="utf-8").splitlines()}))
        self.assertIn("_matches", rows[0])
        self.assertIn("50 listings ->", err)

    def test_json_array_and_key_option(self):
        import tempfile, os
        data = [{"headline": "Wheel Throwing for Beginners", "day": "2026-10-18", "url": "https://a.example"},
                {"headline": "Wheel Throwing for Beginners", "day": "2026-10-18", "url": "https://b.example"}]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
        try:
            code, out, _ = self.run_cli([f.name, "--key", "title=headline", "--key", "date=day"])
        finally:
            os.unlink(f.name)
        merged = json.loads(out)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["links"], ["https://a.example", "https://b.example"])


if __name__ == "__main__":
    unittest.main()
