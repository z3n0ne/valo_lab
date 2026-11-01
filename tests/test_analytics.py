"""Tests for the aggregation and insight engine."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from valorant.analytics import compute
from valorant.db import Database


def _rounds(
    match_id,
    attack_wins,
    defense_wins,
    attack_rounds,
    defense_rounds,
    attack_cause=None,
    defense_cause=None,
):
    rows = []
    number = 1
    for _ in range(attack_rounds):
        rows.append(
            {
                "match_id": match_id,
                "round_num": number,
                "side": "attack",
                "won": 1 if attack_wins > 0 else 0,
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "score": 0,
                "damage": 0,
                "headshots": 0,
                "bodyshots": 0,
                "legshots": 0,
                "first_blood_mine": 0,
                "first_death_mine": 0,
                "end_cause": attack_cause,
            }
        )
        attack_wins = max(0, attack_wins - 1)
        number += 1
    for _ in range(defense_rounds):
        rows.append(
            {
                "match_id": match_id,
                "round_num": number,
                "side": "defense",
                "won": 1 if defense_wins > 0 else 0,
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "score": 0,
                "damage": 0,
                "headshots": 0,
                "bodyshots": 0,
                "legshots": 0,
                "first_blood_mine": 0,
                "first_death_mine": 0,
                "end_cause": defense_cause,
            }
        )
        defense_wins = max(0, defense_wins - 1)
        number += 1
    return rows


class AnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "test.db")
        self.db.init_schema()

    def tearDown(self):
        self.tmp.cleanup()

    def add_match(
        self,
        match_id,
        agent,
        map_name,
        days_ago,
        wins,
        losses,
        kills,
        deaths,
        assists,
        combat_score,
        damage,
        attack_wins,
        defense_wins,
        attack_rounds=12,
        defense_rounds=12,
        queue="competitive",
        attack_cause=None,
        defense_cause=None,
    ):
        started = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        match = {
            "match_id": match_id,
            "started_at": started,
            "map_id": map_name.lower(),
            "map_name": map_name,
            "queue_id": queue,
            "queue_name": queue.capitalize(),
            "mode_type": "standard",
            "agent_id": agent.lower(),
            "agent_name": agent,
            "puuid": "me",
            "team_id": "blue",
            "won": 1 if wins > losses else 0,
            "score_mine": wins,
            "score_enemy": losses,
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "combat_score": combat_score,
            "damage_dealt": damage,
            "damage_received": 0,
            "headshots": 10,
            "bodyshots": 30,
            "legshots": 0,
            "rounds_played": attack_rounds + defense_rounds,
            "tier_name": "Diamond 1",
            "is_demo": 0,
            "synced_at": started,
        }
        rounds = _rounds(
            match_id,
            attack_wins,
            defense_wins,
            attack_rounds,
            defense_rounds,
            attack_cause=attack_cause,
            defense_cause=defense_cause,
        )
        self.db.upsert_match(match, rounds)

    def add_mmr(self, match_id, days_ago, elo, delta, rr=None):
        played = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.db.upsert_mmr_history(
            [
                {
                    "match_id": match_id,
                    "played_at": played,
                    "rr": elo % 100 if rr is None else rr,
                    "last_change": delta,
                    "elo": elo,
                    "tier_id": 1,
                    "tier_name": "Diamond 1",
                    "map_id": "ascent",
                    "map_name": "Ascent",
                    "season_id": "s1",
                    "season_short": "S1",
                    "is_demo": 0,
                    "synced_at": played,
                }
            ]
        )

    def seed_four_matches(self):
        # 2 wins / 2 losses, more rounds won on attack than on defense.
        self.add_match("m1", "Omen", "Ascent", 4, 13, 10, 24, 15, 6, 4600, 2300, 8, 5, attack_rounds=12, defense_rounds=11)
        self.add_match("m2", "Omen", "Ascent", 3, 9, 13, 18, 18, 4, 3800, 1900, 4, 5, attack_rounds=11, defense_rounds=11)
        self.add_match("m3", "Raze", "Bind", 2, 13, 11, 20, 17, 3, 4300, 2150, 7, 6, attack_rounds=12, defense_rounds=12)
        self.add_match("m4", "Raze", "Bind", 1, 11, 13, 15, 20, 2, 3900, 1950, 5, 6, attack_rounds=12, defense_rounds=12)


class SummaryTests(AnalyticsTestCase):
    def test_empty_database_is_safe(self):
        data = compute(self.db)
        self.assertFalse(data["meta"]["has_data"])
        self.assertEqual(data["summary"]["matches"], 0)
        self.assertEqual(data["agents"], [])
        self.assertEqual(data["maps"], [])
        self.assertIsNone(data["highlight"])
        self.assertEqual(len(data["insights"]), 1)
        self.assertEqual(data["insights"][0]["tag"], "DONNÉES")

    def test_overall_aggregates(self):
        self.seed_four_matches()
        summary = compute(self.db)["summary"]
        self.assertEqual(summary["matches"], 4)
        self.assertEqual(summary["wins"], 2)
        self.assertEqual(summary["losses"], 2)
        self.assertEqual(summary["win_rate"], 50.0)
        self.assertEqual(summary["kills"], 77)
        self.assertEqual(summary["deaths"], 70)
        self.assertEqual(summary["kd"], 1.1)
        self.assertEqual(summary["kda"], round((77 + 15) / 70, 2))
        self.assertEqual(summary["rounds"], 93)
        self.assertEqual(summary["acs"], round(16600 / 93, 1))
        self.assertEqual(summary["adr"], round(8300 / 93, 1))

    def test_sides_are_split(self):
        self.seed_four_matches()
        summary = compute(self.db)["summary"]
        attack = summary["attack"]
        defense = summary["defense"]
        self.assertEqual(attack["rounds"], 47)
        self.assertEqual(attack["wins"], 24)
        self.assertEqual(attack["round_win_rate"], round(100 * 24 / 47, 1))
        self.assertEqual(defense["rounds"], 46)
        self.assertEqual(defense["wins"], 22)
        self.assertEqual(defense["round_win_rate"], round(100 * 22 / 46, 1))
        self.assertGreater(attack["round_win_rate"], defense["round_win_rate"])
        self.assertEqual(summary["round_win_rate"], round(100 * 46 / 93, 1))

    def test_agents_and_maps_group_matches(self):
        self.seed_four_matches()
        data = compute(self.db)
        agents = {a["name"]: a for a in data["agents"]}
        maps = {m["name"]: m for m in data["maps"]}
        self.assertEqual(set(agents), {"Omen", "Raze"})
        self.assertEqual(set(maps), {"Ascent", "Bind"})
        self.assertEqual(agents["Omen"]["matches"], 2)
        self.assertEqual(agents["Omen"]["win_rate"], 50.0)
        self.assertEqual(maps["Ascent"]["rounds"], 45)
        self.assertEqual(maps["Bind"]["rounds"], 48)
        for row in list(agents.values()) + list(maps.values()):
            self.assertIn("impact", row)
            self.assertIsInstance(row["impact"], (int, float))
            self.assertIn("attack", row)
            self.assertIn("defense", row)

    def test_map_drill_down_lists_agents_for_that_map(self):
        self.seed_four_matches()
        ascent = {m["name"]: m for m in compute(self.db)["maps"]}["Ascent"]
        self.assertEqual([a["name"] for a in ascent["agents"]], ["Omen"])
        self.assertEqual(ascent["agents"][0]["matches"], 2)
        self.assertEqual(ascent["agents"][0]["impact"], 100.0)

        self.add_match("m5", "Jett", "Ascent", 1, 13, 8, 25, 10, 4, 5200, 2600, 9, 4)
        ascent = {m["name"]: m for m in compute(self.db)["maps"]}["Ascent"]
        agents = {a["name"]: a for a in ascent["agents"]}
        self.assertEqual(set(agents), {"Omen", "Jett"})
        self.assertEqual(agents["Jett"]["matches"], 1)
        self.assertEqual(ascent["agents"][0]["name"], "Jett")
        self.assertGreater(ascent["agents"][0]["impact"], 100)
        self.assertLess(agents["Omen"]["impact"], 100)

    def test_highlight_is_the_highest_acs_game(self):
        self.seed_four_matches()
        data = compute(self.db)
        highlight = data["highlight"]
        self.assertIsNotNone(highlight)
        self.assertEqual(highlight["match_id"], "m1")
        self.assertEqual(highlight["acs"], max(card["acs"] for card in data["recent"]))
        self.assertIn("agent", highlight)
        self.assertIn("score", highlight)
        self.assertIn("kd", highlight)

    def test_mode_filter_excludes_deathmatch(self):
        self.seed_four_matches()
        self.add_match(
            "dm1", "Jett", "Ascent", 1, 1, 0, 40, 20, 5, 9000, 4000, 0, 0,
            attack_rounds=0, defense_rounds=0, queue="deathmatch",
        )
        tactical = compute(self.db, mode="tactical")
        deathmatch = compute(self.db, mode="deathmatch")
        everything = compute(self.db, mode="all")
        self.assertEqual(tactical["summary"]["matches"], 4)
        self.assertEqual(deathmatch["summary"]["matches"], 1)
        self.assertEqual(everything["summary"]["matches"], 5)

    def test_days_window_filters_old_matches(self):
        self.seed_four_matches()
        self.add_match("old", "Omen", "Ascent", 400, 13, 5, 20, 10, 5, 4000, 2000, 10, 5)
        self.assertEqual(compute(self.db, days=90)["summary"]["matches"], 4)
        self.assertEqual(compute(self.db, days=3650)["summary"]["matches"], 5)


class EndingTests(AnalyticsTestCase):
    def test_endings_are_grouped_globally_and_per_map(self):
        self.add_match(
            "e1", "Omen", "Ascent", 1, 13, 11, 20, 16, 4, 4400, 2200, 8, 6,
            attack_cause="detonation", defense_cause="defuse",
        )
        data = compute(self.db)
        summary = data["summary"]
        endings = {item["id"]: item for item in summary["endings"]}
        self.assertEqual(endings["detonation"]["rounds"], 12)
        self.assertEqual(endings["detonation"]["wins"], 8)
        self.assertEqual(endings["detonation"]["losses"], 4)
        self.assertEqual(endings["detonation"]["side"], "attack")
        self.assertEqual(endings["defuse"]["rounds"], 12)
        self.assertEqual(endings["defuse"]["wins"], 6)
        self.assertEqual(endings["defuse"]["side"], "defense")
        self.assertEqual(summary["ending_rounds"], 24)
        self.assertEqual(summary["rounds_without_cause"], 0)

        ascent = data["maps"][0]
        self.assertEqual(ascent["ending_rounds"], 24)
        self.assertEqual({item["id"] for item in ascent["endings"] if item["rounds"]}, {"detonation", "defuse"})

    def test_unclassified_rounds_are_counted(self):
        self.add_match(
            "e1", "Omen", "Ascent", 1, 13, 11, 20, 16, 4, 4400, 2200, 8, 6,
            attack_cause="detonation", defense_cause="defuse",
        )
        self.add_match("e2", "Omen", "Ascent", 2, 13, 9, 18, 14, 5, 4100, 2050, 7, 6)
        summary = compute(self.db)["summary"]
        self.assertEqual(summary["rounds"], 48)
        self.assertEqual(summary["ending_rounds"], 24)
        self.assertEqual(summary["rounds_without_cause"], 24)


class AcsImpactTests(AnalyticsTestCase):
    def test_high_acs_is_compared_with_low_acs(self):
        self.seed_four_matches()
        impact = compute(self.db)["acs_impact"]
        self.assertTrue(impact["available"])
        self.assertEqual(impact["matches"], 4)
        self.assertEqual(impact["high"]["wins"], 2)
        self.assertEqual(impact["low"]["wins"], 0)
        self.assertEqual(impact["high"]["win_rate"], 100.0)
        self.assertEqual(impact["low"]["win_rate"], 0.0)
        self.assertEqual(impact["lift"], 100.0)
        self.assertGreater(impact["correlation"], 0.35)
        self.assertEqual(impact["strength"], "strong")
        self.assertIn("convertit", impact["verdict"])

    def test_missing_games_disable_the_metric(self):
        self.add_match("solo", "Omen", "Ascent", 1, 13, 9, 20, 14, 4, 4400, 2200, 7, 6)
        impact = compute(self.db)["acs_impact"]
        self.assertFalse(impact["available"])
        self.assertEqual(impact["matches"], 1)

    def test_conversion_insight_is_published(self):
        self.seed_four_matches()
        insights = compute(self.db)["insights"]
        conversion = [item for item in insights if item["tag"] == "CONVERSION"]
        self.assertTrue(conversion)
        self.assertEqual(conversion[0]["kind"], "strength")
        self.assertIn("100", conversion[0]["detail"])


class RrHistoryTests(AnalyticsTestCase):
    def test_empty_history_is_safe(self):
        self.seed_four_matches()
        history = compute(self.db)["rr_history"]
        self.assertFalse(history["available"])
        self.assertEqual(history["points"], [])

    def test_elo_history_is_sorted_and_merged_with_matches(self):
        self.seed_four_matches()
        self.add_mmr("m1", 4, 1000, 20)
        self.add_mmr("m2", 3, 1020, -10)
        self.add_mmr("m3", 2, 1010, 15)
        self.add_mmr("m4", 1, 1050, 40)
        data = compute(self.db)
        history = data["rr_history"]
        self.assertTrue(history["available"])
        self.assertEqual(history["metric"], "elo")
        self.assertEqual(history["metric_label"], "RR cumulés")
        self.assertEqual(history["matches"], 4)
        self.assertEqual([point["match_id"] for point in history["points"]], ["m1", "m2", "m3", "m4"])
        self.assertEqual(history["start"]["value"], 1000)
        self.assertEqual(history["current"]["value"], 1050)
        self.assertEqual(history["change"], 50)
        self.assertEqual(history["current"]["agent"], "Raze")
        self.assertEqual(history["points"][0]["agent"], "Omen")

    def test_rr_within_rank_is_used_when_elo_is_missing(self):
        self.seed_four_matches()
        for index, match_id in enumerate(("m1", "m2", "m3", "m4")):
            self.add_mmr(match_id, 4 - index, 0, 5, rr=10 + index * 7)
        history = compute(self.db)["rr_history"]
        self.assertEqual(history["metric"], "rr")
        self.assertEqual(history["metric_label"], "RR dans le rang")
        self.assertEqual(history["current"]["value"], 31)

    def test_old_history_follows_the_period_filter(self):
        self.seed_four_matches()
        self.add_mmr("m1", 4, 1000, 20)
        self.add_mmr("m2", 3, 1020, 20)
        self.add_mmr("m3", 2, 1040, 20)
        self.add_mmr("m4", 1, 1060, 20)
        self.add_mmr("old", 400, 900, -20)
        history = compute(self.db, days=90)["rr_history"]
        self.assertEqual(history["matches"], 4)


class InsightTests(AnalyticsTestCase):
    def test_insights_have_the_expected_shape(self):
        self.seed_four_matches()
        insights = compute(self.db)["insights"]
        self.assertTrue(insights, "expected at least one insight with 4 matches")
        for item in insights:
            self.assertIn(item["kind"], {"strength", "weakness", "info"})
            self.assertTrue(item["title"])
            self.assertTrue(item["detail"])
            self.assertIn(item["confidence"], {"high", "medium", "low"})
            self.assertIsInstance(item["sample"], int)
            self.assertIn(item["tag"], {"AGENT", "MAP", "CÔTÉ", "OUVERTURE", "FORME", "CONVERSION", "DONNÉES"})

    def test_balanced_sides_are_reported_as_such(self):
        self.seed_four_matches()
        insights = compute(self.db)["insights"]
        side_insights = [i for i in insights if i["tag"] == "CÔTÉ"]
        self.assertTrue(side_insights)
        self.assertEqual(side_insights[0]["kind"], "info")
        self.assertIn("équilibré", side_insights[0]["title"].lower())

    def test_weak_side_is_reported_when_attack_dominates(self):
        for index in range(6):
            self.add_match(
                f"atk{index}", "Omen", "Ascent", index + 1,
                wins=13, losses=11, kills=20, deaths=16, assists=5,
                combat_score=4400, damage=2200,
                attack_wins=9, defense_wins=4,
            )
        insights = compute(self.db)["insights"]
        side_insights = [i for i in insights if i["tag"] == "CÔTÉ"]
        self.assertTrue(side_insights, "a large attack/defense gap should be flagged")
        self.assertEqual(side_insights[0]["kind"], "weakness")
        self.assertIn("défense", side_insights[0]["detail"].lower())
        self.assertIn("défense", side_insights[0]["title"].lower())

    def test_demo_dataset_produces_balanced_insights(self):
        from valorant.demo import seed_demo

        seed_demo(self.db)
        data = compute(self.db)
        self.assertGreaterEqual(len(data["insights"]), 4)
        kinds = {item["kind"] for item in data["insights"]}
        self.assertIn("strength", kinds)
        self.assertIn("weakness", kinds)
        self.assertEqual(data["meta"]["demo"], True)
        self.assertEqual(data["summary"]["matches"], 90)


if __name__ == "__main__":
    unittest.main()
