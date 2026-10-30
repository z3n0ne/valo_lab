"""Normalize a HenrikDev v4 match payload into flat rows for SQLite."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ATTACK = "attack"
DEFENSE = "defense"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _iso(value: Any) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_role(role: Any) -> Optional[str]:
    if not role:
        return None
    text = str(role).strip().lower()
    if text.startswith("at"):
        return ATTACK
    if text.startswith("de"):
        return DEFENSE
    return None


def _flip(side: str) -> str:
    return DEFENSE if side == ATTACK else ATTACK


def _side_for_round(raw_round: Dict[str, Any], my_team_id: str) -> Optional[str]:
    """Return the side my team played on during a round.

    v4 exposes `winning_team_role`. When it is missing we can still infer the
    attacking team from the spike plant (or the defending team from a defuse).
    """
    role = _normalize_role(raw_round.get("winning_team_role"))
    winning_team = raw_round.get("winning_team")
    if role and winning_team:
        return role if winning_team == my_team_id else _flip(role)

    plant = raw_round.get("plant") or {}
    planter = (plant.get("player") or {}).get("team")
    if planter:
        return ATTACK if planter == my_team_id else DEFENSE

    defuse = raw_round.get("defuse") or {}
    defuser = (defuse.get("player") or {}).get("team")
    if defuser:
        return DEFENSE if defuser == my_team_id else ATTACK
    return None


def normalize_match(raw: Dict[str, Any], puuid: str) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    """Convert one v4 match into (match_row, round_rows). Returns None if the player is absent."""
    metadata = raw.get("metadata") or {}
    players = raw.get("players") or []
    me = next((p for p in players if p.get("puuid") == puuid), None)
    if not me:
        return None

    teams = raw.get("teams") or []
    my_team_id = me.get("team_id") or ""
    my_team = next((t for t in teams if t.get("team_id") == my_team_id), None)
    if my_team is None:
        # Some payloads only carry team_number; fall back to the player's team number.
        my_number = me.get("team_number")
        my_team = next((t for t in teams if t.get("team_number") == my_number), None)
    if my_team is None:
        my_team = {}

    team_rounds = my_team.get("rounds") or {}
    score_mine = _int(team_rounds.get("won"))
    score_enemy = _int(team_rounds.get("lost"))

    rounds_raw = raw.get("rounds") or []
    if score_mine == 0 and score_enemy == 0 and rounds_raw:
        # Last-resort fallback if the team aggregate is missing.
        for r in rounds_raw:
            if r.get("winning_team") == my_team_id:
                score_mine += 1
            else:
                score_enemy += 1

    stats = me.get("stats") or {}
    damage = stats.get("damage") or {}
    if isinstance(damage, dict):
        damage_dealt = _int(damage.get("dealt"))
        damage_received = _int(damage.get("received"))
    else:
        damage_dealt = _int(damage)
        damage_received = 0

    agent = me.get("agent") or {}
    tier = me.get("tier") or {}
    queue = metadata.get("queue") or {}
    map_info = metadata.get("map") or {}

    won = 1 if score_mine > score_enemy else 0
    rounds_played = len(rounds_raw) or (score_mine + score_enemy)

    kills_by_round: Dict[Any, List[Dict[str, Any]]] = {}
    for kill in raw.get("kills") or []:
        kills_by_round.setdefault(kill.get("round"), []).append(kill)

    round_rows: List[Dict[str, Any]] = []
    for raw_round in rounds_raw:
        round_num = _int(raw_round.get("id"), len(round_rows) + 1)
        round_stats = next(
            (s for s in raw_round.get("stats") or [] if (s.get("player") or {}).get("puuid") == puuid),
            None,
        )
        if round_stats is None:
            continue
        rs = round_stats.get("stats") or {}
        round_damage = sum(
            _int(event.get("damage"))
            for event in round_stats.get("damage_events") or []
        )
        side = _side_for_round(raw_round, my_team_id)
        round_kills = kills_by_round.get(raw_round.get("id"), [])

        deaths = sum(1 for k in round_kills if (k.get("victim") or {}).get("puuid") == puuid)
        assists = sum(
            1
            for k in round_kills
            if any((a or {}).get("puuid") == puuid for a in (k.get("assistants") or []))
        )

        first_blood_mine = 0
        first_death_mine = 0
        first = raw_round.get("first_blood")
        if isinstance(first, dict) and first.get("team"):
            first_blood_mine = 1 if first.get("team") == my_team_id else 0
            first_death_mine = 1 if first.get("puuid") == puuid else 0
        elif round_kills:
            earliest = min(round_kills, key=lambda k: _int(k.get("time_in_round_in_ms"), 10**9))
            killer = earliest.get("killer") or {}
            victim = earliest.get("victim") or {}
            first_blood_mine = 1 if killer.get("team") == my_team_id else 0
            first_death_mine = 1 if victim.get("puuid") == puuid else 0

        round_rows.append(
            {
                "match_id": metadata.get("match_id", ""),
                "round_num": round_num,
                "side": side,
                "won": 1 if raw_round.get("winning_team") == my_team_id else 0,
                "kills": _int(rs.get("kills")),
                "deaths": deaths,
                "assists": assists,
                "score": _int(rs.get("score")),
                "damage": round_damage,
                "headshots": _int(rs.get("headshots")),
                "bodyshots": _int(rs.get("bodyshots")),
                "legshots": _int(rs.get("legshots")),
                "first_blood_mine": first_blood_mine,
                "first_death_mine": first_death_mine,
            }
        )

    match_row = {
        "match_id": metadata.get("match_id") or raw.get("match_id") or "",
        "started_at": _iso(metadata.get("started_at")),
        "map_id": map_info.get("id") or "unknown",
        "map_name": map_info.get("name") or "Inconnue",
        "queue_id": queue.get("id") or "unknown",
        "queue_name": queue.get("name") or queue.get("id") or "Inconnu",
        "mode_type": queue.get("mode_type") or "",
        "agent_id": agent.get("id") or "unknown",
        "agent_name": agent.get("name") or "Inconnu",
        "puuid": puuid,
        "team_id": my_team_id,
        "won": won,
        "score_mine": score_mine,
        "score_enemy": score_enemy,
        "kills": _int(stats.get("kills")),
        "deaths": _int(stats.get("deaths")),
        "assists": _int(stats.get("assists")),
        "combat_score": _int(stats.get("score")),
        "damage_dealt": damage_dealt,
        "damage_received": damage_received,
        "headshots": _int(stats.get("headshots")),
        "bodyshots": _int(stats.get("bodyshots")),
        "legshots": _int(stats.get("legshots")),
        "rounds_played": rounds_played,
        "tier_name": tier.get("name") or "",
        "is_demo": 0,
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not match_row["match_id"]:
        return None
    return match_row, round_rows
