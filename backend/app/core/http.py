"""Client HTTP « poli » utilisé par tous les connecteurs.

- respecte robots.txt (relu toutes les 24 h, par site) ;
- débit faible : délai minimum entre deux requêtes vers un même site ;
- cache disque des pages (évite de retélécharger une page vue récemment) ;
- user-agent identifiable ;
- réessais espacés sur 429 / 5xx, en respectant Retry-After.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import env


class RobotsDisallowed(Exception):
    """La page est interdite aux robots par le robots.txt du site."""


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    headers: dict
    from_cache: bool = False


class PoliteClient:
    ROBOTS_TTL = 24 * 3600

    def __init__(
        self,
        min_delay: float = 4.0,
        cache_ttl_hours: float = 6,
        cache_dir: Path | None = None,
        user_agent: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        self.min_delay = min_delay
        self.cache_ttl = cache_ttl_hours * 3600
        self.cache_dir = cache_dir or (env.cache_dir / "http")
        self.user_agent = user_agent or env.user_agent
        self._client = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Language": "fr-FR,fr;q=0.9"},
            follow_redirects=True,
            timeout=timeout,
            transport=transport,
        )
        self._robots: dict[str, tuple[RobotFileParser, float]] = {}
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._global = threading.Lock()
        self.stats = {"requests": 0, "cache_hits": 0, "robots_blocked": 0}

    # ------------------------------------------------------------------ robots
    def _host(self, url: str) -> str:
        p = urlsplit(url)
        return f"{p.scheme}://{p.netloc}"

    def _lock(self, host: str) -> threading.Lock:
        with self._global:
            return self._locks.setdefault(host, threading.Lock())

    def robots_for(self, url: str) -> RobotFileParser:
        host = self._host(url)
        cached = self._robots.get(host)
        if cached and time.time() - cached[1] < self.ROBOTS_TTL:
            return cached[0]
        rp = RobotFileParser()
        rp.set_url(f"{host}/robots.txt")
        try:
            r = self._client.get(f"{host}/robots.txt")
            if r.status_code in (401, 403):
                rp.disallow_all = True
            elif r.status_code >= 500:
                rp.disallow_all = True  # prudence : site en erreur => on s'abstient
            elif r.status_code >= 400:
                rp.allow_all = True  # pas de robots.txt => tout est autorisé
            else:
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            rp.disallow_all = True
        self._robots[host] = (rp, time.time())
        return rp

    def allowed(self, url: str) -> bool:
        return self.robots_for(url).can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float:
        rp = self.robots_for(url)
        d = rp.crawl_delay(self.user_agent)
        return max(self.min_delay, float(d) if d else 0.0)

    # ------------------------------------------------------------------- cache
    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / h[:2] / f"{h}.json"

    def _cache_get(self, url: str) -> FetchResult | None:
        if self.cache_ttl <= 0:
            return None
        p = self._cache_path(url)
        if not p.exists() or time.time() - p.stat().st_mtime > self.cache_ttl:
            return None
        d = json.loads(p.read_text())
        return FetchResult(d["url"], d["status"], d["text"], d["headers"], from_cache=True)

    def _cache_put(self, res: FetchResult) -> None:
        p = self._cache_path(res.url)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"url": res.url, "status": res.status, "text": res.text, "headers": res.headers}))

    # -------------------------------------------------------------- requêtes
    def _throttle(self, url: str) -> None:
        host = self._host(url)
        delay = self.crawl_delay(url)
        wait = self._last.get(host, 0) + delay - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()

    def _request(self, url: str, max_retries: int = 3) -> httpx.Response:
        if not self.allowed(url):
            self.stats["robots_blocked"] += 1
            raise RobotsDisallowed(url)
        host = self._host(url)
        with self._lock(host):
            for attempt in range(max_retries + 1):
                self._throttle(url)
                self.stats["requests"] += 1
                r = self._client.get(url)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    retry_after = r.headers.get("Retry-After")
                    pause = float(retry_after) if retry_after and retry_after.isdigit() else 30 * (attempt + 1)
                    time.sleep(min(pause, 300))
                    continue
                return r
        return r  # pragma: no cover

    def get(self, url: str, use_cache: bool = True) -> FetchResult:
        if use_cache:
            cached = self._cache_get(url)
            if cached:
                self.stats["cache_hits"] += 1
                return cached
        r = self._request(url)
        res = FetchResult(str(r.url), r.status_code, r.text, dict(r.headers))
        if r.status_code == 200 and use_cache:
            self._cache_put(res)
        return res

    def get_bytes(self, url: str) -> bytes | None:
        """Pour les photos (pas de cache texte ; stockées ailleurs)."""
        r = self._request(url)
        return r.content if r.status_code == 200 else None

    def close(self) -> None:
        self._client.close()


def download_file(url: str, dest: Path, retries: int = 5, timeout: float = 600) -> httpx.Headers:
    """Télécharge un gros fichier de données publiques (avec réessais). Renvoie les en-têtes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": env.user_agent}) as c:
                with c.stream("GET", url) as r:
                    r.raise_for_status()
                    with tmp.open("wb") as fh:
                        for chunk in r.iter_bytes(1 << 20):
                            fh.write(chunk)
                    tmp.replace(dest)
                    return r.headers
        except (httpx.HTTPError, OSError) as e:
            last_exc = e
            time.sleep(min(5 * 2**attempt, 120))
    raise RuntimeError(f"Téléchargement impossible après {retries} essais : {url} ({last_exc})")
