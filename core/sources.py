"""Fetch candidate projects from GitHub and the Hugging Face Hub.

All text that comes back from these APIs is untrusted data. Nothing here
interprets it; it is only stored and later shown or embedded.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_TTL_S = 24 * 3600
TIMEOUT_S = 12
USER_AGENT = "already-built/1.0 (+https://github.com)"
README_CHARS = 1500

# Many campus and home networks advertise IPv6 but drop it, which makes every
# first connection hang ~10 s before falling back. IPv4-only avoids that.
# Set FORCE_IPV4=0 in .env on an IPv6-only network.
if os.getenv("FORCE_IPV4", "1") != "0":
    import urllib3.util.connection as _u3conn

    _u3conn.HAS_IPV6 = False

_session = requests.Session()
_session.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16))


class RateLimitError(Exception):
    """GitHub or Hugging Face refused the request because of rate limits."""

    def __init__(self, source: str, reset_at: int | None = None):
        self.source = source
        self.reset_at = reset_at
        wait = ""
        if reset_at:
            mins = max(1, int((reset_at - time.time()) / 60) + 1)
            wait = f" Try again in about {mins} min"
        super().__init__(f"{source} rate limit hit.{wait}")


class SourceError(Exception):
    """Network or API failure that is not a rate limit."""


@dataclass
class Candidate:
    id: str  # unique, e.g. "github:owner/repo" or "hf-space:owner/name"
    source: str  # github | hf-model | hf-space
    name: str
    url: str
    description: str = ""
    topics: list[str] = field(default_factory=list)
    readme: str = ""
    stars: int = 0
    updated_at: str = ""
    archived: bool = False
    fork: bool = False
    language: str = ""
    score: float = 0.0
    low_confidence: bool = False
    stale: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------- cache ----------

def _cache_path(key: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")


def cache_get(key: str, enabled: bool = True):
    if not enabled:
        return None
    p = _cache_path(key)
    try:
        if p.exists() and time.time() - p.stat().st_mtime < CACHE_TTL_S:
            return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return None


def cache_set(key: str, value, enabled: bool = True) -> None:
    if not enabled:
        return
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        _cache_path(key).write_text(json.dumps(value), encoding="utf-8")
    except OSError:
        pass  # a cache write failure must never break a search


def clear_cache() -> int:
    if not CACHE_DIR.exists():
        return 0
    n = 0
    for p in CACHE_DIR.glob("*.json"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


# ---------- http ----------

def _get(url: str, params: dict | None = None, headers: dict | None = None, source: str = "GitHub") -> requests.Response:
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    try:
        r = _session.get(url, params=params, headers=h, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        raise SourceError(f"{source} is unreachable ({type(e).__name__}).") from e
    if r.status_code == 429 or (r.status_code == 403 and r.headers.get("X-RateLimit-Remaining") == "0"):
        reset = r.headers.get("X-RateLimit-Reset")
        raise RateLimitError(source, int(reset) if reset and reset.isdigit() else None)
    return r


def _github_headers() -> dict:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ---------- GitHub ----------

def _repo_to_candidate(item: dict) -> Candidate:
    return Candidate(
        id=f"github:{item['full_name']}",
        source="github",
        name=item["full_name"],
        url=item["html_url"],
        description=(item.get("description") or "").strip(),
        topics=list(item.get("topics") or []),
        stars=int(item.get("stargazers_count") or 0),
        updated_at=item.get("pushed_at") or item.get("updated_at") or "",
        archived=bool(item.get("archived")),
        fork=bool(item.get("fork")),
        language=item.get("language") or "",
    )


def search_github(query: str, per_page: int = 30, use_cache: bool = True) -> list[Candidate]:
    key = f"gh:{query}:{per_page}"
    cached = cache_get(key, use_cache)
    if cached is not None:
        return [Candidate.from_dict(c) for c in cached]
    r = _get(
        "https://api.github.com/search/repositories",
        params={"q": f"{query} fork:false", "per_page": per_page, "sort": "best-match"},
        headers=_github_headers(),
    )
    if r.status_code == 422:
        return []  # GitHub rejects some queries (only operators, etc.)
    if r.status_code == 401:
        raise SourceError("GitHub rejected GITHUB_TOKEN (401). Fix or remove it in .env.")
    if r.status_code >= 400:
        raise SourceError(f"GitHub search failed (HTTP {r.status_code}).")
    items = [_repo_to_candidate(i) for i in r.json().get("items", [])]
    cache_set(key, [c.to_dict() for c in items], use_cache)
    return items


def get_github_repo(owner: str, repo: str, use_cache: bool = True) -> Candidate | None:
    key = f"ghrepo:{owner}/{repo}"
    cached = cache_get(key, use_cache)
    if cached is not None:
        return Candidate.from_dict(cached)
    r = _get(f"https://api.github.com/repos/{owner}/{repo}", headers=_github_headers())
    if r.status_code == 404:
        return None
    if r.status_code in (403, 429):
        return None
    if r.status_code >= 400:
        raise SourceError(f"GitHub repo lookup failed (HTTP {r.status_code}).")
    c = _repo_to_candidate(r.json())
    cache_set(key, c.to_dict(), use_cache)
    return c


_MD_NOISE = [
    (re.compile(r"<!--.*?-->", re.S), " "),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),  # images and badges
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # links -> text
    (re.compile(r"<[^>]+>"), " "),  # html tags
    (re.compile(r"```.*?```", re.S), " "),  # code blocks
    (re.compile(r"[#>*_`|=-]{2,}"), " "),
    (re.compile(r"\s+"), " "),
]


def clean_readme(text: str, limit: int = README_CHARS) -> str:
    t = html.unescape(text or "")
    for pat, rep in _MD_NOISE:
        t = pat.sub(rep, t)
    return t.strip()[:limit]


def fetch_readmes(names: list[str], use_cache: bool = True) -> dict[str, str]:
    """Fetch several READMEs in parallel. Missing ones map to ""."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        texts = list(pool.map(lambda n: fetch_readme(n, use_cache), names))
    return dict(zip(names, texts))


def fetch_readme(full_name: str, use_cache: bool = True) -> str:
    """README snippet via raw.githubusercontent. HEAD resolves to the default branch."""
    key = f"readme:{full_name}"
    cached = cache_get(key, use_cache)
    if cached is not None:
        return cached
    text = ""
    failed = False
    for fname in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        try:
            r = _session.get(
                f"https://raw.githubusercontent.com/{full_name}/HEAD/{fname}",
                headers={"User-Agent": USER_AGENT}, timeout=4,
            )
        except requests.RequestException:
            failed = True
            break  # network trouble: don't burn 4 s per file name
        if r.status_code == 200 and r.text.strip():
            text = clean_readme(r.text)
            break
    if not failed:
        cache_set(key, text, use_cache)  # never cache a network failure as "no README"
    return text


# ---------- Hugging Face ----------

def _hf_candidate(item: dict, kind: str) -> Candidate:
    rid = item.get("id") or item.get("modelId") or ""
    card = item.get("cardData") or {}
    desc = card.get("short_description") or card.get("title") or ""
    tags = [t for t in (item.get("tags") or []) if ":" not in t][:8]
    if kind == "hf-model" and item.get("pipeline_tag"):
        tags = [item["pipeline_tag"], *tags]
    base = "https://huggingface.co/spaces/" if kind == "hf-space" else "https://huggingface.co/"
    return Candidate(
        id=f"{kind}:{rid}",
        source=kind,
        name=rid,
        url=base + rid,
        description=str(desc).strip(),
        topics=tags,
        stars=int(item.get("likes") or 0),
        updated_at=item.get("lastModified") or "",
    )


def search_hf(query: str, kind: str = "hf-space", limit: int = 10, use_cache: bool = True) -> list[Candidate]:
    key = f"{kind}:{query}:{limit}"
    cached = cache_get(key, use_cache)
    if cached is not None:
        return [Candidate.from_dict(c) for c in cached]
    endpoint = "spaces" if kind == "hf-space" else "models"
    params = {"search": query, "limit": limit, "sort": "likes", "direction": -1, "full": "true"}
    headers = {}
    hf_token = os.getenv("HF_TOKEN", "").strip()
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"
    r = _get(f"https://huggingface.co/api/{endpoint}", params=params, headers=headers, source="Hugging Face")
    if r.status_code >= 400:
        raise SourceError(f"Hugging Face search failed (HTTP {r.status_code}).")
    items = [_hf_candidate(i, kind) for i in r.json()]
    cache_set(key, [c.to_dict() for c in items], use_cache)
    return items


# ---------- Hacker News (Show HN launches, via the free Algolia API) ----------

def search_hn(query: str, limit: int = 10, use_cache: bool = True) -> list[Candidate]:
    """Finds launched products that may not be on GitHub at all."""
    key = f"hn:{query}:{limit}"
    cached = cache_get(key, use_cache)
    if cached is not None:
        return [Candidate.from_dict(c) for c in cached]
    r = _get("https://hn.algolia.com/api/v1/search",
             params={"query": query, "tags": "show_hn", "hitsPerPage": limit}, source="Hacker News")
    if r.status_code >= 400:
        raise SourceError(f"Hacker News search failed (HTTP {r.status_code}).")
    items = []
    for h in r.json().get("hits", []):
        title = re.sub(r"^\s*Show HN:\s*", "", h.get("title") or "", flags=re.I).strip()
        if not title:
            continue
        hn_url = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        items.append(Candidate(
            id=f"hn:{h.get('objectID')}",
            source="hn",
            name=title[:120],
            url=h.get("url") or hn_url,
            description=clean_readme(h.get("story_text") or "", 400),
            stars=int(h.get("points") or 0),
            updated_at=h.get("created_at") or "",
        ))
    cache_set(key, [c.to_dict() for c in items], use_cache)
    return items


# ---------- URL input ----------

MAX_PAGE_BYTES = 1_000_000


def _public_host(url: str) -> bool:
    """True only for http(s) URLs whose host resolves to public addresses.

    Blocks loopback, private, link-local (cloud metadata) and reserved ranges,
    so a pasted link can never make the server read its own network.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except (OSError, ValueError, UnicodeError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return bool(infos)


def fetch_url_text(url: str, use_cache: bool = True) -> str:
    """Turn a pasted non-GitHub URL into plain text. Returns "" if it fails or the host is not public."""
    key = f"url:{url}"
    cached = cache_get(key, use_cache)
    if cached is not None:
        return cached
    # Follow redirects by hand so every hop is checked against private addresses.
    try:
        for _ in range(4):
            if not _public_host(url):
                return ""
            r = _session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S, allow_redirects=False, stream=True)
            if r.is_redirect and r.headers.get("Location"):
                from urllib.parse import urljoin

                url = urljoin(url, r.headers["Location"])
                r.close()
                continue
            break
        else:
            return ""
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "text/html"):
            r.close()
            return ""
        raw = b""
        for chunk in r.iter_content(65536):
            raw += chunk
            if len(raw) >= MAX_PAGE_BYTES:
                break
        r.close()
        body = raw.decode(r.encoding or "utf-8", errors="replace")
    except requests.RequestException:
        return ""
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    title = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.S | re.I)
    meta = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', body, flags=re.I)
    text = " ".join(filter(None, [title.group(1) if title else "", meta.group(1) if meta else "", clean_readme(body, 1200)]))
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()[:1500]
    cache_set(key, text, use_cache)
    return text
