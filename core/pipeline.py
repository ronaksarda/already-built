"""End-to-end check: input guard -> plan (1 Gemma call) -> fetch -> rank (local HF models) -> report (gpt-oss).

Every stage degrades instead of failing, so the caller always gets a result
dict it can render, even when every network call failed.

Model roles:
- Gemma 4 via Gemini API: exactly one call per check. Reads the idea and the
  optional rival screenshot, writes search queries, refuses harmful ideas.
- sentence-transformers (local): decides what is similar. Nothing else ranks.
- gpt-oss via Groq: writes the report and powers the follow-up chat.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable

from . import gemma, groq, rank, report, sources
from .guard import HARM_MESSAGE, check_idea, project_name_from_text, title_from_text, check_image, fallback_queries, github_repo_from_url, is_harmful

Progress = Callable[..., None]  # (stage_key, human label, optional live detail)
MAP_POINTS = 60
MAP_OTHERS = 20  # grey context points on the chart; more turns it into noise
README_FETCH = 24
HF_TERMS = 4  # Hugging Face search matches words in the repo id, so it gets short two-word terms
HN_QUERIES = 3
PER_SOURCE_PICKS = 2  # best Hugging Face / Show HN matches kept in the list even when GitHub fills it

STAGES = [
    ("read", "Reading your idea"),
    ("plan", "Planning search queries"),
    ("fetch", "Searching GitHub, Hugging Face and Hacker News"),
    ("rank", "Ranking matching projects"),
    ("report", "Writing your report"),
]


def _noop(_k: str, _l: str, _d: str = "") -> None:
    pass


SAFETY_VERSION = 5  # bump when safety rules change; pages drop older saved results


def _base(idea: str) -> dict:
    return {
        "safety_version": SAFETY_VERSION,
        "status": "ok", "message": "", "idea": idea, "core_claim": "", "queries": [],
        "query_source": "", "rival": "", "warnings": [], "errors": [], "top": [],
        "map": [], "verdict": None, "report": None, "report_note": "",
        "counts": {"fetched": 0, "unique": 0, "kept": 0}, "partial": [], "title": "", "project_name": "",
        "models": {"plan": gemma.GEMMA_MODEL, "embed": rank.EMBED_MODEL, "report": ""},
        "gemini_calls": 0, "demo": False, "timings": {},
    }


# Gemma is the planner, but when it is slow or failing the user should not wait for it.
HEDGE_S = float(os.getenv("PLAN_HEDGE_S", "6"))  # start gpt-oss alongside Gemma after this many seconds
PLAN_DEADLINE_S = 30
GEMMA_SKIP_AFTER = 2  # consecutive Gemma failures before it is skipped for text-only checks
GEMMA_SKIP_S = 300
_gemma_health = {"fails": 0, "since": 0.0}
_gemma_lock = threading.Lock()


def _gemma_note(ok: bool) -> None:
    with _gemma_lock:
        if ok:
            _gemma_health.update(fails=0, since=0.0)
        else:
            _gemma_health["fails"] += 1
            _gemma_health["since"] = time.time()


def _gemma_skipped() -> bool:
    with _gemma_lock:
        if _gemma_health["fails"] < GEMMA_SKIP_AFTER:
            return False
        if time.time() - _gemma_health["since"] > GEMMA_SKIP_S:
            _gemma_health["fails"] = GEMMA_SKIP_AFTER - 1  # half-open: give Gemma one more try
            return False
        return True


def _plan_gemma(idea_text: str, img) -> tuple[dict, str]:
    has_img = bool(img and img.ok)
    try:
        p = gemma.plan(idea_text, img.data if has_img else None, img.mime if has_img else None)
    except gemma.NoKeyError:
        raise
    except Exception:
        _gemma_note(False)
        raise
    _gemma_note(True)
    return p, gemma.last_model


def _plan_groq(idea_text: str) -> tuple[dict, str]:
    text, model = groq.chat([{"role": "user", "content": gemma.plan_prompt(idea_text, False)}], temperature=0.2, json_mode=True)
    return gemma.validate_plan(gemma.extract_json(text)), model


def _plan(res: dict, idea_text: str, img) -> bool:
    """Fill queries. Returns False when the idea must be refused.

    Gemma and gpt-oss write the same plan. Gemma starts first; if it has not answered
    within HEDGE_S seconds (or fails), gpt-oss starts too and the first valid plan wins.
    Only Gemma reads screenshots, so with an image Gemma is always tried."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    has_img = bool(img and img.ok)
    use_gemma = bool(gemma.api_key()) and (has_img or not _gemma_skipped())
    use_groq = bool(groq.api_key())
    p, plan_err = None, ""
    pool = ThreadPoolExecutor(max_workers=2)
    futures = {}
    try:
        if use_gemma:
            res["gemini_calls"] += 1
            futures[pool.submit(_plan_gemma, idea_text, img)] = "gemma"
        elif not gemma.api_key():
            plan_err = "Gemma is not configured (no GEMINI_API_KEY)."
        else:
            plan_err = "Gemma skipped: it failed on recent checks."
        hedged = not use_gemma
        if hedged and use_groq:
            futures[pool.submit(_plan_groq, idea_text)] = "groq"
        deadline = time.time() + PLAN_DEADLINE_S
        while futures and p is None and time.time() < deadline:
            timeout = HEDGE_S if not hedged else max(0.1, deadline - time.time())
            done, _ = wait(list(futures), timeout=timeout, return_when=FIRST_COMPLETED)
            if not done and not hedged:
                hedged = True
                if use_groq:
                    futures[pool.submit(_plan_groq, idea_text)] = "groq"
                continue
            for f in done:
                who = futures.pop(f)
                try:
                    plan, model = f.result()
                except Exception as e:
                    if who == "gemma":
                        plan_err = str(e) or "Gemma failed."
                        if not hedged and use_groq:
                            hedged = True
                            futures[pool.submit(_plan_groq, idea_text)] = "groq"
                    continue
                if p is None:
                    p = plan
                    res["models"]["plan"] = model
                    res["query_source"] = "gemma" if who == "gemma" else f"fallback: {model}" + (f" ({plan_err})" if plan_err else "")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)  # a slow loser finishes in the background

    if p is None and plan_err:
        res["errors"].append(plan_err)  # only surfaced when no planner worked at all
    if has_img and res.get("query_source") != "gemma":
        res["warnings"].append("Screenshot skipped: reading images needs Gemma, which didn't answer in time.")

    if p is None:
        res.update(queries=fallback_queries(idea_text), query_source="fallback: keywords")
        res["models"]["plan"] = "keywords (no LLM)"
        res["warnings"].append("The search planner was unavailable, so plain keywords from your text were searched. Close rivals may be missing.")
        return True

    if p["refuse"]:
        _refused(res)
        return False

    direct_queries = fallback_queries(idea_text)
    combined: list[str] = []
    if direct_queries:
        combined.append(direct_queries[0])
    for q in p.get("queries", []):
        if q and q.lower() not in [c.lower() for c in combined]:
            combined.append(q)
    for q in direct_queries[1:]:
        if q and q.lower() not in [c.lower() for c in combined]:
            combined.append(q)

    res["title"] = p.get("title") or ""
    res["project_name"] = res.get("project_name") or p.get("project_name") or ""
    res.update(core_claim=p["core_claim"], queries=combined[:6], problem=p.get("problem", ""), solution=p.get("solution", ""))
    rival = p["rival_description"]
    if has_img and (not rival or rival.lower().startswith("unreadable")):
        res["warnings"].append("Couldn't read the screenshot. Continued with text only.")
        rival = ""
    res["rival"] = rival if has_img else ""
    return True


def hf_terms(queries: list[str], n: int = HF_TERMS) -> list[str]:
    """Two-word terms for Hugging Face, whose search is a substring match on "owner/name".

    "lecture slides flashcards" finds nothing there; "slides flashcards" and "flashcards" can."""
    split = [[w for w in q.lower().split() if len(w) > 2 and w not in ("github", "app", "tool", "open", "source")] for q in queries]
    # Specific word pairs first (one per query, then a second pair), single words only to fill up.
    candidates = [" ".join(w[-2:]) for w in split if len(w) >= 2] + [" ".join(w[:2]) for w in split if len(w) >= 3] + [w[-1] for w in split if w]
    terms: list[str] = []
    for t in candidates:
        if t not in terms:
            terms.append(t)
    return terms[:n]


def _fetch(res: dict, use_cache: bool) -> tuple[list[sources.Candidate], bool]:
    """Returns (candidates, every_source_failed). Sources that failed are listed in res["partial"].

    All searches run in parallel; results are merged in a fixed order so a run is reproducible."""
    from concurrent.futures import ThreadPoolExecutor

    jobs: list[tuple[str, Callable[[], list]]] = []
    for q in res["queries"]:
        jobs.append(("github", lambda q=q: sources.search_github(q, use_cache=use_cache)))
    for q in hf_terms(res["queries"]):
        for kind in ("hf-space", "hf-model"):
            jobs.append(("hf", lambda q=q, kind=kind: sources.search_hf(q, kind=kind, use_cache=use_cache)))
    for q in res["queries"][:HN_QUERIES]:
        jobs.append(("hn", lambda q=q: sources.search_hn(q, use_cache=use_cache)))

    def attempt(fn):
        try:
            return fn(), None
        except (sources.RateLimitError, sources.SourceError) as e:
            return None, e
        except Exception as e:  # a parser surprise in one source must not sink the others
            return None, sources.SourceError(f"A search failed ({type(e).__name__}).")

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda j: attempt(j[1]), jobs))

    found: list[sources.Candidate] = []
    ok = {"github": False, "hf": False, "hn": False}
    for (src, _), (items, err) in zip(jobs, outcomes):
        if err is None:
            found += items
            ok[src] = True
            continue
        msg = str(err)
        if isinstance(err, sources.RateLimitError) and src == "github":
            msg += " Results below are partial. A GITHUB_TOKEN in .env raises the limit."
        if msg not in res["errors"]:
            res["errors"].append(msg)
    names = {"github": "GitHub", "hf": "Hugging Face", "hn": "Hacker News"}
    res["partial"] = [names[k] for k, v in ok.items() if not v]
    return found, not any(ok.values())


def run(idea: str, image: bytes | None = None, use_cache: bool = True, progress: Progress = _noop) -> dict:
    t0 = time.time()
    res = _base((idea or "").strip())

    # ---- 1. input checks (no API calls) ----
    progress(*STAGES[0])
    chk = check_idea(idea)
    if not chk.ok:
        res.update(status=chk.kind, message=chk.message)
        return res
    res["warnings"] += chk.warnings

    idea_text = res["idea"]
    exclude_id = None
    if chk.kind == "url":
        gh = github_repo_from_url(chk.url)
        if gh:
            full = f"{gh[0]}/{gh[1]}"
            exclude_id = f"github:{full}"
            desc = ""
            try:
                repo = sources.get_github_repo(*gh, use_cache=use_cache)
                if repo is not None:
                    exclude_id, full, desc = repo.id, repo.name, repo.description
            except (sources.SourceError, sources.RateLimitError):
                pass
            readme = sources.fetch_readme(full, use_cache)
            if not desc and not readme:
                try:
                    page_text = sources.fetch_url_text(f"https://github.com/{full}", use_cache)
                    if len(page_text) > 40:
                        readme = page_text[:1200]
                except Exception:
                    pass
            res["project_name"] = full.split("/")[-1]
            idea_text = ". ".join(p for p in [rank._split_name(full), desc, readme[:800]] if p)
            if not idea_text:
                res.update(status="url_failed", message="That GitHub repo doesn't exist, is private, or has no description/README. Describe the idea in words instead.")
                return res
        else:
            idea_text = sources.fetch_url_text(chk.url, use_cache)
        if len(idea_text) < 20:
            res.update(status="url_failed", message="Couldn't read enough from that link. Describe the idea in 1-3 sentences instead.")
            return res
        if is_harmful(idea_text):
            return _finish(_refused(res), t0)
        res["warnings"].append("Used the page behind your link as the idea. The project at that link is left out of the results.")
        res["idea_from_url"] = idea_text[:600]

    img = check_image(image) if image else None
    if img and not img.ok and img.message:
        res["warnings"].append(img.message)

    # ---- 2. plan: one Gemma call ----
    progress(*STAGES[1])
    t = time.time()
    if not _plan(res, idea_text, img):
        return _finish(res, t0)
    res["timings"]["plan"] = round(time.time() - t, 2)

    # ---- 3. fetch ----
    progress(*STAGES[2], "searching: " + ", ".join(res["queries"]))
    t = time.time()
    found, all_failed = _fetch(res, use_cache)
    res["timings"]["fetch"] = round(time.time() - t, 2)
    res["counts"]["fetched"] = len(found)
    unique = [rank.annotate(c) for c in rank.dedupe(found) if c.id != exclude_id]
    res["counts"]["unique"] = len(unique)
    by_source: dict[str, int] = {}
    for c in unique:
        key = "hf" if c.source.startswith("hf") else c.source
        by_source[key] = by_source.get(key, 0) + 1
    res["counts"]["by_source"] = by_source
    if all_failed:
        res.update(status="source_failed", message="Couldn't reach GitHub, Hugging Face or Hacker News, so there is nothing to compare yet.")
        return _finish(res, t0)

    # ---- 4. rank: local embeddings, then again with README text ----
    progress(*STAGES[3], f"{len(unique)} unique results after removing forks and repeats")
    t = time.time()
    rank_text = f"{idea_text}. {res['core_claim']}" if res["core_claim"] else idea_text
    top: list[sources.Candidate] = []
    quad: dict = {}
    if unique:
        try:
            rank.score(rank_text, unique)
        except Exception as e:  # model missing or failed to load
            res.update(status="rank_failed", message=f"The similarity model couldn't load ({type(e).__name__}), so nothing could be ranked. Run python scripts/prefetch.py once with internet, then try again.")
            return _finish(res, t0)
        shortlist = sorted(unique, key=lambda c: -c.score)[:README_FETCH]
        readmes = sources.fetch_readmes([c.name for c in shortlist if c.source == "github"], use_cache)
        for c in shortlist:
            if c.source == "github" and c.name in readmes:
                c.readme = readmes[c.name]
                rank.annotate(c)
        ranked = sorted(unique, key=lambda c: -c.score)
        pool = ranked[:MAP_POINTS]
        for group in (("hf-space", "hf-model"), ("hn",)):  # READMEs lift GitHub scores; keep the other sources in reach
            pool += [c for c in ranked if c.source in group and c not in pool][:PER_SOURCE_PICKS]
        _, mat = rank.score(rank_text, pool)
        top = rank.select(pool)
        top = rank.diversify(top, pool, PER_SOURCE_PICKS)
        # Two meaningful axes instead of an abstract projection.
        problem = res.get("problem") or idea_text
        solution = res.get("solution") or idea_text
        res["axes_from"] = "gemma" if res.get("problem") and res.get("solution") else "idea text (no LLM split)"
        xs, ys = rank.axes(problem, solution, mat)
        pid = {c.id: f"P{i}" for i, c in enumerate(top, 1)}
        res["map"] = []
        others = 0
        for c, x, y in zip(pool, xs, ys):
            if c.id not in pid and (c.score < rank.SCORE_THRESHOLD - 0.05 or others >= MAP_OTHERS):
                continue  # far-off noise stays off the chart
            others += c.id not in pid
            res["map"].append({"x": round(float(x), 3), "y": round(float(y), 3), "name": c.name, "url": c.url, "source": c.source,
                               "score": round(c.score, 3), "pid": pid.get(c.id, ""), "kind": "top" if c.id in pid else "other",
                               "quadrant": rank.quadrant(float(x), float(y))})
        res["quadrant_split"] = rank.QUADRANT_SPLIT
        quad = {(p["name"], p["url"]): p["quadrant"] for p in res["map"]}
    res["timings"]["rank"] = round(time.time() - t, 2)
    res["counts"]["kept"] = len(top)
    res["top"] = [c.to_dict() for c in top]
    for d in res["top"]:
        d["quadrant"] = quad.get((d["name"], d["url"]), "")
    res["verdict"] = rank.verdict(top, {c.id: quad.get((c.name, c.url), "") for c in top} if quad else None)
    if res.get("partial") and res["verdict"]["level"] == "open":
        # An empty list from a half-failed search is not evidence that the space is open.
        res["verdict"] = {"level": "unknown", "title": "Search incomplete",
                          "text": f"{', '.join(res['partial'])} couldn't be searched, so this list is partial. Run it again in a few minutes before trusting it."}

    # ---- 5. report: gpt-oss, rules fallback ----
    progress(*STAGES[4], f"{len(top)} projects passed the similarity bar")
    t = time.time()
    try:
        res["report"] = report.llm_report(idea_text, res["core_claim"], top, res["rival"])
    except groq.GroqError as e:
        res["report"] = report.rules_report(top)
        res["report_note"] = f"{e} This report is built from the data by fixed rules, not by a language model."
    if res["report"].get("refuse"):
        # The second model caught what the first missed: drop everything and show only the refusal.
        return _finish(_refused(res), t0)
    res["models"]["report"] = res["report"]["model"]
    res["timings"]["report"] = round(time.time() - t, 2)
    return _finish(res, t0)


def _refused(res: dict) -> dict:
    res.update(status="harmful", message=HARM_MESSAGE, top=[], map=[], report=None, verdict=None, position=None)
    return res


def _finish(res: dict, t0: float) -> dict:
    res["timings"]["total"] = round(time.time() - t0, 2)
    # A stated name beats a model's guess; the title falls back to the idea's first words.
    stated = project_name_from_text(res["idea"])
    res["project_name"] = stated or res.get("project_name") or ""
    if res["project_name"] and res["project_name"].lower() not in res["idea"].lower() and not res.get("idea_from_url"):
        res["project_name"] = ""  # the model may only repeat a name the user wrote, never invent one
    # A name the user gave is the heading; otherwise the planner's short summary, then the idea's first words.
    res["title"] = res["project_name"] or res.get("title") or title_from_text(res.get("core_claim") or res["idea"])
    return res
