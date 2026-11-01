"""SQLite storage for normalized Valorant matches and round stats."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

NON_TACTICAL_QUEUES = (
    "deathmatch",
    "teamdeathmatch",
    "hurm",
    "spikerush",
    "escalation",
    "replication",
    "snowball",
    "gungame",
    "onefa",
    "skirmish",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    map_id TEXT,
    map_name TEXT,
    queue_id TEXT,
    queue_name TEXT,
    mode_type TEXT,
    agent_id TEXT,
    agent_name TEXT,
    puuid TEXT,
    team_id TEXT,
    won INTEGER NOT NULL DEFAULT 0,
    score_mine INTEGER NOT NULL DEFAULT 0,
    score_enemy INTEGER NOT NULL DEFAULT 0,
    kills INTEGER NOT NULL DEFAULT 0,
    deaths INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    combat_score INTEGER NOT NULL DEFAULT 0,
    damage_dealt INTEGER NOT NULL DEFAULT 0,
    damage_received INTEGER NOT NULL DEFAULT 0,
    headshots INTEGER NOT NULL DEFAULT 0,
    bodyshots INTEGER NOT NULL DEFAULT 0,
    legshots INTEGER NOT NULL DEFAULT 0,
    rounds_played INTEGER NOT NULL DEFAULT 0,
    tier_name TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matches_started ON matches(started_at);
CREATE INDEX IF NOT EXISTS idx_matches_queue ON matches(queue_id);
CREATE INDEX IF NOT EXISTS idx_matches_agent ON matches(agent_id);
CREATE INDEX IF NOT EXISTS idx_matches_map ON matches(map_id);

CREATE TABLE IF NOT EXISTS rounds (
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
    end_cause TEXT,
    PRIMARY KEY (match_id, round_num),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_rounds_match ON rounds(match_id);
CREATE INDEX IF NOT EXISTS idx_rounds_side ON rounds(side);

CREATE TABLE IF NOT EXISTS mmr_history (
    match_id TEXT PRIMARY KEY,
    played_at TEXT NOT NULL,
    rr INTEGER NOT NULL DEFAULT 0,
    last_change INTEGER NOT NULL DEFAULT 0,
    elo INTEGER NOT NULL DEFAULT 0,
    tier_id INTEGER,
    tier_name TEXT,
    map_id TEXT,
    map_name TEXT,
    season_id TEXT,
    season_short TEXT,
    is_demo INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mmr_history_date ON mmr_history(played_at);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

MATCH_FIELDS = (
    "match_id",
    "started_at",
    "map_id",
    "map_name",
    "queue_id",
    "queue_name",
    "mode_type",
    "agent_id",
    "agent_name",
    "puuid",
    "team_id",
    "won",
    "score_mine",
    "score_enemy",
    "kills",
    "deaths",
    "assists",
    "combat_score",
    "damage_dealt",
    "damage_received",
    "headshots",
    "bodyshots",
    "legshots",
    "rounds_played",
    "tier_name",
    "is_demo",
    "synced_at",
)

ROUND_FIELDS = (
    "match_id",
    "round_num",
    "side",
    "won",
    "kills",
    "deaths",
    "assists",
    "score",
    "damage",
    "headshots",
    "bodyshots",
    "legshots",
    "first_blood_mine",
    "first_death_mine",
    "end_cause",
)

ROUND_TEXT_FIELDS = {"end_cause"}

MMR_FIELDS = (
    "match_id",
    "played_at",
    "rr",
    "last_change",
    "elo",
    "tier_id",
    "tier_name",
    "map_id",
    "map_name",
    "season_id",
    "season_short",
    "is_demo",
    "synced_at",
)

MMR_NUMERIC_FIELDS = {"rr", "last_change", "elo", "is_demo"}


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Bring databases created by older versions up to date."""
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(rounds)")}
        if "end_cause" not in columns:
            conn.execute("ALTER TABLE rounds ADD COLUMN end_cause TEXT")

    # ------------------------------------------------------------------ writes
    def upsert_match(self, match: Dict[str, Any], rounds: Iterable[Dict[str, Any]]) -> None:
        values = [match.get(field, 0) for field in MATCH_FIELDS]
        placeholders = ",".join("?" for _ in MATCH_FIELDS)
        columns = ",".join(MATCH_FIELDS)
        round_rows = [
            tuple(
                r.get(field) if field in ROUND_TEXT_FIELDS else r.get(field, 0)
                for field in ROUND_FIELDS
            )
            for r in rounds
        ]
        with self.connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO matches ({columns}) VALUES ({placeholders})",
                values,
            )
            conn.execute("DELETE FROM rounds WHERE match_id = ?", (match["match_id"],))
            if round_rows:
                conn.executemany(
                    f"INSERT OR REPLACE INTO rounds ({','.join(ROUND_FIELDS)}) VALUES ({','.join('?' for _ in ROUND_FIELDS)})",
                    round_rows,
                )

    def upsert_mmr_history(self, rows: Iterable[Dict[str, Any]]) -> int:
        values = [
            tuple(
                (row.get(field) if row.get(field) is not None else 0)
                if field in MMR_NUMERIC_FIELDS
                else row.get(field)
                for field in MMR_FIELDS
            )
            for row in rows
            if row.get("match_id")
        ]
        if not values:
            return 0
        with self.connect() as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO mmr_history ({','.join(MMR_FIELDS)}) "
                f"VALUES ({','.join('?' for _ in MMR_FIELDS)})",
                values,
            )
        return len(values)

    def set_meta(self, key: str, value: Any) -> None:
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_meta(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]

    def delete_demo(self) -> int:
        with self.connect() as conn:
            conn.execute("DELETE FROM rounds WHERE match_id IN (SELECT match_id FROM matches WHERE is_demo = 1)")
            conn.execute("DELETE FROM mmr_history WHERE is_demo = 1")
            cur = conn.execute("DELETE FROM matches WHERE is_demo = 1")
            return cur.rowcount

    def delete_all(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM rounds")
            conn.execute("DELETE FROM mmr_history")
            conn.execute("DELETE FROM matches")

    def delete_real(self) -> int:
        with self.connect() as conn:
            conn.execute("DELETE FROM rounds WHERE match_id IN (SELECT match_id FROM matches WHERE is_demo = 0)")
            conn.execute("DELETE FROM mmr_history WHERE is_demo = 0")
            cur = conn.execute("DELETE FROM matches WHERE is_demo = 0")
            return cur.rowcount

    def delete_non_competitive(self) -> int:
        """Drop stored real games that are known to be outside ranked queues."""
        condition = "is_demo = 0 AND queue_id IS NOT NULL AND queue_id NOT IN ('', 'unknown', 'competitive')"
        with self.connect() as conn:
            conn.execute(f"DELETE FROM rounds WHERE match_id IN (SELECT match_id FROM matches WHERE {condition})")
            cur = conn.execute(f"DELETE FROM matches WHERE {condition}")
            return cur.rowcount

    def delete_meta(self, key: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM meta WHERE key = ?", (key,))

    def delete_match(self, match_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
            conn.execute("DELETE FROM mmr_history WHERE match_id = ?", (match_id,))

    # ------------------------------------------------------------------- reads
    def count_matches(self, demo: Optional[bool] = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM matches"
        params: List[Any] = []
        if demo is not None:
            sql += " WHERE is_demo = ?"
            params.append(1 if demo else 0)
        with self.connect() as conn:
            return int(conn.execute(sql, params).fetchone()["n"])

    def existing_ids(self) -> set:
        with self.connect() as conn:
            return {row["match_id"] for row in conn.execute("SELECT match_id FROM matches")}

    def latest_match_at(self) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(started_at) AS ts FROM matches").fetchone()
        return row["ts"] if row and row["ts"] else None

    def query_matches(
        self,
        mode: str = "tactical",
        days: int = 0,
        map_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["1=1"]
        params: List[Any] = []
        if days and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            clauses.append("started_at >= ?")
            params.append(cutoff)
        if mode == "tactical":
            placeholders = ",".join("?" for _ in NON_TACTICAL_QUEUES)
            clauses.append(f"(queue_id IS NULL OR queue_id NOT IN ({placeholders}))")
            params.extend(NON_TACTICAL_QUEUES)
        elif mode and mode not in ("all", "tactical"):
            clauses.append("queue_id = ?")
            params.append(mode)
        if map_id:
            clauses.append("map_id = ?")
            params.append(map_id)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        sql = "SELECT * FROM matches WHERE " + " AND ".join(clauses) + " ORDER BY started_at DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def rounds_for(self, match_ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
        if not match_ids:
            return {}
        out: Dict[str, List[Dict[str, Any]]] = {}
        with self.connect() as conn:
            for start in range(0, len(match_ids), 400):
                chunk = list(match_ids[start : start + 400])
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM rounds WHERE match_id IN ({placeholders}) ORDER BY round_num",
                    chunk,
                ).fetchall()
                for row in rows:
                    out.setdefault(row["match_id"], []).append(dict(row))
        return out

    def query_mmr_history(self, days: int = 0, demo: Optional[bool] = None) -> List[Dict[str, Any]]:
        clauses = ["1=1"]
        params: List[Any] = []
        if days and days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
            clauses.append("played_at >= ?")
            params.append(cutoff)
        if demo is not None:
            clauses.append("is_demo = ?")
            params.append(1 if demo else 0)
        sql = "SELECT * FROM mmr_history WHERE " + " AND ".join(clauses) + " ORDER BY played_at ASC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def count_mmr_history(self, demo: Optional[bool] = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM mmr_history"
        params: List[Any] = []
        if demo is not None:
            sql += " WHERE is_demo = ?"
            params.append(1 if demo else 0)
        with self.connect() as conn:
            return int(conn.execute(sql, params).fetchone()["n"])

    def match_ids_missing_end_cause(self, queue_mode: str = "tactical", limit: int = 60) -> List[str]:
        """Return stored real matches whose rounds have no end-of-round cause yet."""
        clauses = [
            "m.is_demo = 0",
            "m.rounds_played > 0",
            "("
            "NOT EXISTS (SELECT 1 FROM rounds r WHERE r.match_id = m.match_id) "
            "OR EXISTS (SELECT 1 FROM rounds r WHERE r.match_id = m.match_id AND r.end_cause IS NULL)"
            ")",
        ]
        params: List[Any] = []
        if queue_mode == "competitive":
            clauses.append("(m.queue_id IS NULL OR m.queue_id IN ('', 'unknown', 'competitive'))")
        else:
            placeholders = ",".join("?" for _ in NON_TACTICAL_QUEUES)
            clauses.append(f"(m.queue_id IS NULL OR m.queue_id NOT IN ({placeholders}))")
            params.extend(NON_TACTICAL_QUEUES)
        sql = (
            "SELECT m.match_id FROM matches m WHERE "
            + " AND ".join(clauses)
            + " ORDER BY m.started_at DESC LIMIT ?"
        )
        params.append(max(1, int(limit)))
        with self.connect() as conn:
            return [row["match_id"] for row in conn.execute(sql, params).fetchall()]

    def filter_options(self) -> Dict[str, Any]:
        with self.connect() as conn:
            queues = [
                dict(row)
                for row in conn.execute(
                    "SELECT queue_id AS id, COALESCE(queue_name, queue_id) AS name, COUNT(*) AS count "
                    "FROM matches GROUP BY queue_id, queue_name ORDER BY count DESC"
                )
            ]
            maps = [
                dict(row)
                for row in conn.execute(
                    "SELECT map_id AS id, COALESCE(map_name, map_id) AS name, COUNT(*) AS count "
                    "FROM matches GROUP BY map_id, map_name ORDER BY count DESC"
                )
            ]
            agents = [
                dict(row)
                for row in conn.execute(
                    "SELECT agent_id AS id, COALESCE(agent_name, agent_id) AS name, COUNT(*) AS count "
                    "FROM matches GROUP BY agent_id, agent_name ORDER BY count DESC"
                )
            ]
        return {"queues": queues, "maps": maps, "agents": agents}

    def has_demo(self) -> bool:
        return self.count_matches(demo=True) > 0

    def match_dates(self) -> List[str]:
        with self.connect() as conn:
            return [row["started_at"] for row in conn.execute("SELECT started_at FROM matches ORDER BY started_at")]
