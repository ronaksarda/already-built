"""Run one real check and save it as the offline fallback shown by "Open a saved example".

Run: python scripts/make_demo.py ["your idea"]
Uses whatever keys are in .env. Without keys the saved report is the rules-based one, and the page says so.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from core import pipeline  # noqa: E402

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
IDEA = ARGS[0] if ARGS else "An app that turns lecture slides into spaced-repetition flashcards for medical students."

res = pipeline.run(IDEA, use_cache=False, progress=lambda key, label, detail="": print("-", label, detail))
if res["status"] != "ok":
    sys.exit(f"Check failed: {res['status']} {res.get('message')} {res.get('errors')}")
if res["errors"] and "--allow-errors" not in sys.argv:
    sys.exit(f"Run had errors, demo not saved (pass --allow-errors to keep it): {res['errors']}")
res["demo"] = True
res["demo_note"] = (
    f"Recorded on a live run. Report by {res['models']['report']}. "
    "Links and numbers are from that run, so they may have changed since."
)
out = ROOT / "demo" / "demo_result.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(res, indent=1), encoding="utf-8")
print(f"Saved {out} ({len(res['top'])} projects, report: {res['models']['report']})")
