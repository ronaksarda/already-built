"""Similarity ranking with a local Hugging Face sentence-transformers model.

This module decides what counts as "similar". Gemma never ranks; it only
explains the list this module produces.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
import threading

import numpy as np

from .sources import Candidate

EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
SCORE_THRESHOLD = 0.35  # below this a result is a keyword accident, not a rival
STALE_DAYS = 365
TOP_K = 10
DUMMY_REPO_RE = re.compile(
    r"^(?:github[-_]?)?(?:(?:repo|repository|project)[-_])?(?:my[-_]?)?(?:first|test|sample|dummy|practice|learn(?:ing)?|trial|training|starter|template|sandbox)[-_]?(?:repo|repository|project)?(?:[-_]?(?:training|practice|learn(?:ing)?))?$",
    re.IGNORECASE,
)


_model = None
_model_lock = threading.Lock()


def get_model():
    """Load once, thread-safe. Uses the local cache first so startup never waits on the Hub."""
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            try:
                _model = SentenceTransformer(EMBED_MODEL, local_files_only=True)
            except Exception:
                _model = SentenceTransformer(EMBED_MODEL)  # first run: download
        return _model


def warm_up() -> None:
    get_model().encode(["warm up"], normalize_embeddings=True)


def _split_name(name: str) -> str:
    base = name.split("/")[-1]
    base = re.sub(r"([a-z])([A-Z])", r"\1 \2", base)
    return re.sub(r"[-_.]+", " ", base)


def candidate_text(c: Candidate) -> str:
    parts = [_split_name(c.name), c.description, " ".join(c.topics), c.readme[:600]]
    return ". ".join(p for p in parts if p).strip()


def embed(texts: list[str]) -> np.ndarray:
    return np.asarray(get_model().encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False))


def dedupe(cands: list[Candidate]) -> list[Candidate]:
    """Drop forks, repeated ids, and mirrors (same repo name + same description)."""
    seen_ids: set[str] = set()
    seen_sig: dict[str, Candidate] = {}
    out: list[Candidate] = []
    for c in sorted(cands, key=lambda x: -x.stars):  # keep the most-starred copy of a mirror
        if c.fork or c.id in seen_ids or c.name.lower().endswith("/.github"):
            continue  # forks, repeats, and org profile repos are not rival projects
        base_name = c.name.split("/")[-1]
        if c.source == "github" and c.stars < 5 and DUMMY_REPO_RE.match(base_name):
            continue  # ignore beginner "my-first-repo" / "test-repo" scratchpads
        seen_ids.add(c.id)
        # Show HN reposts share a title but not always a text, so HN dedupes on title alone.
        sig = _split_name(c.name).lower().strip() + "|" + ("" if c.source == "hn" else c.description.lower().strip()[:80])
        if (c.description or c.source == "hn") and sig in seen_sig:
            continue
        seen_sig[sig] = c
        out.append(c)
    return out


def days_since(iso: str) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def annotate(c: Candidate) -> Candidate:
    c.low_confidence = not c.description and not c.readme
    age = days_since(c.updated_at)
    # A Show HN post date is a launch date, not activity, so HN items are never "stale".
    c.stale = c.archived or (c.source != "hn" and age is not None and age > STALE_DAYS)
    return c


def score(idea_text: str, cands: list[Candidate]) -> tuple[np.ndarray, np.ndarray]:
    """Return (idea_vector, candidate_matrix) and write cosine scores onto candidates."""
    vecs = embed([idea_text] + [candidate_text(c) for c in cands])
    idea_vec, mat = vecs[0], vecs[1:]
    sims = mat @ idea_vec if len(cands) else np.array([])
    for c, s in zip(cands, sims):
        c.score = float(s)
    return idea_vec, mat


def select(cands: list[Candidate], k: int = TOP_K, threshold: float = SCORE_THRESHOLD) -> list[Candidate]:
    kept = [c for c in cands if c.score >= threshold]
    kept.sort(key=lambda c: -c.score)
    return kept[:k]


def diversify(top: list[Candidate], pool: list[Candidate], per_source: int = 2, threshold: float = SCORE_THRESHOLD) -> list[Candidate]:
    """Make room for the best Hugging Face and Show HN matches that passed the bar.

    Launched products (Show HN) and models/demos (Hugging Face) are often the real rivals,
    but GitHub READMEs give repos more text to match, so a plain top-k can be all GitHub.
    Each missing source gets up to `per_source` slots, taken from the weakest GitHub entries."""
    out = list(top)
    k = max(len(top), 1)
    for group in (("hf-space", "hf-model"), ("hn",)):
        have = [c for c in out if c.source in group]
        extra = sorted((c for c in pool if c.source in group and c.score >= threshold and c not in out), key=lambda c: -c.score)
        for c in extra[: max(0, per_source - len(have))]:
            if len(out) >= k:
                gh = [x for x in out if x.source == "github"]
                if not gh:
                    break
                out.remove(min(gh, key=lambda x: x.score))
            out.append(c)
    out.sort(key=lambda c: -c.score)
    return out


QUADRANT_SPLIT = 0.45


def axes(problem: str, solution: str, mat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """x = same users and problem, y = same features and approach. Cosine per axis."""
    if not len(mat):
        return np.array([]), np.array([])
    pv, sv = embed([problem, solution])
    return mat @ pv, mat @ sv


def quadrant(x: float, y: float, split: float = QUADRANT_SPLIT) -> str:
    if x >= split and y >= split:
        return "rival"
    if x >= split:
        return "same-problem"
    if y >= split:
        return "same-build"
    return "loose"


def verdict(top: list[Candidate], quadrants: dict[str, str] | None = None) -> dict:
    """An honest headline. Uses overall similarity and, when available, the rival quadrant."""
    quadrants = quadrants or {}
    if not top:
        return {"level": "open", "title": "No close open-source match",
                "text": "Nothing on GitHub, Hugging Face or Show HN passed the similarity bar. That is not proof the idea is new: closed apps, app stores and startups are not searched here. Check those before you build."}
    rivals = [c for c in top if quadrants.get(c.id) == "rival" or (not quadrants and c.score >= 0.70)]
    unit = lambda c: "points" if c.source == "hn" else ("likes" if c.source.startswith("hf") else "stars")  # noqa: E731
    strong = [c for c in rivals if not c.stale and c.stars >= 50]
    if strong:
        b = strong[0]
        return {"level": "taken", "title": "Close to an active project",
                "text": f"{b.name} solves the same problem the same way and is actively maintained ({b.stars} {unit(b)}). Building a clone without a specific edge will not compete."}
    if rivals:
        return {"level": "crowded", "title": "Done before in open source",
                "text": f"{len(rivals)} {'project targets' if len(rivals) == 1 else 'projects target'} the same problem space with existing code, but {'it is' if len(rivals) == 1 else 'they are'} small or inactive. You must build an explicit differentiator to stand out."}
    if top[0].score >= 0.50:
        return {"level": "crowded", "title": "Neighbours, not twins",
                "text": "Existing projects share core elements. Without an explicit narrow audience or unique mechanism in your prompt, you will face direct competition."}
    return {"level": "open", "title": "Loosely related only",
            "text": "Only distant matches in open-source repositories. For broad consumer ideas (videos, social, chat), dominant closed platforms already solve this."}
