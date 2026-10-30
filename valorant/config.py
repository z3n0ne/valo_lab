"""Configuration loading and persistence for the Valorant dashboard."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VALO_DATA_DIR", ROOT / "data"))
CONFIG_PATH = DATA_DIR / "config.json"
DB_PATH = DATA_DIR / "valorant.db"

REGIONS = ["eu", "na", "ap", "kr", "latam", "br"]
PLATFORMS = ["pc", "console"]

DEFAULT_CONFIG: Dict[str, Any] = {
    "riot_name": "",
    "riot_tag": "",
    "region": "eu",
    "platform": "pc",
    "api_key": "",
    "backfill": 40,
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, Any]:
    ensure_data_dir()
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            stored = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}
        if isinstance(stored, dict):
            cfg.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})
    # Environment variable wins over the stored key, useful for CI or shared machines.
    env_key = os.environ.get("HENRIK_API_KEY", "").strip()
    if env_key:
        cfg["api_key"] = env_key
    return cfg


def save_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    for key in DEFAULT_CONFIG:
        if key in updates:
            cfg[key] = updates[key]
    cfg["riot_name"] = str(cfg.get("riot_name", "")).strip()
    cfg["riot_tag"] = str(cfg.get("riot_tag", "")).strip()
    cfg["region"] = str(cfg.get("region", "eu")).strip().lower()
    cfg["platform"] = str(cfg.get("platform", "pc")).strip().lower()
    if cfg["region"] not in REGIONS:
        cfg["region"] = "eu"
    if cfg["platform"] not in PLATFORMS:
        cfg["platform"] = "pc"
    try:
        cfg["backfill"] = max(10, min(100, int(cfg.get("backfill", 40))))
    except (TypeError, ValueError):
        cfg["backfill"] = 40
    cfg["api_key"] = str(cfg.get("api_key", "")).strip()

    ensure_data_dir()
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)
    os.chmod(CONFIG_PATH, 0o600)
    return cfg


def public_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Config safe to send to the browser (never includes the API key)."""
    return {
        "riot_name": cfg.get("riot_name", ""),
        "riot_tag": cfg.get("riot_tag", ""),
        "region": cfg.get("region", "eu"),
        "platform": cfg.get("platform", "pc"),
        "backfill": cfg.get("backfill", 40),
        "has_api_key": bool(cfg.get("api_key")),
    }


def is_configured(cfg: Dict[str, Any]) -> bool:
    return bool(cfg.get("riot_name") and cfg.get("riot_tag") and cfg.get("api_key"))
