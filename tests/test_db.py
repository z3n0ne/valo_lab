"""Tests for the SQLite storage helpers."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from valorant.db import Database


def _match(match_id, queue_id, is_demo=0, rounds_played=0):
    return {
        "match_id": match_id,
        "started_at": "2026-10-01T00:00:00Z",
        "queue_id": queue_id,
        "queue_name": queue_id,
        "rounds_played": rounds_played,
        "is_demo": is_demo,
        "synced_at": "2026-10-01T00:00:00Z",
    }


def _round(match_id, round_num=1, end_cause=None):
    return {
        "match_id": match_id,
        "round_num": round_num,
        "side": "attack",
        "won": 1,
        "end_cause": end_cause,
    }


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


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"
        self.db = Database(self.path)
        self.db.init_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_end_cause_round_trip(self):
        self.db.upsert_match(_match("m1", "competitive"), [_round("m1", 1, "defuse")])
        rows = self.db.rounds_for(["m1"])["m1"]
        self.assertEqual(rows[0]["end_cause"], "defuse")

    def test_mmr_history_is_upserted_and_filtered(self):
        base = {
            "match_id": "m1",
            "played_at": "2026-10-01T00:00:00Z",
            "rr": 40,
            "last_change": 20,
            "elo": 1500,
            "tier_id": 1,
            "tier_name": "Diamond 1",
            "map_id": "ascent",
            "map_name": "Ascent",
            "season_id": "s1",
            "season_short": "S1",
            "is_demo": 0,
            "synced_at": "2026-10-01T00:00:00Z",
        }
        demo = dict(base, match_id="d1", is_demo=1)
        self.assertEqual(self.db.upsert_mmr_history([base, demo]), 2)
        updated = dict(base, rr=60, last_change=20)
        self.db.upsert_mmr_history([updated])

        self.assertEqual(self.db.count_mmr_history(), 2)
        self.assertEqual(self.db.count_mmr_history(demo=False), 1)
        self.assertEqual(self.db.count_mmr_history(demo=True), 1)
        rows = self.db.query_mmr_history(days=0, demo=False)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rr"], 60)

    def test_deleting_demo_also_removes_demo_rr_history(self):
        self.db.upsert_match(_match("demo", "competitive", is_demo=1), [])
        self.db.upsert_match(_match("real", "competitive"), [])
        self.db.upsert_mmr_history(
            [
                {"match_id": "demo", "played_at": "2026-10-01T00:00:00Z", "is_demo": 1, "synced_at": "2026-10-01T00:00:00Z"},
                {"match_id": "real", "played_at": "2026-10-01T00:00:00Z", "is_demo": 0, "synced_at": "2026-10-01T00:00:00Z"},
            ]
        )
        self.assertEqual(self.db.delete_demo(), 1)
        self.assertEqual(self.db.count_mmr_history(demo=True), 0)
        self.assertEqual(self.db.count_mmr_history(demo=False), 1)

    def test_missing_end_cause_matches_are_detected(self):
        self.db.upsert_match(
            _match("m1", "competitive", rounds_played=2),
            [_round("m1", 1, None), _round("m1", 2, "defuse")],
        )
        self.db.upsert_match(
            _match("m2", "competitive", rounds_played=1),
            [_round("m2", 1, "detonation")],
        )
        self.db.upsert_match(
            _match("m3", "unrated", rounds_played=1),
            [_round("m3", 1, None)],
        )
        self.db.upsert_match(
            _match("demo", "competitive", is_demo=1, rounds_played=1),
            [_round("demo", 1, None)],
        )
        self.assertEqual(self.db.match_ids_missing_end_cause(queue_mode="competitive"), ["m1"])
        self.assertEqual(
            set(self.db.match_ids_missing_end_cause(queue_mode="tactical")),
            {"m1", "m3"},
        )


class MigrationTests(unittest.TestCase):
    def test_old_rounds_table_gets_the_end_cause_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE rounds (
                    match_id TEXT NOT NULL,
                    round_num INTEGER NOT NULL,
                    side TEXT,
                    won INTEGER NOT NULL DEFAULT 0,
                    kills INTEGER NOT NULL DEFAULT 0,
                    deaths INTEGER NOT NULL DEFAULT 0,
                    assists INTEGER NOT NULL DEFAULT 0,
                    score INTEGER NOT NULL DEFAULT 0,
                    damage INTEGER NOT NULL DEFAULT 0,
                    headshots INTEGER NOT NULL DEFAULT 0,
                    bodyshots INTEGER NOT NULL DEFAULT 0,
                    legshots INTEGER NOT NULL DEFAULT 0,
                    first_blood_mine INTEGER NOT NULL DEFAULT 0,
                    first_death_mine INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (match_id, round_num)
                );
                """
            )
            conn.commit()
            conn.close()

            db = Database(path)
            db.init_schema()
            with db.connect() as check:
                columns = {row["name"] for row in check.execute("PRAGMA table_info(rounds)")}
            self.assertIn("end_cause", columns)


if __name__ == "__main__":
    unittest.main()
