"""Background synchronization with the HenrikDev API."""
from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from .config import is_configured, load_config
from .db import Database
from .henrik import HenrikClient, HenrikError
from .parser import normalize_match

SYNC_INTERVAL_HOURS = 24


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _date_iso(value: Any) -> str:
    if isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return _now_iso()
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not value:
        return _now_iso()
    text = str(value).strip().replace("Z", "+00:00").replace(" ", "T")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return _now_iso()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_mmr_history(history: Any, is_demo: bool = False) -> list:
    """Flatten a v2 MMR-history payload into rows for the local database."""
    if isinstance(history, dict):
        history = history.get("history") or []
    if not isinstance(history, list):
        return []
    rows = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        match_id = entry.get("match_id") or ""
        if not match_id:
            continue
        tier = entry.get("tier") if isinstance(entry.get("tier"), dict) else {}
        map_info = entry.get("map") if isinstance(entry.get("map"), dict) else {}
        season = entry.get("season") if isinstance(entry.get("season"), dict) else {}
        rows.append(
            {
                "match_id": match_id,
                "played_at": _date_iso(entry.get("date")),
                "rr": _as_int(entry.get("rr", entry.get("ranking_in_tier"))),
                "last_change": _as_int(
                    entry.get("last_change", entry.get("mmr_change_to_last_game"))
                ),
                "elo": _as_int(entry.get("elo")),
                "tier_id": _as_int(tier.get("id")),
                "tier_name": tier.get("name") or entry.get("currenttierpatched") or "",
                "map_id": map_info.get("id") or "",
                "map_name": map_info.get("name") or "",
                "season_id": season.get("id") or entry.get("season_id") or "",
                "season_short": season.get("short") or "",
                "is_demo": 1 if is_demo else 0,
                "synced_at": _now_iso(),
            }
        )
    return rows


def match_queue_id(raw: Dict[str, Any]) -> str:
    """Return the queue id carried by a v4 match payload ("" when unknown)."""
    metadata = raw.get("metadata") or {}
    queue = metadata.get("queue") or {}
    if isinstance(queue, dict):
        queue = queue.get("id") or ""
    return str(queue).strip().lower()


def keep_queue(raw: Dict[str, Any], queue_mode: str) -> bool:
    """Keep competitive-only payloads when the config asks for ranked games.

    An unknown queue is kept so the caller can inspect the full match payload
    instead of silently dropping a valid game.
    """
    if queue_mode != "competitive":
        return True
    return match_queue_id(raw) in ("", "competitive")


def profile_from_account(account: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": account.get("name") or "",
        "tag": account.get("tag") or "",
        "puuid": account.get("puuid") or "",
        "region": account.get("region") or "",
        "card": account.get("card") or "",
        "level": account.get("account_level") or 0,
        "rank": "",
        "rr": None,
        "peak": "",
        "updated_at": _now_iso(),
    }


def apply_mmr(profile: Dict[str, Any], mmr: Dict[str, Any]) -> Dict[str, Any]:
    current = mmr.get("current") or {}
    tier = current.get("tier") or {}
    if isinstance(tier, dict):
        profile["rank"] = tier.get("name") or ""
    profile["rr"] = current.get("rr")
    peak = mmr.get("peak") or {}
    peak_tier = peak.get("tier") if isinstance(peak, dict) else None
    if isinstance(peak_tier, dict):
        profile["peak"] = peak_tier.get("name") or ""
    return profile


class SyncManager:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status: Dict[str, Any] = {
            "state": "idle",
            "message": "",
            "progress": 0,
            "total": 0,
            "new_matches": 0,
            "started_at": None,
            "finished_at": None,
            "error": None,
        }

    # ------------------------------------------------------------------ public
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            data = dict(self._status)
        data["last_sync"] = self.db.get_meta("last_sync")
        data["stale"] = self.is_stale()
        return data

    def is_stale(self) -> bool:
        last = _parse_iso(self.db.get_meta("last_sync"))
        if last is None:
            return True
        return datetime.now(timezone.utc) - last > timedelta(hours=SYNC_INTERVAL_HOURS)

    def start(self, full: bool = False) -> bool:
        with self._lock:
            if self._status["state"] == "running":
                return False
            cfg = load_config()
            if not is_configured(cfg):
                self._status = {
                    "state": "error",
                    "message": "Compte non configuré",
                    "progress": 0,
                    "total": 0,
                    "new_matches": 0,
                    "started_at": None,
                    "finished_at": _now_iso(),
                    "error": "Renseigne ton Riot ID et ta clé API HenrikDev dans les réglages.",
                }
                return False
            self._status = {
                "state": "running",
                "message": "Connexion à l'API…",
                "progress": 0,
                "total": 1,
                "new_matches": 0,
                "started_at": _now_iso(),
                "finished_at": None,
                "error": None,
            }
            self._thread = threading.Thread(target=self._run, args=(full,), daemon=True)
            self._thread.start()
            return True

    def auto_sync_if_needed(self) -> bool:
        if not is_configured(load_config()):
            return False
        if self.is_stale():
            return self.start()
        return False

    # ---------------------------------------------------------------- internals
    def _update(self, **changes: Any) -> None:
        with self._lock:
            self._status.update(changes)

    def _run(self, full: bool) -> None:
        cfg = load_config()
        client = HenrikClient(cfg["api_key"])
        name, tag = cfg["riot_name"], cfg["riot_tag"]
        region, platform = cfg["region"], cfg["platform"]

        try:
            self._update(message=f"Récupération du compte {name}#{tag}…", progress=0, total=1)
            account = client.account(name, tag)
            if not isinstance(account, dict) or not account.get("puuid"):
                raise HenrikError("Compte introuvable ou réponse inattendue de l'API.", 404)
            puuid = account["puuid"]
            profile = profile_from_account(account)

            try:
                self._update(message="Récupération du rang…", progress=0, total=1)
                mmr = client.mmr(region, platform, name, tag)
                if isinstance(mmr, dict):
                    apply_mmr(profile, mmr)
            except HenrikError:
                # Unranked / MMR unavailable is not fatal.
                pass

            try:
                self._update(message="Récupération de l'historique RR…", progress=0, total=1)
                history = client.mmr_history(region, platform, name, tag)
                mmr_rows = normalize_mmr_history(history)
                if mmr_rows:
                    self.db.upsert_mmr_history(mmr_rows)
            except (HenrikError, AttributeError):
                # The RR history is a bonus: keep syncing matches if it fails.
                pass

            queue_mode = cfg.get("queue_mode", "competitive")
            existing = self.db.existing_ids()
            target = int(cfg["backfill"])
            base_pages = max(1, math.ceil(target / 10))
            # Competitive-only syncs skip unranked games, so scan more history to
            # still collect the requested number of ranked matches.
            pages = min(base_pages * 2, 20) if queue_mode == "competitive" else base_pages
            new_count = 0
            skipped = 0
            scanned = 0
            known_found = False

            for page in range(pages):
                self._update(
                    message=f"Récupération des parties ({page + 1}/{pages})…",
                    progress=page,
                    total=pages,
                )
                batch = client.matches(region, platform, name, tag, start=page * 10, size=10)
                if not batch:
                    break
                scanned += 1
                for raw in batch:
                    metadata = raw.get("metadata") or {}
                    match_id = metadata.get("match_id")
                    if not match_id:
                        continue
                    if not keep_queue(raw, queue_mode):
                        skipped += 1
                        continue
                    if match_id in existing and not full:
                        known_found = True
                        continue
                    if not raw.get("rounds") or not raw.get("players"):
                        raw = client.match(region, match_id)
                    # The list payload may omit the queue: check again on the
                    # detailed match before storing it.
                    if not keep_queue(raw, queue_mode):
                        skipped += 1
                        continue
                    parsed = normalize_match(raw, puuid)
                    if not parsed:
                        continue
                    row, rounds = parsed
                    row["is_demo"] = 0
                    self.db.upsert_match(row, rounds)
                    existing.add(match_id)
                    new_count += 1
                    self._update(new_matches=new_count)
                if known_found and not full:
                    break

            if self.db.has_demo():
                self.db.delete_demo()

            # Older databases predate the end-of-round cause column. Complete
            # them once, without forcing the user to trigger a full re-sync.
            backfilled = 0
            missing = self.db.match_ids_missing_end_cause(queue_mode=queue_mode, limit=60)
            if missing:
                for index, match_id in enumerate(missing):
                    self._update(
                        message=f"Complétion des fins de round ({index + 1}/{len(missing)})…",
                        progress=index,
                        total=len(missing),
                    )
                    try:
                        raw = client.match(region, match_id)
                    except HenrikError:
                        continue
                    parsed = normalize_match(raw, puuid)
                    if not parsed:
                        continue
                    row, rounds = parsed
                    if not rounds or not any(round_row.get("end_cause") for round_row in rounds):
                        continue
                    row["is_demo"] = 0
                    self.db.upsert_match(row, rounds)
                    backfilled += 1

            self.db.set_meta("profile", profile)
            self.db.set_meta("last_sync", _now_iso())
            message = (
                f"{new_count} nouvelle{'s' if new_count > 1 else ''} partie{'s' if new_count > 1 else ''} importée{'s' if new_count > 1 else ''}"
                if new_count
                else "Déjà à jour"
            )
            if skipped:
                message += (
                    f" · {skipped} partie{'s' if skipped > 1 else ''} hors compétitif "
                    f"ignorée{'s' if skipped > 1 else ''}"
                )
            if backfilled:
                message += (
                    f" · {backfilled} partie{'s' if backfilled > 1 else ''} "
                    f"complétée{'s' if backfilled > 1 else ''} pour les fins de round"
                )
            done = max(1, scanned)
            self._update(
                state="success",
                message=message,
                progress=done,
                total=done,
                new_matches=new_count,
                finished_at=_now_iso(),
                error=None,
            )
        except HenrikError as exc:
            self._update(
                state="error",
                message="Synchronisation impossible",
                finished_at=_now_iso(),
                error=exc.message,
            )
        except Exception as exc:  # noqa: BLE001 - surface a readable error in the UI
            self._update(
                state="error",
                message="Synchronisation impossible",
                finished_at=_now_iso(),
                error=f"Erreur inattendue : {exc}",
            )


def test_connection(cfg: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Validate credentials without touching the database."""
    try:
        client = HenrikClient(cfg.get("api_key", ""))
        account = client.account(cfg["riot_name"], cfg["riot_tag"])
        if not isinstance(account, dict) or not account.get("puuid"):
            return False, {"error": "Réponse inattendue de l'API pour ce compte."}
        profile = profile_from_account(account)
        try:
            mmr = client.mmr(cfg["region"], cfg["platform"], cfg["riot_name"], cfg["riot_tag"])
            if isinstance(mmr, dict):
                apply_mmr(profile, mmr)
        except HenrikError:
            pass
        return True, {"profile": profile}
    except HenrikError as exc:
        return False, {"error": exc.message}
    except Exception as exc:  # noqa: BLE001
        return False, {"error": f"Erreur inattendue : {exc}"}
