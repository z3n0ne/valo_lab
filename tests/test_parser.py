"""Tests for the HenrikDev v4 payload normalizer."""
import unittest

from valorant.parser import normalize_match

ME = "puuid-me"
ALLY = "puuid-ally"
ENEMY = "puuid-enemy"


def _round(
    round_id,
    winning_team,
    role=None,
    stats=None,
    kills=None,
    plant=None,
    defuse=None,
    first_blood=None,
    result=None,
    ceremony=None,
):
    return {
        "id": round_id,
        "result": result,
        "ceremony": ceremony,
        "winning_team": winning_team,
        "winning_team_role": role,
        "stats": stats or [],
        "kills": kills or [],
        "plant": plant,
        "defuse": defuse,
        "first_blood": first_blood,
    }


def _player_stats(**overrides):
    base = {
        "puuid": ME,
        "kills": 1,
        "deaths": 0,
        "assists": 0,
        "score": 180,
        "headshots": 1,
        "bodyshots": 2,
        "legshots": 0,
    }
    base.update(overrides)
    return {"player": {"puuid": ME}, "stats": base, "damage_events": [{"damage": 120, "receiver": ENEMY}]}


def build_match(rounds, won=13, lost=8, kills=None):
    return {
        "metadata": {
            "match_id": "match-1",
            "started_at": "2026-10-01T20:15:00Z",
            "queue": {"id": "competitive", "name": "Competitive", "mode_type": "standard"},
            "map": {"id": "ascent", "name": "Ascent"},
        },
        "players": [
            {
                "puuid": ME,
                "team_id": "blue",
                "team_number": 1,
                "agent": {"id": "omen", "name": "Omen"},
                "tier": {"name": "Diamond 1"},
                "stats": {
                    "kills": 21,
                    "deaths": 14,
                    "assists": 7,
                    "score": 4200,
                    "headshots": 9,
                    "bodyshots": 20,
                    "legshots": 2,
                    "damage": {"dealt": 3100, "received": 2400},
                },
            },
            {"puuid": ALLY, "team_id": "blue", "team_number": 1, "agent": {"name": "Sova"}},
            {"puuid": ENEMY, "team_id": "red", "team_number": 2, "agent": {"name": "Jett"}},
        ],
        "teams": [
            {"team_id": "blue", "rounds": {"won": won, "lost": lost}},
            {"team_id": "red", "rounds": {"won": lost, "lost": won}},
        ],
        "rounds": rounds,
        "kills": kills or [],
    }


class SideAttributionTests(unittest.TestCase):
    def _side(self, raw_round):
        match, rows = normalize_match(build_match([raw_round]), ME)
        self.assertIsNotNone(match)
        self.assertEqual(len(rows), 1, "round row missing, check the stats payload")
        return rows[0]["side"], rows[0]["won"]

    def test_winning_role_applies_to_my_team(self):
        side, won = self._side(_round(1, "blue", "defense", [_player_stats()]))
        self.assertEqual(side, "defense")
        self.assertEqual(won, 1)

    def test_winning_role_is_flipped_for_the_other_team(self):
        side, won = self._side(_round(1, "red", "attack", [_player_stats()]))
        self.assertEqual(side, "defense", "the enemy attacking means we were defending")
        self.assertEqual(won, 0)

    def test_attack_role_acronyms_are_accepted(self):
        side, _ = self._side(_round(1, "blue", "atk", [_player_stats()]))
        self.assertEqual(side, "attack")

    def test_plant_infers_attack_side_without_role(self):
        plant = {"player": {"puuid": ALLY, "team": "blue"}}
        side, _ = self._side(_round(1, "blue", None, [_player_stats()], plant=plant))
        self.assertEqual(side, "attack")

    def test_plant_by_the_enemy_infers_defense(self):
        plant = {"player": {"puuid": ENEMY, "team": "red"}}
        side, _ = self._side(_round(1, "blue", None, [_player_stats()], plant=plant))
        self.assertEqual(side, "defense")

    def test_defuse_infers_defense_side(self):
        defuse = {"player": {"puuid": ME, "team": "blue"}}
        side, _ = self._side(_round(1, "blue", None, [_player_stats()], defuse=defuse))
        self.assertEqual(side, "defense")

    def test_unknown_side_is_none(self):
        side, _ = self._side(_round(1, "blue", None, [_player_stats()]))
        self.assertIsNone(side)


class EndCauseTests(unittest.TestCase):
    def _end(self, raw_round, kills=None):
        _, rows = normalize_match(build_match([raw_round], kills=kills), ME)
        self.assertTrue(rows)
        return rows[0]["end_cause"]

    def test_bomb_detonation(self):
        cause = self._end(_round(1, "blue", "attack", [_player_stats()], result="Bomb detonated"))
        self.assertEqual(cause, "detonation")

    def test_bomb_defuse(self):
        cause = self._end(_round(1, "red", "defense", [_player_stats()], result="Bomb defused"))
        self.assertEqual(cause, "defuse")

    def test_timeout(self):
        cause = self._end(_round(1, "red", "defense", [_player_stats()], result="Time ran out"))
        self.assertEqual(cause, "timeout")

    def test_attack_elimination(self):
        cause = self._end(_round(1, "blue", "attack", [_player_stats()], result="Eliminated"))
        self.assertEqual(cause, "attack_elimination")

    def test_defense_elimination(self):
        cause = self._end(_round(1, "red", "defense", [_player_stats()], result="Eliminated"))
        self.assertEqual(cause, "defense_elimination")

    def test_cancelled_rounds_are_other(self):
        cause = self._end(_round(1, "blue", "attack", [_player_stats()], result="Surrendered"))
        self.assertEqual(cause, "other")

    def test_missing_result_falls_back_to_the_attack_win(self):
        cause = self._end(_round(1, "blue", "attack", [_player_stats()]))
        self.assertEqual(cause, "attack_elimination")

    def test_missing_result_falls_back_to_the_defense_timeout(self):
        cause = self._end(_round(1, "blue", "defense", [_player_stats()]))
        self.assertEqual(cause, "timeout")

    def test_missing_result_detects_a_defense_wipe(self):
        kills = [
            {
                "round": 1,
                "killer": {"puuid": ALLY, "team": "blue"},
                "victim": {"puuid": f"red-{index}", "team": "red"},
                "assistants": [],
            }
            for index in range(5)
        ]
        cause = self._end(_round(1, "blue", "defense", [_player_stats()]), kills=kills)
        self.assertEqual(cause, "defense_elimination")


class NormalizeMatchTests(unittest.TestCase):
    def test_missing_player_returns_none(self):
        payload = build_match([])
        payload["players"] = [p for p in payload["players"] if p["puuid"] != ME]
        self.assertIsNone(normalize_match(payload, ME))

    def test_match_row_is_normalized(self):
        payload = build_match([_round(1, "blue", "attack", [_player_stats()])])
        match, _ = normalize_match(payload, ME)
        self.assertEqual(match["match_id"], "match-1")
        self.assertEqual(match["started_at"], "2026-10-01T20:15:00Z")
        self.assertEqual(match["map_name"], "Ascent")
        self.assertEqual(match["agent_name"], "Omen")
        self.assertEqual((match["score_mine"], match["score_enemy"]), (13, 8))
        self.assertEqual(match["won"], 1)
        self.assertEqual(match["damage_dealt"], 3100)
        self.assertEqual(match["damage_received"], 2400)
        self.assertEqual(match["rounds_played"], 1)
        self.assertEqual(match["is_demo"], 0)

    def test_draw_is_not_a_win(self):
        payload = build_match([], won=13, lost=13)
        match, _ = normalize_match(payload, ME)
        self.assertEqual(match["won"], 0)

    def test_round_damage_comes_from_damage_events(self):
        stats = _player_stats()
        stats["damage_events"] = [{"damage": 90, "receiver": ENEMY}, {"damage": 55, "receiver": ALLY}]
        _, rows = normalize_match(
            build_match([_round(1, "blue", "attack", [stats])]), ME
        )
        self.assertEqual(rows[0]["damage"], 145)
        self.assertEqual(rows[0]["score"], 180)

    def test_kills_and_assists_come_from_the_kill_feed(self):
        kills = [
            {"round": 1, "killer": {"puuid": ALLY}, "victim": {"puuid": ENEMY}, "assistants": []},
            {"round": 1, "killer": {"puuid": ENEMY}, "victim": {"puuid": ME}, "assistants": [{"puuid": ALLY}]},
            {"round": 1, "killer": {"puuid": ALLY}, "victim": {"puuid": "puuid-x"}, "assistants": [{"puuid": ME}]},
        ]
        payload = build_match([_round(1, "blue", "attack", [_player_stats()])], kills=kills)
        _, rows = normalize_match(payload, ME)
        self.assertEqual(rows[0]["deaths"], 1)
        self.assertEqual(rows[0]["assists"], 1)

    def test_first_blood_falls_back_to_the_earliest_kill(self):
        kills = [
            {"round": 1, "killer": {"puuid": ME, "team": "blue"}, "victim": {"puuid": ENEMY}, "time_in_round_in_ms": 2100},
            {"round": 1, "killer": {"puuid": ENEMY, "team": "red"}, "victim": {"puuid": ALLY}, "time_in_round_in_ms": 9000},
        ]
        payload = build_match([_round(1, "blue", "attack", [_player_stats()])], kills=kills)
        _, rows = normalize_match(payload, ME)
        self.assertEqual(rows[0]["first_blood_mine"], 1)
        self.assertEqual(rows[0]["first_death_mine"], 0)

    def test_first_death_is_flagged_when_the_enemy_opens(self):
        kills = [
            {"round": 1, "killer": {"puuid": ENEMY, "team": "red"}, "victim": {"puuid": ME, "team": "blue"}, "time_in_round_in_ms": 800},
        ]
        payload = build_match([_round(1, "blue", "attack", [_player_stats()])], kills=kills)
        _, rows = normalize_match(payload, ME)
        self.assertEqual(rows[0]["first_blood_mine"], 0)
        self.assertEqual(rows[0]["first_death_mine"], 1)

    def test_rounds_without_stats_are_skipped(self):
        payload = build_match(
            [
                _round(1, "blue", "attack", [_player_stats()]),
                _round(2, "blue", "attack", []),
            ]
        )
        _, rows = normalize_match(payload, ME)
        self.assertEqual(len(rows), 1)

    def test_score_falls_back_to_round_results(self):
        payload = build_match(
            [
                _round(1, "blue", "attack", [_player_stats()]),
                _round(2, "red", "attack", [_player_stats()]),
            ],
            won=0,
            lost=0,
        )
        match, _ = normalize_match(payload, ME)
        self.assertEqual((match["score_mine"], match["score_enemy"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
