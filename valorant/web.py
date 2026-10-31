"""HTTP server and JSON API for the local dashboard."""
from __future__ import annotations

import json
import mimetypes
import os
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .analytics import compute
from .config import (
    DB_PATH,
    PLATFORMS,
    REGIONS,
    is_configured,
    load_config,
    public_config,
    save_config,
)
from .db import Database
from .demo import seed_demo
from .sync import SyncManager, test_connection
from .version import VERSION

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class App:
    def __init__(self, db: Database, sync: SyncManager):
        self.db = db
        self.sync = sync


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ValoLab/1.0"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ helpers
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # Quiet by default; VALO_LOG=1 prints requests while debugging.
        if os.environ.get("VALO_LOG"):
            print("[http]", fmt % args, flush=True)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = 400) -> None:
        self._send_json({"error": message}, status)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_error_json("Fichier introuvable", 404)
            return
        try:
            resolved = path.resolve()
            resolved.relative_to(STATIC_DIR.resolve())
        except (ValueError, OSError):
            self._send_error_json("Chemin invalide", 403)
            return
        content = resolved.read_bytes()
        content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > 1_000_000:
            raise ValueError("Corps de requête trop volumineux")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("JSON invalide") from exc
        if not isinstance(payload, dict):
            raise ValueError("Le corps doit être un objet JSON")
        return payload

    def _bootstrap(self) -> Dict[str, Any]:
        db = self.app.db
        cfg = load_config()
        real = db.count_matches(demo=False)
        demo = db.has_demo()
        return {
            "configured": is_configured(cfg),
            "config": public_config(cfg),
            "profile": db.get_meta("profile") or {},
            "sync": self.app.sync.snapshot(),
            "demo": demo,
            "demo_dismissed": bool(db.get_meta("demo_dismissed")),
            "counts": {
                "matches": db.count_matches(),
                "real": real,
                "demo": db.count_matches(demo=True),
                "last_match": db.latest_match_at(),
            },
            "filters": db.filter_options(),
            "regions": REGIONS,
            "platforms": PLATFORMS,
            "version": VERSION,
            "server_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    # -------------------------------------------------------------------- verbs
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self._send_file(STATIC_DIR / "index.html")
                return
            if parsed.path.startswith("/static/"):
                self._send_file(STATIC_DIR / parsed.path[len("/static/") :])
                return
            if parsed.path == "/api/health":
                self._send_json({"ok": True, "version": VERSION})
                return
            if parsed.path == "/api/bootstrap":
                self._send_json(self._bootstrap())
                return
            if parsed.path == "/api/stats":
                query = parse_qs(parsed.query)
                mode = (query.get("mode") or ["tactical"])[0]
                try:
                    days = int((query.get("days") or ["90"])[0])
                except ValueError:
                    days = 90
                days = max(0, min(3650, days))
                data = compute(self.app.db, mode=mode, days=days)
                data["filters"] = self.app.db.filter_options()
                data["profile"] = self.app.db.get_meta("profile") or {}
                self._send_json(data)
                return
            if parsed.path == "/api/sync/status":
                self._send_json(self.app.sync.snapshot())
                return
            self._send_error_json("Route inconnue", 404)
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send_error_json(f"Erreur serveur : {exc}", 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/sync":
                body = self._read_json()
                cfg = load_config()
                if not is_configured(cfg):
                    self._send_json(
                        {
                            "error": "Renseigne ton Riot ID et ta clé API HenrikDev dans les réglages.",
                            "sync": self.app.sync.snapshot(),
                        },
                        400,
                    )
                    return
                started = self.app.sync.start(full=bool(body.get("full")))
                self._send_json({"started": started, "sync": self.app.sync.snapshot()}, 202 if started else 409)
                return

            if parsed.path == "/api/settings":
                body = self._read_json()
                old = load_config()
                updates: Dict[str, Any] = {}
                for key in ("riot_name", "riot_tag", "region", "platform", "backfill", "queue_mode"):
                    if key in body:
                        updates[key] = body[key]
                if "api_key" in body and str(body.get("api_key") or "").strip():
                    updates["api_key"] = str(body["api_key"]).strip()
                if body.get("clear_api_key"):
                    updates["api_key"] = ""

                identity_changed = any(
                    str(updates.get(key, old.get(key)) or "").strip().lower()
                    != str(old.get(key) or "").strip().lower()
                    for key in ("riot_name", "riot_tag", "region")
                )
                cfg = save_config(updates)
                queue_mode_changed = cfg.get("queue_mode") != old.get("queue_mode")
                purged = 0
                if queue_mode_changed and cfg.get("queue_mode") == "competitive":
                    purged = self.app.db.delete_non_competitive()
                if identity_changed and self.app.db.count_matches(demo=False) > 0:
                    self.app.db.delete_real()
                    self.app.db.delete_meta("last_sync")
                    self.app.db.delete_meta("profile")
                self._send_json(
                    {
                        "ok": True,
                        "identity_changed": identity_changed,
                        "queue_mode_changed": queue_mode_changed,
                        "purged": purged,
                        "configured": is_configured(cfg),
                        "config": public_config(cfg),
                        "bootstrap": self._bootstrap(),
                    }
                )
                return

            if parsed.path == "/api/test":
                body = self._read_json()
                cfg = load_config()
                for key in ("riot_name", "riot_tag", "region", "platform"):
                    if str(body.get(key) or "").strip():
                        cfg[key] = str(body[key]).strip()
                if str(body.get("api_key") or "").strip():
                    cfg["api_key"] = str(body["api_key"]).strip()
                if not cfg.get("riot_name") or not cfg.get("riot_tag"):
                    self._send_error_json("Renseigne un Riot ID complet (Pseudo#TAG).", 400)
                    return
                ok, result = test_connection(cfg)
                self._send_json({"ok": ok, **result}, 200 if ok else 400)
                return

            if parsed.path == "/api/demo/clear":
                removed = self.app.db.delete_demo()
                self.app.db.set_meta("demo_dismissed", True)
                profile = self.app.db.get_meta("profile") or {}
                if profile.get("demo"):
                    self.app.db.delete_meta("profile")
                self._send_json({"ok": True, "removed": removed, "bootstrap": self._bootstrap()})
                return

            if parsed.path == "/api/demo/seed":
                self.app.db.set_meta("demo_dismissed", False)
                added = seed_demo(self.app.db)
                self._send_json({"ok": True, "added": added, "bootstrap": self._bootstrap()})
                return

            self._send_error_json("Route inconnue", 404)
        except ValueError as exc:
            self._send_error_json(str(exc), 400)
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._send_error_json(f"Erreur serveur : {exc}", 500)


def make_server(host: str, port: int, app: App) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.daemon_threads = True
    server.app = app  # type: ignore[attr-defined]
    return server


def default_app() -> App:
    db = Database(DB_PATH)
    return App(db=db, sync=SyncManager(db))
