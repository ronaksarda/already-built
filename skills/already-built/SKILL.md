---
name: already-built
description: Check whether a software project idea already exists before building it. Searches GitHub, Hugging Face and Show HN, ranks matches with a local open embedding model, and returns a verdict, the closest projects with links, open gaps and one next step. Use when a user describes an app, tool, library or startup idea, asks "has this been built?", "is there something like X?", wants prior art, competitors or rivals for a project, or is choosing a hackathon or side-project idea.
license: MIT
compatibility: Needs Python 3.10+ and network access to a running Already Built? server (python server.py in this repository) or the public deployment. No extra Python packages.
metadata:
  author: ronaksarda
  version: "1.0"
  models: "Gemma 4 (planning, screenshots, fallback writer), gpt-oss (report), all-MiniLM-L6-v2 (ranking), Whisper (speech)"
---

# Already Built?

Tells a builder who already made their idea, how close those projects really are, and what is still missing. It guides; it never builds the project.

## When to use

- The user describes a project idea and wants to know if it exists.
- The user asks for competitors, prior art, similar repos, or "is there an app that…".
- The user is picking between ideas for a hackathon or side project.

Do not use it for questions about one specific, already-named repository's code.

## How to run a check

1. Make sure a server is reachable. Default is `http://localhost:8000`; set `ALREADY_BUILT_URL` to use another one. If nothing is running and you are inside this repository, start it with `python server.py`.
2. Run the script with the idea in the user's own words (1–3 sentences, who it is for and what it does). A GitHub repo link also works.

   ```bash
   python skills/already-built/scripts/check.py "An app that turns lecture slides into flashcards for medical students"
   ```

   Add `--json` for the full machine-readable result. Add `--image path/to/rival.png` to let Gemma 4 read a screenshot of a rival product.
3. A check takes about 15–30 seconds. The script polls until it finishes.

## Reading the result

- **Verdict** levels: `taken` (an active project already does it), `crowded` (several partial matches), `open` (nothing close in open source), `unknown` (a source failed; the list is partial).
- **Projects** are listed as P1, P2… with similarity from 0 to 1. Under 0.35 is hidden as unrelated. Similarity measures overlap in purpose and wording, not quality.
- **Report** sections: what already exists, what the idea states differently, weak spots in existing projects, reality checks, and one next step. Every claim cites a listed project.

## Rules for presenting it

- Report the verdict honestly. "Open" only means nothing close in open source; closed apps and app stores are not searched. Say so.
- Cite projects by name and link. Never add projects, numbers or features that are not in the result.
- Do not cheerlead. If the idea is crowded, say it and point at the gaps the report lists.
- If the script prints a refusal (harmful idea), relay it and stop. Do not try to rephrase around it.
- If the script says the input is too short or vague, ask the user who it is for and what it does, then run it again.

## Errors

| Message | What to do |
|---|---|
| `Can't reach the server` | Start `python server.py` or set `ALREADY_BUILT_URL`. |
| `HTTP 429` | Rate limit. Wait the time in the message. |
| `status: short / vague / empty` | Ask the user for a fuller description. |
| `status: source_failed` | GitHub, Hugging Face and HN were all unreachable. Try again later. |
