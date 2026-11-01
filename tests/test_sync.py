"""Tests for the queue filter used by the synchronizer (no network)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from valorant import sync
from valorant.db import Database


def _raw(match_id, queue=None):
    metadata = {"match_id": match_id}
    if queue is not None:
        metadata["queue"] = queue
    return {"metadata": metadata, "players": [{"puuid": "pu"}], "rounds": [{"id": 1}]}


class QueueFilterTests(unittest.TestCase):
    def test_reads_a_dict_queue(self):
        raw = _raw("m1", {"id": "Competitive", "name": "Competitive"})
        self.assertEqual(sync.match_queue_id(raw), "competitive")

    def test_reads_a_string_queue(self):
        self.assertEqual(sync.match_queue_id(_raw("m1", "Unrated")), "unrated")

    def test_missing_queue_is_unknown(self):
        self.assertEqual(sync.match_queue_id(_raw("m1")), "")
        self.assertEqual(sync.match_queue_id({}), "")

    def test_competitive_mode_keeps_only_ranked(self):
        self.assertTrue(sync.keep_queue(_raw("m1", {"id": "competitive"}), "competitive"))
        self.assertFalse(sync.keep_queue(_raw("m1", {"id": "unrated"}), "competitive"))
        self.assertFalse(sync.keep_queue(_raw("m1", {"id": "deathmatch"}), "competitive"))

    def test_unknown_queue_is_deferred_to_the_detail_payload(self):
        self.assertTrue(sync.keep_queue(_raw("m1"), "competitive"))

    def test_tactical_mode_keeps_every_queue(self):
        for queue in ("competitive", "unrated", "deathmatch"):
            with self.subTest(queue=queue):
                self.assertTrue(sync.keep_queue(_raw("m1", {"id": queue}), "tactical"))


class FakeClient:
    def __init__(self, pages, detail=None, history=None):
        self.pages = pages
        self.detail = detail or {}
        self.history = history or []
        self.match_calls = []

    def account(self, name, tag):
        return {"name": name, "tag": tag, "puuid": "pu-1", "region": "eu", "account_level": 1}

    def mmr(self, region, platform, name, tag):
        return {}

    def mmr_history(self, region, platform, name, tag):
        return self.history

    def matches(self, region, platform, name, tag, start=0, size=10):
        return self.pages.get(start, [])

    def match(self, region, match_id):
        self.match_calls.append(match_id)
        return self.detail[match_id]


class SyncQueueIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "sync.db")
        self.db.init_schema()
        self.cfg = {
            "riot_name": "JoueurTest",
            "riot_tag": "TEST",
            "region": "eu",
            "platform": "pc",
            "api_key": "fake-key-for-tests",
            "backfill": 20,
            "queue_mode": "competitive",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, client, normalize_impl=None):
        def normalize(raw, puuid):
            metadata = raw["metadata"]
            queue = metadata.get("queue") or {}
            return {
                "match_id": metadata["match_id"],
                "started_at": "2026-10-01T00:00:00Z",
                "queue_id": queue.get("id") if isinstance(queue, dict) else queue,
            }, []

        with mock.patch.object(sync, "load_config", return_value=self.cfg), mock.patch.object(
            sync, "HenrikClient", return_value=client
        ), mock.patch.object(sync, "normalize_match", side_effect=normalize_impl or normalize):
            manager = sync.SyncManager(self.db)
            manager._run(full=True)
        return manager

    def test_competitive_sync_skips_unranked_games_and_keeps_paging(self):
        page_zero = [_raw(f"u{i}", {"id": "unrated"}) for i in range(5)]
        page_zero += [_raw(f"c{i}", {"id": "competitive"}) for i in range(5)]
        page_one = [_raw(f"u{i + 5}", {"id": "unrated"}) for i in range(10)]
        page_two = [_raw(f"c{i + 5}", {"id": "competitive"}) for i in range(10)]
        client = FakeClient({0: page_zero, 10: page_one, 20: page_two})

        manager = self._run(client)

        stored = self.db.query_matches(mode="all", days=0)
        self.assertEqual(len(stored), 15)
        self.assertEqual({m["queue_id"] for m in stored}, {"competitive"})
        status = manager.snapshot()
        self.assertEqual(status["state"], "success")
        self.assertEqual(status["new_matches"], 15)
        self.assertEqual(status["progress"], 3)
        self.assertIn("15 parties hors compétitif", status["message"])

    def test_queue_missing_from_the_list_is_checked_on_the_detail(self):
        client = FakeClient(
            {0: [{"metadata": {"match_id": "m1"}}]},
            {"m1": {"metadata": {"match_id": "m1", "queue": {"id": "unrated"}}, "players": [], "rounds": []}},
        )

        manager = self._run(client)

        self.assertEqual(self.db.count_matches(), 0)
        self.assertEqual(client.match_calls, ["m1"])
        self.assertIn("hors compétitif", manager.snapshot()["message"])

    def test_mmr_history_is_imported_without_blocking_matches(self):
        client = FakeClient(
            {0: [_raw("c1", {"id": "competitive"})]},
            history=[
                {
                    "date": "2026-10-01T20:00:00Z",
                    "elo": 1540,
                    "last_change": 22,
                    "rr": 40,
                    "tier": {"id": 15, "name": "Diamond 1"},
                    "map": {"id": "ascent", "name": "Ascent"},
                    "season": {"id": "s1", "short": "S1"},
                    "match_id": "c1",
                }
            ],
        )

        manager = self._run(client)

        self.assertEqual(self.db.count_mmr_history(), 1)
        row = self.db.query_mmr_history(days=0)[0]
        self.assertEqual(row["match_id"], "c1")
        self.assertEqual(row["elo"], 1540)
        self.assertEqual(row["last_change"], 22)
        self.assertEqual(row["tier_name"], "Diamond 1")
        self.assertEqual(manager.snapshot()["new_matches"], 1)

    def test_old_matches_are_backfilled_with_end_causes(self):
        old = {
            "match_id": "old",
            "started_at": "2026-09-01T00:00:00Z",
            "queue_id": "competitive",
            "queue_name": "Competitive",
            "rounds_played": 2,
            "is_demo": 0,
            "synced_at": "2026-09-01T00:00:00Z",
        }
        self.db.upsert_match(
            old,
            [
                {"match_id": "old", "round_num": 1, "side": "attack", "won": 1},
                {"match_id": "old", "round_num": 2, "side": "defense", "won": 0},
            ],
        )
        raw = {
            "metadata": {"match_id": "old", "queue": {"id": "competitive"}},
            "players": [{"puuid": "pu-1"}],
            "rounds": [{"id": 1}, {"id": 2}],
        }
        client = FakeClient({}, {"old": raw})

        def normalize_impl(payload, puuid):
            row = dict(old)
            rounds = [
                {"match_id": "old", "round_num": 1, "side": "attack", "won": 1, "end_cause": "detonation"},
                {"match_id": "old", "round_num": 2, "side": "defense", "won": 0, "end_cause": "defuse"},
            ]
            return row, rounds

        manager = self._run(client, normalize_impl=normalize_impl)

        self.assertEqual(client.match_calls, ["old"])
        rows = self.db.rounds_for(["old"])["old"]
        self.assertEqual([row["end_cause"] for row in rows], ["detonation", "defuse"])
        self.assertIn("complétée", manager.snapshot()["message"])


class MmrHistoryNormalizationTests(unittest.TestCase):
    def test_v2_payload_is_flattened(self):
        rows = sync.normalize_mmr_history(
            {
                "history": [
                    {
                        "date": "2026-10-01T20:00:00Z",
                        "elo": 1540,
                        "last_change": 22,
                        "rr": 40,
                        "tier": {"id": 15, "name": "Diamond 1"},
                        "map": {"id": "ascent", "name": "Ascent"},
                        "season": {"id": "s1", "short": "S1"},
                        "match_id": "m1",
                    }
                ]
            }
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["match_id"], "m1")
        self.assertEqual(row["played_at"], "2026-10-01T20:00:00Z")
        self.assertEqual(row["elo"], 1540)
        self.assertEqual(row["rr"], 40)
        self.assertEqual(row["last_change"], 22)
        self.assertEqual(row["map_name"], "Ascent")
        self.assertEqual(row["season_short"], "S1")
        self.assertEqual(row["is_demo"], 0)

    def test_legacy_fields_are_supported(self):
        rows = sync.normalize_mmr_history(
            [
                {
                    "date": "2026-10-01T20:00:00Z",
                    "mmr_change_to_last_game": -12,
                    "ranking_in_tier": 55,
                    "currenttierpatched": "Platinum 3",
                    "match_id": "m2",
                }
            ],
            is_demo=True,
        )
        self.assertEqual(rows[0]["last_change"], -12)
        self.assertEqual(rows[0]["rr"], 55)
        self.assertEqual(rows[0]["tier_name"], "Platinum 3")
        self.assertEqual(rows[0]["is_demo"], 1)

    def test_entries_without_a_match_id_are_skipped(self):
        self.assertEqual(sync.normalize_mmr_history([{"elo": 1200}]), [])
        self.assertEqual(sync.normalize_mmr_history(None), [])


if __name__ == "__main__":
    unittest.main()
