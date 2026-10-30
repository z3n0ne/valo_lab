"""Small standard-library client for the HenrikDev VALORANT API (v4)."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

DEFAULT_BASE = "https://api.henrikdev.xyz"
USER_AGENT = "valo-lab/1.0 (local personal dashboard)"


class HenrikError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class HenrikClient:
    def __init__(self, api_key: str, min_interval: float = 2.15, base_url: Optional[str] = None):
        self.api_key = (api_key or "").strip()
        self.min_interval = max(0.0, min_interval)
        self.base_url = (base_url or os.environ.get("HENRIK_BASE_URL") or DEFAULT_BASE).rstrip("/")
        self._last_request = 0.0

    # --------------------------------------------------------------- internals
    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request = time.monotonic()

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.api_key:
            raise HenrikError("Clé API manquante. Ajoute une clé HenrikDev dans les réglages.", 401)
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urlencode(clean)
        headers = {
            "Authorization": self.api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

        last_error: Optional[HenrikError] = None
        for attempt in range(4):
            self._wait()
            request = Request(url, headers=headers)
            try:
                with urlopen(request, timeout=30) as response:
                    body = response.read()
                payload = json.loads(body.decode("utf-8"))
                status = payload.get("status", response.status)
                if isinstance(status, int) and status >= 400:
                    raise HenrikError(_payload_error(payload), status)
                return payload.get("data")
            except HTTPError as exc:
                raw = exc.read()
                payload: Dict[str, Any] = {}
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
                status = exc.code
                message = _payload_error(payload) or f"Erreur HTTP {status}"
                if status == 429:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = _safe_float(retry_after, 8.0 + attempt * 6.0)
                    last_error = HenrikError(
                        "Limite de requêtes atteinte (30/min avec une clé Basic). Nouvelle tentative dans quelques secondes.",
                        429,
                    )
                    if attempt < 3:
                        time.sleep(max(4.0, delay))
                        continue
                if status == 401:
                    raise HenrikError(
                        "Clé API refusée. Vérifie ta clé HenrikDev (Basic Key, gratuite) dans les réglages.",
                        401,
                    )
                if status == 404:
                    raise HenrikError(
                        "Compte ou partie introuvable. Vérifie le Riot ID (Pseudo#TAG) et la région.",
                        404,
                    )
                if status >= 500 and attempt < 2:
                    last_error = HenrikError("L'API HenrikDev est momentanément indisponible.", status)
                    time.sleep(3.0 + attempt * 2.0)
                    continue
                raise HenrikError(message, status)
            except URLError as exc:
                if attempt < 2:
                    last_error = HenrikError(f"Connexion impossible à l'API ({exc.reason}).", None)
                    time.sleep(2.0 + attempt * 2.0)
                    continue
                raise HenrikError("Impossible de joindre l'API HenrikDev. Vérifie ta connexion internet.", None)
            except json.JSONDecodeError:
                raise HenrikError("Réponse illisible de l'API HenrikDev.", None)

        raise last_error or HenrikError("Échec de la requête à l'API HenrikDev.", None)

    # ----------------------------------------------------------------- endpoints
    def account(self, name: str, tag: str) -> Dict[str, Any]:
        return self._request(f"/valorant/v2/account/{quote(name, safe='')}/{quote(tag, safe='')}")

    def mmr(self, region: str, platform: str, name: str, tag: str) -> Dict[str, Any]:
        return self._request(
            f"/valorant/v3/mmr/{quote(region, safe='')}/{quote(platform, safe='')}/"
            f"{quote(name, safe='')}/{quote(tag, safe='')}"
        )

    def matches(
        self,
        region: str,
        platform: str,
        name: str,
        tag: str,
        start: int = 0,
        size: int = 10,
        mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        data = self._request(
            f"/valorant/v4/matches/{quote(region, safe='')}/{quote(platform, safe='')}/"
            f"{quote(name, safe='')}/{quote(tag, safe='')}",
            {"start": max(0, int(start)), "size": max(1, min(10, int(size))), "mode": mode},
        )
        return data if isinstance(data, list) else []

    def match(self, region: str, match_id: str) -> Dict[str, Any]:
        return self._request(f"/valorant/v4/match/{quote(region, safe='')}/{quote(match_id, safe='')}")


def _payload_error(payload: Dict[str, Any]) -> str:
    errors = payload.get("errors") or []
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            details = first.get("details")
            message = first.get("message") or ""
            if details and isinstance(details, dict):
                escaped = details.get("message") if isinstance(details.get("message"), str) else None
                if escaped:
                    return f"{message} ({escaped})" if message else escaped
            return message or "Erreur API"
    if isinstance(payload.get("message"), str):
        return payload["message"]
    return ""


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
