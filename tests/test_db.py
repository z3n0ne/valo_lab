"""Tests for the SQLite storage helpers."""
import tempfile
import unittest
from pathlib import Path

from valorant.db import Database


def _match(match_id, queue_id, is_demo=0):
    return {
        "match_id": match_id,
        "started_at": "2026-10-01T00:00:00Z",
        "queue_id": queue_id,
        "queue_name": queue_id,
        "is_demo": is_demo,
        "synced_at": "2026-10-01T00:00:00Z",
    }


def _round(match_id):
    return {"match_id": match_id, "round_num": 1, "side": "attack", "won": 1}


class QueueCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.init_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_non_competitive_keeps_ranked_unknown_and_demo_rows(self):
        for match_id, queue_id, is_demo in (
            ("ranked", "competitive", 0),
            ("unrated", "unrated", 0),
            ("deathmatch", "deathmatch", 0),
            ("unknown", "unknown", 0),
            ("demo", "unrated", 1),
        ):
            self.db.upsert_match(_match(match_id, queue_id, is_demo), [_round(match_id)])

        removed = self.db.delete_non_competitive()

        self.assertEqual(removed, 2)
        remaining = {m["match_id"] for m in self.db.query_matches(mode="all", days=0)}
        self.assertEqual(remaining, {"ranked", "unknown", "demo"})
        rounds = self.db.rounds_for(["unrated", "deathmatch"])
        self.assertEqual(rounds, {})

    def test_delete_non_competitive_is_a_noop_without_candidates(self):
        self.db.upsert_match(_match("ranked", "competitive"), [])
        self.assertEqual(self.db.delete_non_competitive(), 0)
        self.assertEqual(self.db.count_matches(), 1)


if __name__ == "__main__":
    unittest.main()
