"""Polite, resumable, content-addressed HTTP client.

The harvest touches dozens of public APIs, many of them small academic servers.
Three properties matter more than speed:

1. *Never fetch the same thing twice.* Responses land in a content-addressed
   cache keyed by the request, so re-running a harvest after a crash costs
   nothing and the raw bytes stay available for re-parsing.
2. *Never hammer a host.* A per-host token bucket enforces a minimum interval
   between requests regardless of how the callers are interleaved.
3. *Survive flaky servers.* Retries use exponential backoff with jitter and
   honour ``Retry-After``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .paths import cache_dir

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass
class RateLimit:
    """Minimum seconds between requests to one host."""

    min_interval_s: float = 0.2
    _last: float = field(default=0.0, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval_s - now
            if delay > 0:
                time.sleep(delay)
                now = time.monotonic()
            self._last = now


# Published/observed politeness requirements per host. Anything not listed gets
# DEFAULT_INTERVAL. Values are deliberately conservative: a harvest that gets
# the client IP banned costs far more than it saves.
HOST_INTERVALS: dict[str, float] = {
    "api.openalex.org": 0.12,        # 10 req/s polite pool; stay under
    "api.crossref.org": 0.05,        # 50 req/s polite pool
    "api.semanticscholar.org": 1.05,  # 1 req/s unauthenticated
    "www.ebi.ac.uk": 0.15,           # Europe PMC
    "eutils.ncbi.nlm.nih.gov": 0.35,  # 3 req/s without an API key
    "api.unpaywall.org": 0.12,
    "api.core.ac.uk": 6.0,           # very tight quota on the free tier
    "zenodo.org": 1.0,
    "api.datacite.org": 0.25,
    "power.larc.nasa.gov": 1.0,      # NASA POWER throttles aggressively
    "rest.isric.org": 1.0,           # SoilGrids: ~5 req/min is the safe zone
    "daymet.ornl.gov": 0.5,
    "sdmdataaccess.sc.egov.usda.gov": 1.0,
    "wcc.sc.egov.usda.gov": 1.0,
    "www.ncei.noaa.gov": 0.5,
    "ismn.earth": 2.0,
}
DEFAULT_INTERVAL = 0.5

_LIMITERS: dict[str, RateLimit] = {}
_LIMITERS_LOCK = threading.Lock()


def limiter_for(url: str) -> RateLimit:
    host = urlparse(url).netloc.lower()
    with _LIMITERS_LOCK:
        if host not in _LIMITERS:
            _LIMITERS[host] = RateLimit(HOST_INTERVALS.get(host, DEFAULT_INTERVAL))
        return _LIMITERS[host]


def cache_key(method: str, url: str, params: dict | None, body: Any = None) -> str:
    payload = json.dumps(
        {"m": method.upper(), "u": url, "p": params or {}, "b": body},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _cache_paths(key: str) -> tuple[Path, Path]:
    # Two-level fan-out keeps directory listings usable at millions of entries.
    d = cache_dir() / key[:2] / key[2:4]
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.body", d / f"{key}.meta.json"


class PoliteSession:
    """A requests session with caching, rate limiting and retry.

    Parameters
    ----------
    mailto:
        Contact address sent in ``User-Agent`` and, where supported, as a
        ``mailto`` query parameter. OpenAlex and Crossref route requests that
        carry one into a faster, more reliable "polite pool".
    use_cache:
        When ``True`` (default) a successful response is written to the raw
        cache and served from it on subsequent identical requests.
    offline:
        Serve only from cache; raise on a miss. Useful for reproducing a run
        or for working without a network.
    """

    def __init__(
        self,
        mailto: str | None = None,
        user_agent: str = "smml/0.1 (soil-moisture research harvester)",
        use_cache: bool = True,
        offline: bool = False,
        max_retries: int = 5,
        timeout_s: float = 60.0,
    ) -> None:
        self.mailto = mailto
        self.use_cache = use_cache
        self.offline = offline
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.session = requests.Session()
        ua = f"{user_agent}" + (f" mailto:{mailto}" if mailto else "")
        self.session.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self.stats = {"hits": 0, "misses": 0, "retries": 0, "errors": 0}

    # -- core ------------------------------------------------------------

    def request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        json_body: Any = None,
        headers: dict | None = None,
        cache: bool | None = None,
    ) -> bytes:
        """Return the response body, from cache when available."""
        use_cache = self.use_cache if cache is None else cache
        key = cache_key(method, url, params, json_body)
        body_path, meta_path = _cache_paths(key)

        if use_cache and body_path.exists():
            self.stats["hits"] += 1
            return body_path.read_bytes()

        if self.offline:
            raise FileNotFoundError(f"offline mode: {method} {url} not in cache ({key})")

        self.stats["misses"] += 1
        content = self._fetch_with_retry(method, url, params, json_body, headers)

        if use_cache:
            body_path.write_bytes(content)
            meta_path.write_text(
                json.dumps(
                    {"method": method.upper(), "url": url, "params": params, "bytes": len(content)},
                    sort_keys=True,
                )
            )
        return content

    def _fetch_with_retry(self, method, url, params, json_body, headers) -> bytes:
        limiter = limiter_for(url)
        last_exc: Exception | None = None

        for attempt in range(self.max_retries):
            limiter.wait()
            try:
                resp = self.session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout_s,
                )
            except requests.RequestException as exc:
                last_exc = exc
                self.stats["retries"] += 1
                self._backoff(attempt, reason=type(exc).__name__, url=url)
                continue

            if resp.status_code in RETRYABLE_STATUS:
                last_exc = requests.HTTPError(f"{resp.status_code} for {url}")
                self.stats["retries"] += 1
                self._backoff(attempt, reason=str(resp.status_code), url=url,
                              retry_after=resp.headers.get("Retry-After"))
                continue

            if not resp.ok:
                # 4xx other than the retryable ones: a bad request, a missing
                # record, or a policy denial. Retrying will not help.
                self.stats["errors"] += 1
                raise requests.HTTPError(
                    f"{resp.status_code} {resp.reason} for {url} :: {resp.text[:300]}"
                )

            return resp.content

        self.stats["errors"] += 1
        raise RuntimeError(f"exhausted {self.max_retries} attempts for {url}") from last_exc

    def _backoff(self, attempt: int, reason: str, url: str, retry_after: str | None = None) -> None:
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 2.0 ** attempt
        else:
            delay = 2.0 ** attempt
        delay = min(delay, 60.0) * (0.8 + 0.4 * random.random())  # jitter
        log.debug("retry %d for %s (%s) in %.1fs", attempt + 1, url, reason, delay)
        time.sleep(delay)

    # -- conveniences ----------------------------------------------------

    def get(self, url: str, params: dict | None = None, **kw) -> bytes:
        return self.request("GET", url, params=params, **kw)

    def get_json(self, url: str, params: dict | None = None, **kw) -> Any:
        return json.loads(self.request("GET", url, params=params, **kw))

    def get_text(self, url: str, params: dict | None = None, encoding: str = "utf-8", **kw) -> str:
        return self.request("GET", url, params=params, **kw).decode(encoding, errors="replace")

    def download(self, url: str, dest: Path, params: dict | None = None, **kw) -> Path:
        """Fetch to a file, writing atomically so a crash cannot leave a stub."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(self.request("GET", url, params=params, **kw))
        tmp.replace(dest)
        return dest
