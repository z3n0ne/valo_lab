#!/usr/bin/env python3
"""Launch the local VALORANT dashboard.

    python3 app.py

The server listens on 127.0.0.1 by default; use ``--host 0.0.0.0`` to expose it
on the local network (Docker does this automatically). Data stays in ./data.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Allow running from anywhere: python3 /path/to/app.py
sys.path.insert(0, str(Path(__file__).resolve().parent))

from valorant.config import DB_PATH, is_configured, load_config  # noqa: E402
from valorant.db import Database  # noqa: E402
from valorant.demo import seed_demo  # noqa: E402
from valorant.sync import SyncManager  # noqa: E402
from valorant.version import VERSION  # noqa: E402
from valorant.web import App, make_server  # noqa: E402

BANNER = r"""
 _   _  ___   _     _____    _____       ___  ______ 
| | | |/ _ \ | |   |  _  |  / / / |     / _ \ | ___ \
| | | / /_\ \| |   | | | | / / /| |    / /_\ \| |_/ /
| | | |  _  || |   | | | |/ / / | |    |  _  || ___ \
\ \_/ / | | || |___\ \_/ / / /  | |____| | | || |_/ /
 \___/\_| |_/\_____/\___/_/_/   \_____/\_| |_/\____/ 
                                                     
"""


def watch_for_daily_sync(sync: SyncManager, interval: float = 1800.0) -> None:
    """Keep the data fresh when the dashboard stays open for days."""
    while True:
        time.sleep(interval)
        try:
            sync.auto_sync_if_needed()
        except Exception:  # noqa: BLE001 - the watcher must never kill the server
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Dashboard local de performances VALORANT")
    parser.add_argument("--host", default="127.0.0.1", help="Adresse d'écoute (127.0.0.1 par défaut)")
    parser.add_argument("--port", type=int, default=8765, help="Port HTTP (8765 par défaut)")
    parser.add_argument("--no-browser", action="store_true", help="Ne pas ouvrir le navigateur")
    parser.add_argument("--no-sync", action="store_true", help="Ne pas synchroniser au démarrage")
    args = parser.parse_args()

    db = Database(DB_PATH)
    cfg = load_config()
    if db.count_matches() == 0 and not is_configured(cfg) and not db.get_meta("demo_dismissed"):
        inserted = seed_demo(db)
        if inserted:
            print(f"· Données de démonstration chargées ({inserted} parties).")

    sync = SyncManager(db)
    app = App(db=db, sync=sync)

    server = None
    last_error = None
    for port in range(args.port, args.port + 20):
        try:
            server = make_server(args.host, port, app)
            break
        except OSError as exc:
            last_error = exc
            continue
    if server is None:
        print(f"Impossible de démarrer le serveur : {last_error}")
        return 1

    url = f"http://{args.host}:{server.server_port}"
    print(BANNER)
    print(f"  VALO//LAB v{VERSION}  ·  {url}")
    print("  Données locales : ./data  ·  Ctrl+C pour arrêter\n")

    if not args.no_sync:
        started = sync.auto_sync_if_needed()
        if started:
            print("· Synchronisation automatique lancée (dernière sync > 24 h).\n")
        threading.Thread(target=watch_for_daily_sync, args=(sync,), daemon=True).start()

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n· Arrêt du dashboard.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
