"""Tests for the deterministic demo dataset."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from valorant.db import Database
from valorant.demo import seed_demo


def _score_is_valid(mine, enemy):
    best, worst = max(mine, enemy), min(mine, enemy)
    if best == 13:
        return 0 <= worst <= 11
    if best > 13:
        return worst == best - 2
    return False


class DemoDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "demo.db")
        self.db.init_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_creates_a_full_dataset(self):
        added = seed_demo(self.db)
        self.assertEqual(added, 90)
        self.assertEqual(self.db.count_matches(demo=True), 90)
        self.assertEqual(self.db.count_matches(demo=False), 0)
        self.assertTrue(self.db.has_demo())

    def test_seed_is_disabled_once_data_exists(self):
        seed_demo(self.db)
        self.assertEqual(seed_demo(self.db), 0)
        self.assertEqual(self.db.count_matches(), 90)

    def test_seed_respects_the_dismissed_flag(self):
        self.db.set_meta("demo_dismissed", True)
        self.assertEqual(seed_demo(self.db), 0)

    def test_scores_follow_valorant_rules(self):
        seed_demo(self.db)
        matches = self.db.query_matches(mode="all", days=0)
        self.assertEqual(len(matches), 90)
        for match in matches:
            with self.subTest(match=match["match_id"]):
                self.assertTrue(
                    _score_is_valid(match["score_mine"], match["score_enemy"]),
                    f"invalid score {match['score_mine']}-{match['score_enemy']}",
                )

    def test_every_match_has_rounds_and_both_sides(self):
        seed_demo(self.db)
        matches = self.db.query_matches(mode="all", days=0)
        rounds = self.db.rounds_for([m["match_id"] for m in matches])
        for match in matches:
            with self.subTest(match=match["match_id"]):
                played = rounds.get(match["match_id"], [])
                self.assertTrue(played)
                self.assertEqual(len(played), match["rounds_played"])
                sides = {row["side"] for row in played}
                self.assertEqual(sides, {"attack", "defense"})
                wins = sum(row["won"] for row in played)
                self.assertEqual(wins, match["score_mine"])

    def test_no_match_is_in_the_future(self):
        seed_demo(self.db)
        latest = self.db.latest_match_at()
        self.assertIsNotNone(latest)
        parsed = datetime.strptime(latest, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.assertLessEqual(parsed, datetime.now(timezone.utc))

    def test_demo_is_deterministic(self):
        seed_demo(self.db)
        with tempfile.TemporaryDirectory() as other:
            second = Database(Path(other) / "demo.db")
            second.init_schema()
            seed_demo(second)
            first_rows = sorted(
                (m["map_name"], m["agent_name"], m["score_mine"], m["score_enemy"], m["kills"], m["deaths"])
                for m in self.db.query_matches(mode="all", days=0)
            )
            second_rows = sorted(
                (m["map_name"], m["agent_name"], m["score_mine"], m["score_enemy"], m["kills"], m["deaths"])
                for m in second.query_matches(mode="all", days=0)
            )
        self.assertEqual(first_rows, second_rows)

    def test_demo_only_contains_competitive_matches(self):
        seed_demo(self.db)
        matches = self.db.query_matches(mode="all", days=0)
        self.assertTrue(matches)
        self.assertEqual({m["queue_id"] for m in matches}, {"competitive"})
        self.assertEqual({m["queue_name"] for m in matches}, {"Competitive"})

    def test_demo_profile_is_flagged(self):
        seed_demo(self.db)
        profile = self.db.get_meta("profile") or {}
        self.assertTrue(profile.get("demo"))
        self.assertEqual(profile.get("name"), "DemoPlayer")

    def test_delete_demo_clears_everything(self):
        seed_demo(self.db)
        removed = self.db.delete_demo()
        self.assertEqual(removed, 90)
        self.assertEqual(self.db.count_matches(), 0)
        self.assertFalse(self.db.has_demo())


if __name__ == "__main__":
    unittest.main()
