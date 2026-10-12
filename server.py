"""Already Built? web server.

Run:  python server.py        (then open http://localhost:8000)
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import threading
import time
import uuid
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from pathlib import Path

mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("font/woff2", ".woff2")

from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from core import gemma, groq, pipeline, rank, report  # noqa: E402
from core.guard import MAX_IMAGE_BYTES, check_idea  # noqa: E402

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DEMO_PATH = ROOT / "demo" / "demo_result.json"

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_PARALLEL_CHECKS = int(os.getenv("MAX_PARALLEL_CHECKS", "2"))
JOB_TTL_S = 2 * 3600
MAX_JOBS = 300
MAX_WAITING = int(os.getenv("MAX_WAITING_CHECKS", "20"))  # running + queued checks before the server says "busy"
MAX_IDEA_FIELD = 20_000  # raw form field cap; the guard enforces the real 1200-char limit
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"  # set behind a reverse proxy so limits use the real client IP


@asynccontextmanager
async def lifespan(_app):
    # Load the embedding model in the background so the first check is fast.
    threading.Thread(target=_safe_warm, daemon=True).start()
    yield


app = FastAPI(title="Already Built?", docs_url=None, redoc_url=None, lifespan=lifespan)

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", "microphone=(self), camera=()")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp

# ---------- simple per-IP rate limits (protect the free API quotas) ----------
LIMITS = {
    "check": (int(os.getenv("LIMIT_CHECKS", "8")), 600),
    "chat": (int(os.getenv("LIMIT_CHAT", "40")), 600),
    "speech": (int(os.getenv("LIMIT_SPEECH", "30")), 600),
}  # (requests, window seconds)
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def client_ip(request: Request) -> str:
    if TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, bucket: str) -> None:
    n, window = LIMITS[bucket]
    ip = client_ip(request)
    now = time.time()
    with _hits_lock:
        if len(_hits) > 5000:  # drop idle buckets so the table can't grow forever
            for k in [k for k, q in _hits.items() if not q or now - q[-1] > 3600]:
                _hits.pop(k, None)
        q = _hits[(bucket, ip)]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= n:
            wait = int(window - (now - q[0])) + 1
            raise HTTPException(429, f"Slow down: limit is {n} per {window // 60} min. Try again in {max(1, wait // 60)} min.")
        q.append(now)


# ---------- jobs ----------
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
check_slots = threading.Semaphore(MAX_PARALLEL_CHECKS)
embed_state = {"ready": False, "error": ""}


def _gc_jobs() -> None:
    now = time.time()
    with jobs_lock:
        old = [k for k, j in jobs.items() if now - j["created"] > JOB_TTL_S]
        for k in old:
            jobs.pop(k, None)
        for k in [k for k, (t, _) in results_cache.items() if now - t > JOB_TTL_S]:
            results_cache.pop(k, None)
        if len(jobs) > MAX_JOBS:
            done = [k for k in jobs if jobs[k]["state"] == "done"]
            for k in sorted(done, key=lambda k: jobs[k]["created"])[: len(jobs) - MAX_JOBS]:
                jobs.pop(k, None)


# Same idea + same screenshot within 2 h returns the stored result: no second Gemini call, same answer.
results_cache: dict[str, tuple[float, dict]] = {}


def result_key(idea: str, image: bytes | None) -> str:
    norm = " ".join((idea or "").lower().split())
    return hashlib.sha256(norm.encode() + b"|" + (image or b"")).hexdigest()


def _run_job(job_id: str, idea: str, image: bytes | None) -> None:
    job = jobs.get(job_id)
    if job is None:
        return

    def progress(key: str, label: str, detail: str = "") -> None:
        job.update(stage=key, label=label, detail=detail)

    job.update(stage="queue", label="Waiting for a free slot")
    with check_slots:
        try:
            # No wait for the embedding model here: Gemma and the searches run while it loads.
            job["result"] = pipeline.run(idea, image=image, progress=progress)
            if job["result"].get("status") == "ok" and not job["result"].get("errors"):
                results_cache[result_key(idea, image)] = (time.time(), job["result"])
        except Exception as e:  # never leave the page hanging
            job["result"] = {"status": "crashed", "message": f"Unexpected error ({type(e).__name__}). Try again, or open the saved example."}
        job["state"] = "done"


def _warm() -> None:
    try:
        rank.warm_up()
        embed_state.update(ready=True, error="")
    except Exception as e:
        embed_state["error"] = f"Embedding model failed to load ({type(e).__name__}). Run python scripts/prefetch.py with internet once."
        raise


def _safe_warm() -> None:
    try:
        _warm()
    except Exception:
        pass


# ---------- API ----------
@app.get("/api/health")
def health() -> dict:
    return {
        "gemma": bool(gemma.api_key()),
        "groq": bool(groq.api_key()),
        "chat": bool(groq.api_key() or gemma.api_key()),  # gpt-oss first, Gemma 4 as the fallback
        "github_token": bool(os.getenv("GITHUB_TOKEN")),
        "embed_ready": embed_state["ready"],
        "safety_version": pipeline.SAFETY_VERSION,
        "embed_error": embed_state["error"],
        "models": {"plan": gemma.GEMMA_MODEL, "embed": rank.EMBED_MODEL, "report": groq.CHAT_MODELS, "speech": groq.STT_MODEL},
    }


@app.post("/api/check")
async def check(request: Request, idea: str = Form(""), image: UploadFile | None = File(None), force: bool = Form(False)) -> dict:
    if len(idea) > MAX_IDEA_FIELD:
        idea = idea[:MAX_IDEA_FIELD]  # the guard still answers "too long"; this only caps memory
    img_bytes = None
    if image is not None and image.filename:
        img_bytes = await image.read(MAX_IMAGE_BYTES + 1)  # guard.check_image rejects anything larger
    _gc_jobs()
    job_id = uuid.uuid4().hex
    hit = results_cache.get(result_key(idea, img_bytes))
    if hit and not force and time.time() - hit[0] < JOB_TTL_S:
        with jobs_lock:
            jobs[job_id] = {"state": "done", "stage": "report", "label": "Done", "created": time.time(),
                            "result": {**hit[1], "cached_at": hit[0]}}
        return {"job_id": job_id, "cached": True}
    # Input the guard rejects costs no API call, so it must not cost the user any of their limit either.
    chk = check_idea(idea)
    if not chk.ok:
        with jobs_lock:
            jobs[job_id] = {"state": "done", "stage": "read", "label": "Done", "created": time.time(),
                            "result": {**pipeline._base(idea.strip()[:MAX_IDEA_FIELD]), "status": chk.kind, "message": chk.message}}
        return {"job_id": job_id}
    rate_limit(request, "check")
    with jobs_lock:
        if sum(1 for j in jobs.values() if j["state"] == "running") >= MAX_WAITING:
            raise HTTPException(503, "The server is busy with other checks. Try again in a minute.")
        jobs[job_id] = {"state": "running", "stage": "queue", "label": "Starting", "result": None, "created": time.time()}
    threading.Thread(target=_run_job, args=(job_id, idea, img_bytes), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/check/{job_id}")
def check_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "This check expired. Run it again.")
    out = {"state": job["state"], "stage": job["stage"], "label": job["label"], "detail": job.get("detail", ""), "stages": pipeline.STAGES}
    if job["state"] == "done":
        out["result"] = job["result"]
    return out


class ChatMsg(BaseModel):
    role: str
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    job_id: str = ""
    messages: list[ChatMsg] = Field(max_length=40)
    result: dict | None = None  # sent by the page when the server no longer has the job


@app.post("/api/chat")
def chat(request: Request, body: ChatIn) -> dict:
    rate_limit(request, "chat")
    if not body.messages or body.messages[-1].role != "user" or not body.messages[-1].content.strip():
        raise HTTPException(400, "Type a question first.")
    job = jobs.get(body.job_id)
    res = (job or {}).get("result") or body.result
    if not res or res.get("status") not in ("ok", None):
        raise HTTPException(400, "Run a check first, then ask about it.")
    if not isinstance(res.get("top", []), list) or len(json.dumps(res)) > 400_000:
        raise HTTPException(413, "Result too large to discuss. Run the check again.")
    try:
        text, model = report.chat_reply(res, [m.model_dump() for m in body.messages])
    except groq.GroqNoKey:
        raise HTTPException(503, "Chat needs GROQ_API_KEY or GEMINI_API_KEY in .env.")
    except groq.GroqError as e:
        raise HTTPException(503, str(e))
    except (TypeError, ValueError, KeyError, AttributeError):
        raise HTTPException(400, "This result is damaged. Run the check again, then ask.")
    return {"reply": text.strip(), "model": model}


@app.post("/api/transcribe")
async def transcribe(request: Request, audio: UploadFile = File(...), language: str = Form("")) -> dict:
    rate_limit(request, "speech")
    if not groq.api_key():
        raise HTTPException(503, "no_server_stt")  # page falls back to the browser's own speech recognition
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording too long. Keep it under 2 minutes.")
    if len(data) < 1200:
        raise HTTPException(400, "Didn't catch anything. Hold the mic button a bit longer.")
    mime = (audio.content_type or "audio/webm").split(";")[0]
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav"}.get(mime, "webm")
    lang = language.strip().lower()[:2] or None
    try:
        text = groq.transcribe(data, f"speech.{ext}", mime, lang if lang and lang.isalpha() else None)
    except groq.GroqError as e:
        raise HTTPException(503, str(e))
    if not text:
        raise HTTPException(400, "Didn't catch any words. Try again closer to the mic.")
    return {"text": text}


@app.get("/api/demo")
def demo() -> JSONResponse:
    try:
        return JSONResponse(json.loads(DEMO_PATH.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(404, "Saved example is missing. Run python scripts/make_demo.py.")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")


def _local_lan_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    lan_ip = _local_lan_ip()
    print(f"Already Built? running locally on http://localhost:{port}")
    if lan_ip != "127.0.0.1":
        print(f"Available on your LAN on    http://{lan_ip}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
