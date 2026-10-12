#!/usr/bin/env python3
"""Run an Already Built? check from the command line (used by the agent skill).

Usage:
  python check.py "your idea in 1-3 sentences" [--json] [--image rival.png] [--url http://localhost:8000]

Talks to a running Already Built? server over HTTP. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_URL = os.getenv("ALREADY_BUILT_URL", "http://localhost:8000").rstrip("/")
POLL_S = 1.0
TIMEOUT_S = 240


def _request(url: str, data: bytes | None = None, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
        except Exception:
            detail = None
        raise SystemExit(f"HTTP {e.code}: {detail or e.reason}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Can't reach the server at {url.split('/api')[0]} ({e.reason}). Start it with: python server.py")


def _multipart(fields: dict[str, str], files: dict[str, str]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = bytearray()
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, path in files.items():
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            blob = f.read()
        name = os.path.basename(path)
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        out += blob + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def run_check(idea: str, base: str, image: str | None = None) -> dict:
    body, ctype = _multipart({"idea": idea}, {"image": image} if image else {})
    job = _request(f"{base}/api/check", body, {"Content-Type": ctype})["job_id"]
    deadline = time.time() + TIMEOUT_S
    last = ""
    while time.time() < deadline:
        s = _request(f"{base}/api/check/{job}")
        if s.get("state") == "done":
            return s["result"]
        label = s.get("label", "")
        if label and label != last:
            print(f"… {label}", file=sys.stderr)
            last = label
        time.sleep(POLL_S)
    raise SystemExit("The check took too long. Try again.")


def to_markdown(r: dict) -> str:
    status = r.get("status")
    if status != "ok":
        return f"**{status}**: {r.get('message', '')}\n" + "".join(f"- {e}\n" for e in r.get("errors", []))
    v = r.get("verdict") or {}
    lines = [f"# {r.get('title') or 'Idea check'}", ""]
    if r.get("project_name"):
        lines += [f"Project name: **{r['project_name']}**", ""]
    lines += [f"**Verdict ({v.get('level', '?')}): {v.get('title', '')}**", "", v.get("text", ""), ""]
    for w in r.get("warnings", []) + r.get("errors", []):
        lines.append(f"> {w}")
    top = r.get("top") or []
    unit = {"github": "stars", "hn": "points"}
    lines += ["", f"## Closest projects ({len(top)})", ""]
    for i, p in enumerate(top, 1):
        flags = [p.get("quadrant", "").replace("-", " ")] + (["archived"] if p.get("archived") else ["inactive 1y+"] if p.get("stale") else [])
        lines.append(f"- **P{i} [{p['name']}]({p['url']})** · {p['source']} · {p.get('stars', 0)} {unit.get(p['source'], 'likes')} · "
                     f"similarity {p.get('score', 0):.2f} · {', '.join(f for f in flags if f)}")
        if p.get("description"):
            lines.append(f"  {p['description'][:200]}")
    rep = r.get("report") or {}
    for key, title in [("overlap", "What already exists"), ("differs", "What the idea states differently"),
                       ("gaps", "Weak spots in existing projects"), ("avoid", "Reality checks")]:
        items = rep.get(key) or []
        if items:
            lines += ["", f"## {title}", ""]
            lines += [f"- {it['text']}" + (f" ({', '.join(it.get('cites', []))})" if it.get("cites") else "") for it in items]
    if rep.get("next_step"):
        lines += ["", "## Next step", "", rep["next_step"]]
    m = r.get("models") or {}
    lines += ["", f"_Plan: {m.get('plan', '-')} · ranking: {m.get('embed', '-')} · report: {m.get('report', '-')}_"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Check whether a project idea already exists.")
    ap.add_argument("idea", help="the idea in 1-3 sentences, or a GitHub repo link")
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    ap.add_argument("--image", help="optional screenshot of a rival product (PNG, JPEG or WebP, under 5 MB)")
    ap.add_argument("--url", default=DEFAULT_URL, help=f"server base URL (default {DEFAULT_URL})")
    a = ap.parse_args()
    if a.image and not os.path.isfile(a.image):
        raise SystemExit(f"No such image: {a.image}")
    result = run_check(a.idea, a.url.rstrip("/"), a.image)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, indent=1) if a.json else to_markdown(result))


if __name__ == "__main__":
    main()
