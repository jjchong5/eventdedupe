import unittest

from eventdedupe import dedupe, same_event, similarity, tokens


def ev(title, date="2026-10-18", start=None, venue=None, link=None, **kw):
    return {"title": title, "date": date, "start": start, "venue": venue, "link": link, **kw}


class Tokens(unittest.TestCase):
    def test_accents_case_punctuation_and_noise(self):
        self.assertEqual(tokens("The Café Tacvba — LIVE!"), ["cafe", "tacvba"])

    def test_ampersand_reads_as_and(self):
        self.assertEqual(tokens("Salt & Pepper"), tokens("Salt and Pepper"))

    def test_apostrophes_join(self):
        self.assertEqual(tokens("Rock'n'Roll Night"), ["rocknroll", "night"])


class Similarity(unittest.TestCase):
    def test_word_order_does_not_matter(self):
        self.assertGreater(similarity(tokens("Jazz Orchestra Latin"), tokens("Latin Jazz Orchestra")), 0.99)

    def test_containment_needs_two_tokens(self):
        # "Trivia" alone must not swallow every trivia night in town.
        self.assertLess(similarity(tokens("Trivia"), tokens("Harry Potter Trivia Championship")), 0.85)
        self.assertEqual(similarity(tokens("Jazz Jam"), tokens("Sunday Jazz Jam and Open Mic")), 1.0)


class SameEvent(unittest.TestCase):
    def test_same_show_different_spelling(self):
        a = ev("The Birdland Latin Jazz Orchestra", start="2026-10-18T17:30:00-04:00",
               venue="Birdland Jazz Club, 315 W 44th St, New York")
        b = ev("BIRDLAND LATIN JAZZ ORCHESTRA", start="2026-10-18T17:30:00-04:00",
               venue="Birdland Jazz Club")
        self.assertTrue(same_event(a, b))

    def test_early_and_late_show_stay_apart(self):
        a = ev("Comedy Cellar Lineup", start="2026-10-18T19:00:00-04:00", venue="Comedy Cellar")
        b = ev("Comedy Cellar Lineup", start="2026-10-18T21:30:00-04:00", venue="Comedy Cellar")
        self.assertFalse(same_event(a, b))

    def test_small_clock_drift_is_tolerated(self):
        a = ev("Silent Disco", start="2026-10-18T20:00:00-07:00", venue="Pier 39")
        b = ev("Silent Disco", start="2026-10-18T20:30:00-07:00", venue="Pier 39")
        self.assertTrue(same_event(a, b))

    def test_different_dates(self):
        self.assertFalse(same_event(ev("Farmers Market", "2026-10-18"), ev("Farmers Market", "2026-10-25")))

    def test_different_venues(self):
        a = ev("Open Mic Night", venue="The Bitter End")
        b = ev("Open Mic Night", venue="Sour Mouse")
        self.assertFalse(same_event(a, b))

    def test_missing_venue_needs_a_closer_title(self):
        with_venue = ev("Autumn Lantern Festival", venue="Botanical Garden")
        self.assertTrue(same_event(with_venue, ev("Autumn Lantern Festival")))
        self.assertFalse(same_event(with_venue, ev("Autumn Lantern Festival Kids Workshop")))

    def test_all_day_listing_matches_a_timed_one(self):
        a = ev("Monk Festival: James Francies Trio", venue="Smoke Jazz Club")
        b = ev("Monk Festival - James Francies Trio", start="2026-10-18T19:00:00-04:00",
               venue="Smoke Jazz Club, New York, NY")
        self.assertTrue(same_event(a, b))


class Dedupe(unittest.TestCase):
    def test_merge_keeps_every_link_and_the_richest_fields(self):
        events = [
            ev("Ekep Nkwelle", venue="Dizzy's Club", link="https://venue.example/ekep"),
            ev("EKEP NKWELLE", start="2026-10-18T19:30:00-04:00",
               venue="Dizzy's Club, Jazz at Lincoln Center", link="https://tickets.example/123",
               price="$45", first_seen="2026-10-02"),
            ev("Ekep Nkwelle (live)", venue="Dizzys Club", link="https://listings.example/e/9",
               first_seen="2026-09-28"),
            ev("Carole J. Bufford", venue="Birdland Theater", link="https://venue.example/carole"),
        ]
        out = dedupe(events)
        self.assertEqual(len(out), 2)
        ekep, carole = out
        self.assertEqual(ekep["duplicates"], 2)
        self.assertEqual(ekep["price"], "$45")
        self.assertEqual(ekep["start"], "2026-10-18T19:30:00-04:00")
        self.assertEqual(ekep["first_seen"], "2026-09-28")
        self.assertEqual(ekep["links"], [
            "https://venue.example/ekep", "https://tickets.example/123", "https://listings.example/e/9",
        ])
        self.assertEqual(carole["duplicates"], 0)

    def test_matches_are_transitive(self):
        a = ev("Halloween Bar Crawl", venue="Main St")
        b = ev("Halloween Bar Crawl 2026", venue="Main Street")
        c = ev("Halloween Bar Crawl 2026")
        self.assertEqual(len(dedupe([a, b, c])), 1)

    def test_output_order_follows_input(self):
        events = [ev("B event two words"), ev("A event two words", "2026-10-17"), ev("B event two words")]
        self.assertEqual([e["title"] for e in dedupe(events)], ["B event two words", "A event two words"])

    def test_empty(self):
        self.assertEqual(dedupe([]), [])


if __name__ == "__main__":
    unittest.main()
