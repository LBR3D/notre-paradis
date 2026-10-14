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
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

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


class RobotRules:
    """robots.txt avec jokers (`*`, `$`) et règle de la correspondance la plus longue (RFC 9309).

    `urllib.robotparser` ignore les jokers, ce qui autoriserait à tort des adresses interdites.
    """

    def __init__(self, text: str | None = None, allow_all: bool = False, disallow_all: bool = False):
        self.allow_all = allow_all
        self.disallow_all = disallow_all
        self.delay: float | None = None
        self.rules: list[tuple[bool, re.Pattern, int]] = []
        if text is not None:
            self._parse(text)

    @staticmethod
    def _compile(path: str) -> re.Pattern:
        end = path.endswith("$")
        body = re.escape(path.rstrip("$")).replace(r"\*", ".*")
        return re.compile("^" + body + ("$" if end else ""))

    def _parse(self, text: str) -> None:
        groups: list[tuple[list[str], list[tuple[str, str]]]] = []
        agents: list[str] = []
        lines: list[tuple[str, str]] = []
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if not last_was_agent:
                    if agents:
                        groups.append((agents, lines))
                    agents, lines = [], []
                agents.append(v.lower())
                last_was_agent = True
            else:
                last_was_agent = False
                if k in ("allow", "disallow", "crawl-delay"):
                    lines.append((k, v))
        if agents:
            groups.append((agents, lines))
        mine = [g for g in groups if any(a != "*" and a in env.user_agent.lower() for a in g[0])]
        chosen = mine or [g for g in groups if "*" in g[0]]
        for _, ls in chosen:
            for k, v in ls:
                if k == "crawl-delay":
                    try:
                        self.delay = float(v)
                    except ValueError:
                        pass
                elif v:  # « Disallow: » vide = tout autorisé
                    self.rules.append((k == "allow", self._compile(v), len(v)))

    def can_fetch(self, _agent: str, url: str) -> bool:
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        p = urlsplit(url)
        target = (p.path or "/") + (f"?{p.query}" if p.query else "")
        best: tuple[int, bool] | None = None
        for allow, rx, n in self.rules:
            if rx.match(target) and (best is None or n > best[0] or (n == best[0] and allow)):
                best = (n, allow)
        return True if best is None else best[1]

    def crawl_delay(self, _agent: str) -> float | None:
        return self.delay


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
        self._robots: dict[str, tuple[RobotRules, float]] = {}
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

    def robots_for(self, url: str, lenient: bool = False) -> RobotRules:
        """`lenient` (photos hébergées sur un CDN) : un robots.txt illisible (401/403/5xx) n'interdit rien ;
        un robots.txt lisible qui interdit est toujours respecté."""
        host = self._host(url) + ("#lenient" if lenient else "")
        cached = self._robots.get(host)
        if cached and time.time() - cached[1] < self.ROBOTS_TTL:
            return cached[0]
        try:
            r = self._client.get(f"{self._host(url)}/robots.txt")
            if r.status_code in (401, 403) or r.status_code >= 500:
                rp = RobotRules(allow_all=lenient, disallow_all=not lenient)  # prudence : accès refusé ou site en erreur => on s'abstient
            elif r.status_code >= 400:
                rp = RobotRules(allow_all=True)  # pas de robots.txt => tout est autorisé
            else:
                rp = RobotRules(r.text)
        except httpx.HTTPError:
            rp = RobotRules(allow_all=lenient, disallow_all=not lenient)
        self._robots[host] = (rp, time.time())
        return rp

    def allowed(self, url: str, lenient: bool = False) -> bool:
        return self.robots_for(url, lenient).can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str, lenient: bool = False) -> float:
        rp = self.robots_for(url, lenient)
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
    def _throttle(self, url: str, lenient: bool = False) -> None:
        host = self._host(url)
        delay = self.crawl_delay(url, lenient)
        wait = self._last.get(host, 0) + delay - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()

    def _request(self, url: str, max_retries: int = 3, lenient: bool = False) -> httpx.Response:
        if not self.allowed(url, lenient):
            self.stats["robots_blocked"] += 1
            raise RobotsDisallowed(url)
        host = self._host(url)
        with self._lock(host):
            for attempt in range(max_retries + 1):
                self._throttle(url, lenient)
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

    def get_bytes(self, url: str, lenient: bool = False) -> bytes | None:
        """Fichiers binaires (sitemaps compressés, photos). `lenient=True` pour les photos d'un CDN."""
        r = self._request(url, lenient=lenient)
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
