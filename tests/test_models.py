import unittest

from playlist_sync.models import artists_match, match_key, norm_title, pick_best, primary_artist
from tests.fakes import am, sp


class NormalizeTests(unittest.TestCase):
    def test_remaster_suffixes_match(self):
        self.assertEqual(norm_title("Here Comes the Sun - Remastered 2009"), norm_title("Here Comes the Sun"))
        self.assertEqual(norm_title("Song (2011 Remaster)"), norm_title("Song"))
        self.assertEqual(norm_title("Song (feat. Someone)"), norm_title("Song"))

    def test_live_and_remix_stay_different(self):
        self.assertNotEqual(norm_title("Song - Live"), norm_title("Song"))
        self.assertNotEqual(norm_title("Song (Remix)"), norm_title("Song"))

    def test_non_latin_titles_survive(self):
        self.assertTrue(norm_title("夜に駆ける"))
        self.assertNotEqual(norm_title("夜に駆ける"), norm_title("群青"))

    def test_primary_artist(self):
        self.assertEqual(primary_artist("Calvin Harris, Dua Lipa"), primary_artist("Calvin Harris & Dua Lipa"))
        self.assertEqual(primary_artist("Beyoncé"), primary_artist("Beyonce"))
        self.assertEqual(primary_artist("The Beatles"), primary_artist("Beatles"))
        self.assertTrue(artists_match("Calvin Harris", "Calvin Harris feat. Dua Lipa"))

    def test_match_key(self):
        self.assertEqual(match_key("Song - Radio Edit", "A, B"), match_key("Song (Radio Edit)", "A & B"))


class PickBestTests(unittest.TestCase):
    def test_text_search_needs_title_and_artist(self):
        src = sp("1", "Song", "Artist")
        self.assertIsNone(pick_best(src, [am(1, "Other Song", "Artist")]))
        self.assertIsNone(pick_best(src, [am(1, "Song", "Someone Else")]))
        self.assertEqual(pick_best(src, [am(1, "Song", "Artist")]).service_id, "1")

    def test_text_search_rejects_far_off_lengths(self):
        src = sp("1", "Song", "Artist", ms=200_000)
        self.assertIsNone(pick_best(src, [am(1, "Song", "Artist", ms=260_000)]))

    def test_isrc_prefers_same_title(self):
        src = sp("1", "Song", "Artist", isrc="X")
        best = pick_best(src, [am(1, "Song (Live Edit)", "Artist", "X"), am(2, "Song", "Artist", "X")], by_isrc=True)
        self.assertEqual(best.service_id, "2")


if __name__ == "__main__":
    unittest.main()
