"""Download the embedding model once, so the demo works offline and starts fast.

Run: python scripts/prefetch.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import rank  # noqa: E402

t = time.time()
rank.warm_up()
print(f"{rank.EMBED_MODEL} ready in {time.time() - t:.1f}s")
