"""Deterministic demo dataset so the dashboard is usable before the API is configured."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from .db import Database

MAPS: Dict[str, Dict[str, float]] = {
    "Ascent": {"weight": 0.20, "attack": 0.52, "defense": 0.58},
    "Bind": {"weight": 0.17, "attack": 0.47, "defense": 0.42},
    "Haven": {"weight": 0.15, "attack": 0.50, "defense": 0.52},
    "Split": {"weight": 0.14, "attack": 0.46, "defense": 0.56},
    "Sunset": {"weight": 0.13, "attack": 0.45, "defense": 0.41},
    "Lotus": {"weight": 0.12, "attack": 0.48, "defense": 0.49},
    "Icebox": {"weight": 0.09, "attack": 0.51, "defense": 0.59},
}

AGENTS: Dict[str, Dict[str, Any]] = {
    "Jett": {"weight": 0.28, "attack": 0.035, "defense": -0.010, "kills": 1.22, "score": 1.12, "synergy": {}},
    "Raze": {"weight": 0.16, "attack": 0.000, "defense": -0.045, "kills": 1.18, "score": 1.10, "fg": -0.035, "synergy": {"Split": 0.01}},
    "Omen": {"weight": 0.20, "attack": 0.015, "defense": 0.050, "kills": 0.92, "score": 0.94, "fg": 0.050, "synergy": {"Ascent": 0.02, "Lotus": 0.02}},
    "Sova": {"weight": 0.14, "attack": 0.020, "defense": 0.010, "kills": 0.98, "score": 0.98, "fg": -0.020, "synergy": {"Icebox": 0.03, "Haven": 0.02}},
    "Killjoy": {"weight": 0.14, "attack": -0.010, "defense": 0.045, "kills": 0.90, "score": 0.92, "fg": 0.02, "synergy": {"Bind": 0.03, "Ascent": 0.01}},
    "Chamber": {"weight": 0.08, "attack": 0.010, "defense": 0.025, "kills": 1.08, "score": 1.04, "synergy": {"Lotus": 0.02, "Sunset": 0.02}},
}

TIER_NAMES = (
    "Iron",
    "Bronze",
    "Silver",
    "Gold",
    "Platinum",
    "Diamond",
    "Ascendant",
    "Immortal",
)


def _tier_for_elo(elo: int) -> str:
    if elo >= 2400:
        return "Radiant"
    index = min(len(TIER_NAMES) - 1, max(0, elo // 300))
    division = (elo % 300) // 100 + 1
    return f"{TIER_NAMES[index]} {division}"


def _pick(rng: random.Random, weights: Dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_score(rng: random.Random, won: bool, mult: float) -> int:
    base = rng.randint(150, 310) if won else rng.randint(65, 185)
    return max(0, int(base * mult + rng.randint(-25, 25)))


def _round_damage(rng: random.Random, won: bool) -> int:
    base = rng.randint(90, 230) if won else rng.randint(45, 155)
    return max(0, base + rng.randint(-20, 20))


def _round_shots(rng: random.Random) -> tuple:
    headshots = rng.choices([0, 1, 2, 3], weights=[20, 42, 30, 8], k=1)[0]
    bodyshots = rng.randint(0, 6)
    legshots = rng.choices([0, 1, 2], weights=[80, 18, 2], k=1)[0]
    return headshots, bodyshots, legshots


def _sample_match(rng: random.Random, idx: int, started_at: datetime, competitive_only: bool = True) -> tuple:
    map_name = _pick(rng, {name: data["weight"] for name, data in MAPS.items()})
    agent_name = _pick(rng, {name: data["weight"] for name, data in AGENTS.items()})
    map_profile = MAPS[map_name]
    agent = AGENTS[agent_name]
    cause_rng = random.Random(9000 + idx)

    start_side = rng.choice(["attack", "defense"])
    my_score = 0
    enemy_score = 0
    rounds: List[Dict[str, Any]] = []
    total_score = 0
    total_damage = 0
    total_kills = 0
    total_deaths = 0
    total_assists = 0
    total_hs = 0
    total_bs = 0
    total_ls = 0

    max_rounds = 40
    for i in range(max_rounds):
        if i < 12:
            side = start_side
        elif i < 24:
            side = "defense" if start_side == "attack" else "attack"
        else:
            side = start_side if (i - 24) % 2 == 0 else ("defense" if start_side == "attack" else "attack")

        prob = map_profile[side] + agent[side] + agent.get("synergy", {}).get(map_name, 0.0)
        prob += agent.get("fg", 0.0)
        # Global bias: this profile is stronger on attack, weaker on defense.
        prob += 0.050 if side == "attack" else -0.090
        prob = _clamp(prob, 0.33, 0.70)
        won = rng.random() < prob

        if won:
            my_score += 1
        else:
            enemy_score += 1

        kill_weights = (
            [0.22, 0.45, 0.26, 0.07] if won else [0.38, 0.44, 0.16, 0.02]
        )
        kills = rng.choices([0, 1, 2, 3], weights=kill_weights, k=1)[0]
        kills = int(round(kills * agent["kills"]))
        kills = min(4, max(0, kills))
        died = rng.random() < (0.63 if won else 0.82)
        deaths = 1 if died else 0
        assists = rng.choices([0, 1, 2], weights=[62, 30, 8], k=1)[0]

        score = _round_score(rng, won, agent["score"])
        damage = _round_damage(rng, won)
        hs, bs, ls = _round_shots(rng)
        if died:
            first_death = 1 if rng.random() < 0.30 else 0
        else:
            first_death = 0
        first_blood = 0 if first_death else (1 if rng.random() < 0.56 else 0)

        if won and side == "attack":
            end_cause = "detonation" if cause_rng.random() < 0.45 else "attack_elimination"
        elif won and side == "defense":
            roll = cause_rng.random()
            end_cause = "defuse" if roll < 0.35 else "defense_elimination" if roll < 0.75 else "timeout"
        elif side == "attack":
            roll = cause_rng.random()
            end_cause = "defuse" if roll < 0.35 else "defense_elimination" if roll < 0.75 else "timeout"
        else:
            end_cause = "detonation" if cause_rng.random() < 0.45 else "attack_elimination"

        rounds.append(
            {
                "match_id": f"demo-{idx:04d}",
                "round_num": i + 1,
                "side": side,
                "won": 1 if won else 0,
                "kills": kills,
                "deaths": deaths,
                "assists": assists,
                "score": score,
                "damage": damage,
                "headshots": hs,
                "bodyshots": bs,
                "legshots": ls,
                "first_blood_mine": first_blood,
                "first_death_mine": first_death,
                "end_cause": end_cause,
            }
        )
        total_score += score
        total_damage += damage
        total_kills += kills
        total_deaths += deaths
        total_assists += assists
        total_hs += hs
        total_bs += bs
        total_ls += ls

        diff = my_score - enemy_score
        # Valorant rules: first to 13 wins, and beyond 12-12 every round
        # pair is decided in overtime (a 2-round lead is required).
        if max(my_score, enemy_score) >= 13 and abs(diff) >= 2:
            break

    # The draw is kept even in competitive-only mode so the rest of the
    # deterministic sequence stays stable.
    drawn_queue = rng.random()
    if competitive_only:
        queue_id, queue_name = "competitive", "Competitive"
    else:
        queue_id = "unrated" if drawn_queue < 0.13 else "competitive"
        queue_name = "Unrated" if queue_id == "unrated" else "Competitive"
    match_row = {
        "match_id": f"demo-{idx:04d}",
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "map_id": f"demo-map-{map_name.lower()}",
        "map_name": map_name,
        "queue_id": queue_id,
        "queue_name": queue_name,
        "mode_type": "standard",
        "agent_id": f"demo-agent-{agent_name.lower()}",
        "agent_name": agent_name,
        "puuid": "demo-puuid",
        "team_id": "demo-team",
        "won": 1 if my_score > enemy_score else 0,
        "score_mine": my_score,
        "score_enemy": enemy_score,
        "kills": total_kills,
        "deaths": total_deaths,
        "assists": total_assists,
        "combat_score": total_score,
        "damage_dealt": total_damage,
        "damage_received": int(total_damage * rng.uniform(0.82, 1.05)),
        "headshots": total_hs,
        "bodyshots": total_bs,
        "legshots": total_ls,
        "rounds_played": len(rounds),
        "tier_name": "Diamond 1",
        "is_demo": 1,
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return match_row, rounds


def seed_demo(db: Database, count: int = 90, competitive_only: bool = True) -> int:
    if db.count_matches() > 0 or db.get_meta("demo_dismissed"):
        return 0
    rng = random.Random(20262561)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=1)
    start = now - timedelta(days=86)
    inserted = 0
    history = []
    for idx in range(1, count + 1):
        # Spread matches over ~86 days, with a slight recent activity bump.
        offset = start + timedelta(days=(idx * 86.0 / count) + rng.uniform(0, 1.6))
        offset = offset.replace(hour=rng.randint(17, 23), minute=rng.randint(0, 59))
        if offset > now:
            offset = now - timedelta(hours=rng.randint(1, 30))
        match, rounds = _sample_match(rng, idx, offset, competitive_only=competitive_only)
        db.upsert_match(match, rounds)
        history.append(
            {
                "match_id": match["match_id"],
                "played_at": match["started_at"],
                "won": match["won"],
                "draw": 1 if match["score_mine"] == match["score_enemy"] else 0,
                "map_id": match["map_id"],
                "map_name": match["map_name"],
            }
        )
        inserted += 1

    final_rank, final_rr = "Diamond 1", 54
    if history:
        history.sort(key=lambda item: item["played_at"])
        deltas = []
        for index, item in enumerate(history):
            if item["draw"]:
                delta = 0
            elif item["won"]:
                delta = 18 + index % 6
            else:
                delta = -(14 + index % 4)
            deltas.append(delta)
        elo = max(0, 1554 - sum(deltas))
        mmr_rows = []
        for item, delta in zip(history, deltas):
            elo = max(0, elo + delta)
            mmr_rows.append(
                {
                    "match_id": item["match_id"],
                    "played_at": item["played_at"],
                    "rr": elo % 100,
                    "last_change": delta,
                    "elo": elo,
                    "tier_id": 0,
                    "tier_name": _tier_for_elo(elo),
                    "map_id": item["map_id"],
                    "map_name": item["map_name"],
                    "season_id": "demo-season",
                    "season_short": "D",
                    "is_demo": 1,
                    "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
        db.upsert_mmr_history(mmr_rows)
        if mmr_rows:
            final_rank = mmr_rows[-1]["tier_name"]
            final_rr = mmr_rows[-1]["rr"]

    profile = {
        "name": "DemoPlayer",
        "tag": "EUW",
        "puuid": "demo-puuid",
        "region": "eu",
        "card": "",
        "level": 312,
        "rank": final_rank,
        "rr": final_rr,
        "peak": "Ascendant 2",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "demo": True,
    }
    if not db.get_meta("profile"):
        db.set_meta("profile", profile)
    db.set_meta("demo_seeded_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return inserted
