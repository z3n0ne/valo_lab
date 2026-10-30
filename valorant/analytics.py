"""Aggregations and coaching insights for the dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .db import Database

ATTACK = "attack"
DEFENSE = "defense"


# --------------------------------------------------------------------- helpers
def _div(value: float, divisor: float, default: float = 0.0) -> float:
    if not divisor:
        return default
    return value / divisor


def _pct(value: float, total: float) -> float:
    if not total:
        return 0.0
    return round(100.0 * value / total, 1)


def _round(value: float, digits: int = 1) -> float:
    return round(float(value or 0), digits)


def _ratio(value: float, base: float) -> float:
    if not base:
        return 1.0 if not value else 1.0
    return value / base


def _empty_side() -> Dict[str, Any]:
    return {
        "rounds": 0,
        "wins": 0,
        "kills": 0,
        "deaths": 0,
        "assists": 0,
        "score": 0,
        "damage": 0,
        "first_blood": 0,
        "first_death": 0,
    }


def _empty_acc() -> Dict[str, Any]:
    return {
        "matches": 0,
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "kills": 0,
        "deaths": 0,
        "assists": 0,
        "combat_score": 0,
        "damage": 0,
        "headshots": 0,
        "bodyshots": 0,
        "legshots": 0,
        "rounds": 0,
        "sides": {ATTACK: _empty_side(), DEFENSE: _empty_side()},
    }


def _add_round(side_acc: Dict[str, Any], row: Dict[str, Any]) -> None:
    side_acc["rounds"] += 1
    side_acc["wins"] += 1 if row.get("won") else 0
    side_acc["kills"] += int(row.get("kills") or 0)
    side_acc["deaths"] += int(row.get("deaths") or 0)
    side_acc["assists"] += int(row.get("assists") or 0)
    side_acc["score"] += int(row.get("score") or 0)
    side_acc["damage"] += int(row.get("damage") or 0)
    side_acc["first_blood"] += 1 if row.get("first_blood_mine") else 0
    side_acc["first_death"] += 1 if row.get("first_death_mine") else 0


def _add_match(acc: Dict[str, Any], match: Dict[str, Any], rounds: List[Dict[str, Any]]) -> None:
    acc["matches"] += 1
    mine = int(match.get("score_mine") or 0)
    enemy = int(match.get("score_enemy") or 0)
    if mine > enemy:
        acc["wins"] += 1
    elif mine == enemy:
        acc["draws"] += 1
    acc["kills"] += int(match.get("kills") or 0)
    acc["deaths"] += int(match.get("deaths") or 0)
    acc["assists"] += int(match.get("assists") or 0)
    acc["combat_score"] += int(match.get("combat_score") or 0)
    acc["damage"] += int(match.get("damage_dealt") or 0)
    acc["headshots"] += int(match.get("headshots") or 0)
    acc["bodyshots"] += int(match.get("bodyshots") or 0)
    acc["legshots"] += int(match.get("legshots") or 0)
    acc["rounds"] += int(match.get("rounds_played") or 0)
    for row in rounds:
        side = row.get("side")
        if side in (ATTACK, DEFENSE):
            _add_round(acc["sides"][side], row)


def _finalize_side(side: Dict[str, Any]) -> Dict[str, Any]:
    rounds = side["rounds"]
    return {
        "rounds": rounds,
        "wins": side["wins"],
        "round_win_rate": _pct(side["wins"], rounds),
        "kills": side["kills"],
        "deaths": side["deaths"],
        "assists": side["assists"],
        "kd": _round(_div(side["kills"], side["deaths"], side["kills"]), 2),
        "kda": _round(_div(side["kills"] + side["assists"], side["deaths"], side["kills"] + side["assists"]), 2),
        "acs": _round(_div(side["score"], rounds)),
        "adr": _round(_div(side["damage"], rounds)),
        "first_blood_pct": _pct(side["first_blood"], rounds),
        "first_death_pct": _pct(side["first_death"], rounds),
        "first_blood": side["first_blood"],
        "first_death": side["first_death"],
    }


def _finalize(acc: Dict[str, Any], kind: str) -> Dict[str, Any]:
    matches = acc["matches"]
    wins = acc["wins"]
    draws = acc["draws"]
    losses = max(0, matches - wins - draws)
    rounds = acc["rounds"]
    hs_total = acc["headshots"] + acc["bodyshots"] + acc["legshots"]
    attack = _finalize_side(acc["sides"][ATTACK])
    defense = _finalize_side(acc["sides"][DEFENSE])
    side_rounds = attack["rounds"] + defense["rounds"]
    return {
        "matches": matches,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": _pct(wins, matches),
        "kills": acc["kills"],
        "deaths": acc["deaths"],
        "assists": acc["assists"],
        "kd": _round(_div(acc["kills"], acc["deaths"], acc["kills"]), 2),
        "kda": _round(_div(acc["kills"] + acc["assists"], acc["deaths"], acc["kills"] + acc["assists"]), 2),
        "acs": _round(_div(acc["combat_score"], rounds)),
        "adr": _round(_div(acc["damage"], rounds)),
        "hs_pct": _pct(acc["headshots"], hs_total),
        "rounds": rounds,
        "round_win_rate": _pct(attack["wins"] + defense["wins"], side_rounds),
        "attack": attack,
        "defense": defense,
        "first_blood_pct": _pct(attack["first_blood"] + defense["first_blood"], side_rounds),
        "first_death_pct": _pct(attack["first_death"] + defense["first_death"], side_rounds),
        "impact": 100.0,
        "kind": kind,
    }


def _apply_impact(groups: List[Dict[str, Any]], base: Dict[str, Any]) -> None:
    for group in groups:
        parts = (
            (0.45, _ratio(group["acs"], base["acs"])),
            (0.30, _ratio(group["kd"], base["kd"])),
            (0.25, _ratio(group["win_rate"], base["win_rate"])),
        )
        score = sum(weight * ratio for weight, ratio in parts) * 100.0
        group["impact"] = round(max(60.0, min(145.0, score)), 1)


def _reliability(n: int, kind: str) -> str:
    if kind == "agent":
        return "high" if n >= 10 else "medium" if n >= 5 else "low"
    if kind == "map":
        return "high" if n >= 8 else "medium" if n >= 4 else "low"
    if kind == "side":
        return "high" if n >= 100 else "medium" if n >= 40 else "low"
    return "medium" if n >= 10 else "low"


def _date_label(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d/%m")
    except ValueError:
        return iso[:10]


def _priority(group: Dict[str, Any], direction: str) -> float:
    """Rank strengths/weaknesses by gap to baseline, tempered by sample size."""
    sample_factor = 0.2 + 0.8 * min(group["matches"], 20) / 20.0
    gap = group["impact"] - 100.0 if direction == "strength" else 100.0 - group["impact"]
    return gap * sample_factor


# --------------------------------------------------------------------- insights
def _build_insights(
    summary: Dict[str, Any],
    agents: List[Dict[str, Any]],
    maps: List[Dict[str, Any]],
    trend: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []
    base = summary

    agent_pool = [a for a in agents if a["matches"] >= 3]
    if len(agent_pool) >= 2:
        best = max(agent_pool, key=lambda a: _priority(a, "strength"))
        worst = max(agent_pool, key=lambda a: _priority(a, "weakness"))
        if best["impact"] >= 103:
            delta = round((best["acs"] / base["acs"] - 1) * 100) if base["acs"] else 0
            insights.append(
                {
                    "kind": "strength",
                    "tag": "AGENT",
                    "title": f"{best['name']} est ton meilleur agent",
                    "detail": (
                        f"{best['win_rate']:.0f} % de victoires sur {best['matches']} parties · "
                        f"ACS {best['acs']:.0f} ({delta:+d} % vs ta moyenne)."
                    ),
                    "confidence": _reliability(best["matches"], "agent"),
                    "sample": best["matches"],
                }
            )
        if worst["id"] != best["id"] and worst["impact"] <= 97:
            delta = round((worst["acs"] / base["acs"] - 1) * 100) if base["acs"] else 0
            insights.append(
                {
                    "kind": "weakness",
                    "tag": "AGENT",
                    "title": f"Progresse sur {worst['name']}",
                    "detail": (
                        f"{worst['win_rate']:.0f} % de victoires sur {worst['matches']} parties · "
                        f"ACS {worst['acs']:.0f} ({delta:+d} % vs ta moyenne)."
                    ),
                    "confidence": _reliability(worst["matches"], "agent"),
                    "sample": worst["matches"],
                }
            )

    map_pool = [m for m in maps if m["matches"] >= 2]
    if len(map_pool) >= 2:
        best_map = max(map_pool, key=lambda m: _priority(m, "strength"))
        worst_map = max(map_pool, key=lambda m: _priority(m, "weakness"))
        if best_map["impact"] >= 104:
            insights.append(
                {
                    "kind": "strength",
                    "tag": "MAP",
                    "title": f"Tu domines {best_map['name']}",
                    "detail": (
                        f"{best_map['win_rate']:.0f} % de victoires sur {best_map['matches']} parties · "
                        f"ACS {best_map['acs']:.0f}, K/D {best_map['kd']:.2f}."
                    ),
                    "confidence": _reliability(best_map["matches"], "map"),
                    "sample": best_map["matches"],
                }
            )
        if worst_map["id"] != best_map["id"] and worst_map["impact"] <= 96:
            insights.append(
                {
                    "kind": "weakness",
                    "tag": "MAP",
                    "title": f"Travaille {worst_map['name']}",
                    "detail": (
                        f"{worst_map['win_rate']:.0f} % de victoires sur {worst_map['matches']} parties · "
                        f"ACS {worst_map['acs']:.0f}, K/D {worst_map['kd']:.2f}."
                    ),
                    "confidence": _reliability(worst_map["matches"], "map"),
                    "sample": worst_map["matches"],
                }
            )

    atk = summary["attack"]
    dfn = summary["defense"]
    if atk["rounds"] >= 15 and dfn["rounds"] >= 15:
        gap = atk["round_win_rate"] - dfn["round_win_rate"]
        if abs(gap) >= 6:
            weak = "défense" if gap > 0 else "attaque"
            strong = "attaque" if gap > 0 else "défense"
            weak_stats = dfn if gap > 0 else atk
            strong_stats = atk if gap > 0 else dfn
            action = (
                "Priorité : retakes, tenue des sites et communication des rotations."
                if weak == "défense"
                else "Priorité : ouverture de site, usage de l'utilité et trades d'entrée."
            )
            insights.append(
                {
                    "kind": "weakness",
                    "tag": "CÔTÉ",
                    "title": f"Ton côté {weak} te coûte des rounds",
                    "detail": (
                        f"{weak_stats['round_win_rate']:.0f} % de rounds gagnés en {weak} contre "
                        f"{strong_stats['round_win_rate']:.0f} % en {strong} ({gap:+.0f} pts). {action}"
                    ),
                    "confidence": _reliability(weak_stats["rounds"], "side"),
                    "sample": weak_stats["rounds"],
                }
            )
        else:
            insights.append(
                {
                    "kind": "info",
                    "tag": "CÔTÉ",
                    "title": "Profil équilibré attaque / défense",
                    "detail": (
                        f"{atk['round_win_rate']:.0f} % de rounds en attaque et "
                        f"{dfn['round_win_rate']:.0f} % en défense : pas de côté à sacrifier en priorité."
                    ),
                    "confidence": _reliability(min(atk["rounds"], dfn["rounds"]), "side"),
                    "sample": min(atk["rounds"], dfn["rounds"]),
                }
            )

    side_rounds = atk["rounds"] + dfn["rounds"]
    if side_rounds >= 40:
        if summary["first_death_pct"] >= 21:
            insights.append(
                {
                    "kind": "weakness",
                    "tag": "OUVERTURE",
                    "title": "Tu meurs en premier trop souvent",
                    "detail": (
                        f"{summary['first_death_pct']:.0f} % des rounds commencent par ta mort. "
                        "Joue plus safe en entrée et laisse un équipier prendre le premier duel."
                    ),
                    "confidence": _reliability(side_rounds, "side"),
                    "sample": side_rounds,
                }
            )
        elif summary["first_blood_pct"] >= 54:
            insights.append(
                {
                    "kind": "strength",
                    "tag": "OUVERTURE",
                    "title": "Tu gagnes la majorité de tes opening duels",
                    "detail": (
                        f"Ton équipe obtient le premier kill dans {summary['first_blood_pct']:.0f} % des rounds. "
                        "C'est un vrai moteur de round : garde ce tempo."
                    ),
                    "confidence": _reliability(side_rounds, "side"),
                    "sample": side_rounds,
                }
            )

    if len(trend) >= 12:
        recent = trend[-10:]
        previous = trend[-20:-10] if len(trend) >= 20 else trend[:-10]
        if len(previous) >= 5:
            recent_wr = _pct(sum(r["won"] for r in recent), len(recent))
            prev_wr = _pct(sum(r["won"] for r in previous), len(previous))
            recent_acs = _round(sum(r["acs"] for r in recent) / len(recent))
            prev_acs = _round(sum(r["acs"] for r in previous) / len(previous))
            if recent_wr - prev_wr >= 12 or recent_acs - prev_acs >= 18:
                insights.append(
                    {
                        "kind": "strength",
                        "tag": "FORME",
                        "title": "Forme ascendante",
                        "detail": (
                            f"Sur tes {len(recent)} dernières parties : {recent_wr:.0f} % de victoires et "
                            f"ACS {recent_acs:.0f}, contre {prev_wr:.0f} % et {prev_acs:.0f} avant."
                        ),
                        "confidence": "medium",
                        "sample": len(recent),
                    }
                )
            elif prev_wr - recent_wr >= 12 or prev_acs - recent_acs >= 18:
                insights.append(
                    {
                        "kind": "weakness",
                        "tag": "FORME",
                        "title": "Coup de moins bien récent",
                        "detail": (
                            f"Sur tes {len(recent)} dernières parties : {recent_wr:.0f} % de victoires et "
                            f"ACS {recent_acs:.0f}, contre {prev_wr:.0f} % et {prev_acs:.0f} avant."
                        ),
                        "confidence": "medium",
                        "sample": len(recent),
                    }
                )

    if not insights:
        insights.append(
            {
                "kind": "info",
                "tag": "DONNÉES",
                "title": "Encore trop peu de parties pour conclure",
                "detail": (
                    "Joue quelques parties de plus ou élargis la période : les comparaisons par agent, "
                    "map et côté deviennent fiables à partir de 3 parties par groupe."
                ),
                "confidence": "low",
                "sample": summary["matches"],
            }
        )
    return insights[:8]


# ------------------------------------------------------------------------- main
def compute(db: Database, mode: str = "tactical", days: int = 90) -> Dict[str, Any]:
    matches = db.query_matches(mode=mode, days=days)
    rounds_by_match = db.rounds_for([m["match_id"] for m in matches])

    overall = _empty_acc()
    agent_accs: Dict[str, Dict[str, Any]] = {}
    map_accs: Dict[str, Dict[str, Any]] = {}
    match_cards: List[Dict[str, Any]] = []

    for match in matches:
        rounds = rounds_by_match.get(match["match_id"], [])
        _add_match(overall, match, rounds)

        agent_key = match.get("agent_id") or "unknown"
        if agent_key not in agent_accs:
            agent_accs[agent_key] = {
                "acc": _empty_acc(),
                "id": agent_key,
                "name": match.get("agent_name") or "Inconnu",
            }
        _add_match(agent_accs[agent_key]["acc"], match, rounds)

        map_key = match.get("map_id") or "unknown"
        if map_key not in map_accs:
            map_accs[map_key] = {
                "acc": _empty_acc(),
                "id": map_key,
                "name": match.get("map_name") or "Inconnue",
            }
        _add_match(map_accs[map_key]["acc"], match, rounds)

        atk = _empty_side()
        dfn = _empty_side()
        for row in rounds:
            if row.get("side") == ATTACK:
                _add_round(atk, row)
            elif row.get("side") == DEFENSE:
                _add_round(dfn, row)
        mine = int(match.get("score_mine") or 0)
        enemy = int(match.get("score_enemy") or 0)
        match_cards.append(
            {
                "match_id": match["match_id"],
                "date": match["started_at"],
                "date_label": _date_label(match["started_at"]),
                "map": match.get("map_name") or "Inconnue",
                "map_id": match.get("map_id"),
                "agent": match.get("agent_name") or "Inconnu",
                "agent_id": match.get("agent_id"),
                "queue": match.get("queue_name") or match.get("queue_id") or "",
                "queue_id": match.get("queue_id") or "",
                "won": 1 if mine > enemy else 0,
                "draw": 1 if mine == enemy else 0,
                "score": f"{mine}-{enemy}",
                "score_mine": mine,
                "score_enemy": enemy,
                "kills": int(match.get("kills") or 0),
                "deaths": int(match.get("deaths") or 0),
                "assists": int(match.get("assists") or 0),
                "acs": _round(_div(match.get("combat_score") or 0, match.get("rounds_played") or 0)),
                "kd": _round(_div(match.get("kills") or 0, match.get("deaths") or 0, match.get("kills") or 0), 2),
                "attack_rounds": atk["rounds"],
                "attack_wins": atk["wins"],
                "defense_rounds": dfn["rounds"],
                "defense_wins": dfn["wins"],
            }
        )

    summary = _finalize(overall, "overall")
    agents = []
    for item in agent_accs.values():
        row = _finalize(item["acc"], "agent")
        row.update({"id": item["id"], "name": item["name"]})
        row["reliability"] = _reliability(row["matches"], "agent")
        agents.append(row)

    maps = []
    for item in map_accs.values():
        row = _finalize(item["acc"], "map")
        row.update({"id": item["id"], "name": item["name"]})
        row["reliability"] = _reliability(row["matches"], "map")
        maps.append(row)

    _apply_impact(agents, summary)
    _apply_impact(maps, summary)
    agents.sort(key=lambda a: (-a["matches"], -a["impact"]))
    maps.sort(key=lambda m: (-m["matches"], -m["impact"]))

    chronological = sorted(match_cards, key=lambda m: m["date"])
    trend = [
        {
            "date": card["date"],
            "label": card["date_label"],
            "acs": card["acs"],
            "kd": card["kd"],
            "won": card["won"],
            "draw": card["draw"],
            "agent": card["agent"],
            "map": card["map"],
            "score": card["score"],
        }
        for card in chronological[-60:]
    ]

    recent = sorted(match_cards, key=lambda m: m["date"], reverse=True)[:60]
    insights = _build_insights(summary, agents, maps, trend)

    return {
        "meta": {
            "mode": mode,
            "days": days,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "demo": db.has_demo(),
            "has_data": bool(matches),
            "matches": len(matches),
        },
        "summary": summary,
        "agents": agents,
        "maps": maps,
        "trend": trend,
        "recent": recent,
        "insights": insights,
    }
