# Already Built?

> Found an open-source project like yours and want to quit? Describe your product idea by typing or speaking it. **Already Built?** searches GitHub, Hugging Face Spaces & Models, and Hacker News (Show HN), performs local semantic vector ranking using open-weight embedding models, maps your competitors onto a 2D market quadrant, and generates a grounded competitive breakdown of what exists and which gaps existing projects leave open.

It guides your product positioning and MVP validation. It does not blindly generate code or glaze your project.

---

## Table of Contents

- [Hackathon Challenges: Gemma 4 & Open-Source AI](#hackathon-challenges-gemma-4--open-source-ai)
- [Agent Skill](#agent-skill)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Create a Virtual Environment](#2-create-a-virtual-environment)
  - [3. Install Dependencies](#3-install-dependencies)
  - [4. Configure Environment Variables](#4-configure-environment-variables)
  - [5. Prefetch the Embedding Model](#5-prefetch-the-embedding-model)
  - [6. Start the Server](#6-start-the-server)
- [Architecture & System Design](#architecture--system-design)
  - [Directory Structure](#directory-structure)
  - [The 7-Stage Pipeline](#the-7-stage-pipeline)
  - [Data Flow Diagram](#data-flow-diagram)
  - [Core Subsystems](#core-subsystems)
- [2D Competitive Matrix & Semantic Ranking](#2d-competitive-matrix--semantic-ranking)
- [API Reference](#api-reference)
- [Environment Variables](#environment-variables)
- [Available Scripts](#available-scripts)
- [Testing Guide](#testing-guide)
- [Deployment](#deployment)
  - [Local Area Network (LAN) Access](#local-area-network-lan-access)
  - [Docker Container](#docker-container)
  - [Production Reverse Proxy (Nginx / Caddy)](#production-reverse-proxy-nginx--caddy)
  - [Systemd Service (Linux VPS)](#systemd-service-linux-vps)
- [Troubleshooting](#troubleshooting)
- [Privacy & Security](#privacy--security)
- [Contributing](#contributing)
- [License](#license)

---

## Hackathon Challenges: Gemma 4 & Open-Source AI

Full submission answers: [SUBMISSION.md](SUBMISSION.md).

**Where Gemma 4 works** (`gemma-4-26b-a4b-it` via the Gemini API, `google-genai` SDK; `gemma-4-31b-it` as a second model):

| Job | What Gemma 4 does | Code |
|---|---|---|
| Plan every check | Reads the idea and writes the core claim, the problem and solution sentences (the two chart axes), 3-5 search queries, a short title, and the project name only if the user stated one | [`core/gemma.py` `plan()`](core/gemma.py), [`core/pipeline.py` `_plan()`](core/pipeline.py) |
| Multimodal: read a rival | Reads an uploaded screenshot of a competitor's product and describes what it does; that description goes into the report | [`core/gemma.py` `plan()`](core/gemma.py) |
| Safety | Refuses ideas meant to harm people, before any search runs | [`PLAN_PROMPT`](core/gemma.py) |
| Backup writer | Writes the report and answers the chat when gpt-oss on Groq is down | [`core/report.py` `llm()`](core/report.py), [`core/gemma.py` `chat()`](core/gemma.py) |

Gemma 4 runs with `thinking_level="minimal"`: a plan takes about 5-9 s instead of timing out at 20 s. Gemma always gets the first try; a gpt-oss plan is held back for up to 10 s so Gemma wins whenever it answers, and with a screenshot attached Gemma gets its full time because only it can read images.

**Open-weight / open-source AI in the loop**: Gemma 4 (planning, vision, safety), `openai/gpt-oss-120b` / `gpt-oss-20b` (report and chat on Groq), `sentence-transformers/all-MiniLM-L6-v2` (runs locally and is the only thing that decides similarity), `whisper-large-v3-turbo` (speech to text). MIT licensed.

## Agent Skill

[`skills/already-built/`](skills/already-built/SKILL.md) is an [Agent Skills](https://agentskills.io) package: a `SKILL.md` with `name` and `description` frontmatter and a standard-library script. An agent that loads it can check an idea for a user:

```bash
python skills/already-built/scripts/check.py "An app that turns lecture slides into flashcards for medical students"
python skills/already-built/scripts/check.py "..." --image rival.png --json --url http://localhost:8000
```

## Key Features

- **Multi-Modal Idea Intake**: Input ideas via raw text, direct GitHub repository URLs (`github.com/user/repo`), voice dictation (via Whisper or browser Web Speech API), or attach competitor screenshots for OCR and UI inspection.
- **Local Input Guardrails**: Zero-API-cost validation catching empty inputs, gibberish, vague phrases, non-software questions/lyrics (e.g., meme queries), prompt injection, and dangerous/harmful intentions before any LLM quota is consumed.
- **One-Call Search Planner**: Uses Google Gemma 4 (`gemma-4-26b-a4b-it`) via Google GenAI to deconstruct the problem/solution space, parse uploaded rival UI screenshots, and generate targeted search queries across three platforms.
- **Multi-Source Ecosystem Crawling**: Concurrently searches:
  - **GitHub**: High-star active repositories and codebases via the GitHub Search API.
  - **Hugging Face**: AI models and live interactive Spaces demos via Hugging Face Hub APIs.
  - **Hacker News**: Historic launch threads and community feedback via Algolia Show HN indexing.
- **Local Dense Vector Ranking**: Computes cosine similarity locally via `sentence-transformers/all-MiniLM-L6-v2` across dual dimensions (problem/user fit vs. solution/tech approach). Eliminates arbitrary LLM hallucinated ranking scores.
- **Interactive 2D Market Quadrant**: Projects rivals visually onto an interactive quadrant chart (Direct Competitors, Alternative Approaches, Same Audience/Different Tool, and Peripheral Projects).
- **Grounded Gap Analysis**: Synthesizes structured competitive intelligence (feature overlaps, technical differentiators, unaddressed user pain points, competitor design mistakes, and concrete MVP next steps) using Groq open-weight inference (`openai/gpt-oss-120b`). Citations strictly ground against fetched candidate data.
- **Context-Aware Strategy Advisor**: Follow-up chat powered by Groq with the full competitive intelligence payload preloaded into system context.
- **Resilient Fallback Chains**: Operates completely offline or with zero API keys using rule-based heuristics and bundled static examples.

---

## Tech Stack

| Layer | Technology | Details |
|---|---|---|
| **Language** | Python 3.10+ / 3.12 | Strongly typed with dataclasses, typing protocols, and asyncio |
| **Backend Framework** | FastAPI & Uvicorn | Async ASGI framework, non-blocking request handling, CSP middleware |
| **Frontend** | Vanilla HTML5 / CSS3 / ES Modules | High-contrast pixel aesthetic with custom Pixelon typography, Web Audio synth FX |
| **Search Planner LLM** | Google Gemma 4 (`gemma-4-26b-a4b-it`) | Single Gemini API call per check for intent breakdown and OCR |
| **Embedding Model** | `sentence-transformers/all-MiniLM-L6-v2` | Local Hugging Face PyTorch model; runs on CPU or CUDA |
| **Report & Chat LLM** | Groq (`openai/gpt-oss-120b` / `gpt-oss-20b`) | High-speed open-weight LLM inference with strict citation validation |
| **Speech-to-Text** | Whisper (`whisper-large-v3-turbo`) on Groq | Fast audio transcription with native browser `webkitSpeechRecognition` fallback |
| **Public Search APIs** | GitHub REST, Hugging Face Hub, HN Algolia | Concurrent multi-source search with disk-backed cache |

---

## Prerequisites

- **Python**: Version 3.10 or higher (Python 3.12 recommended).
- **Git**: For version control.
- **API Keys** (Free tiers available):
  - **Google Gemini API Key**: Free tier for Gemma 4 query planning. Get one at [Google AI Studio](https://aistudio.google.com/apikey).
  - **Groq API Key**: Free tier for fast report generation, follow-up chat, and Whisper STT. Get one at [Groq Console](https://console.groq.com/keys).
  - **GitHub Token** *(Optional)*: A Personal Access Token (PAT, no scopes required) increases the GitHub rate limit from 10 to 30 requests/minute.

---

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/your-username/already-built.git
cd already-built
```

### 2. Create a Virtual Environment

On macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the sample environment file:

```bash
cp .env.example .env
```

Open `.env` in your editor and add your keys:

```dotenv
# Required for Gemma query planning
GEMINI_API_KEY=your_gemini_api_key_here

# Required for report generation and follow-up advisor
GROQ_API_KEY=your_groq_api_key_here

# Optional: Higher GitHub API rate limits
GITHUB_TOKEN=your_optional_github_token_here
```

### 5. Prefetch the Embedding Model

Download the local sentence transformer model to your machine cache ahead of time. This takes ~90 MB and avoids first-run cold starts:

```bash
python scripts/prefetch.py
```

*Expected output:*
```text
sentence-transformers/all-MiniLM-L6-v2 ready in 1.4s
```

### 6. Start the Server

```bash
python server.py
```

*Expected console output:*
```text
Already Built? running locally on http://localhost:8000
Available on your LAN on    http://192.168.1.15:8000
```

Open your browser to `http://localhost:8000`.

---

## Architecture & System Design

### Directory Structure

```text
already-built/
├── core/                       # Core analytical engine and external integrations
│   ├── gemma.py                # Gemini API integration: query planning & screenshot OCR
│   ├── groq.py                 # Groq client: report generation, chat advisor & Whisper STT
│   ├── guard.py                # Fast local input validation & safety filters
│   ├── pipeline.py             # 7-stage orchestrator executing checks end-to-end
│   ├── rank.py                 # Local sentence-transformers vector ranking & quadrant math
│   ├── report.py               # Competitive report builder & citation grounding
│   └── sources.py              # Search scrapers: GitHub, Hugging Face & Hacker News
├── demo/                       # Offline fallbacks and sample outputs
│   └── demo_result.json        # Snapshot data for instant demo mode
├── scripts/                    # Maintenance and operational scripts
│   ├── make_demo.py            # Generates a fresh demo result from live APIs
│   └── prefetch.py             # Downloads Hugging Face embedding model locally
├── tests/                      # Automated test suite
│   ├── conftest.py             # Pytest fixtures and mocks
│   ├── test_core.py            # Unit tests for guardrails, ranking and pipelines
│   ├── test_server.py          # FastAPI endpoint integration tests
│   └── test_ui_clean.py        # Frontend assets, fonts, and clean layout tests
├── web/                        # Frontend client assets (served statically)
│   ├── fonts/                  # Custom font binaries (Pixelon.otf, Pixelon.ttf)
│   ├── app.js                  # Frontend application logic, state, and speech handler
│   ├── fx.js                   # Web Audio synthesizer for retro sound effects
│   ├── index.html              # Single-page web application structure
│   └── style.css               # Design system, layout, and pixel typography
├── .env.example                # Example configuration template
├── requirements.txt            # Python dependencies
└── server.py                   # FastAPI application entrypoint & background workers
```

### The 7-Stage Pipeline

```text
User Input (Text, Speech, or Repo URL) + Optional Competitor Screenshot
                              │
                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Local Guard (core/guard.py)                                          │
│    - Length & word count bounds (20-1200 chars, >= 4 words)             │
│    - Pattern match against vague filler, memes, and non-product lyrics │
│    - Regex checks against cyber-attacks, malware & violent intentions   │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Valid Idea
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Planning Stage (core/gemma.py via Gemini API)                       │
│    - Deconstructs core claim, target user, problem, and solution       │
│    - Analyzes competitor UI screenshot if attached                     │
│    - Emits optimized query terms for GitHub, Hugging Face, and HN      │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Search Queries
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Multi-Source Retrieval (core/sources.py)                            │
│    - Concurrently queries GitHub API, Hugging Face Hub, HN Algolia     │
│    - Pulls repo metadata, descriptions, stars, topics, and READMEs    │
│    - Persists query payloads to .cache/ for 24 hours                   │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Raw Candidates (~30-60 items)
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. Semantic Vector Ranking (core/rank.py)                              │
│    - Local all-MiniLM-L6-v2 embeddings (no remote API calls)           │
│    - Calculates Dual Similarity: Problem Vector vs. Solution Vector    │
│    - Applies cosine threshold (> 0.35) and selects top candidates      │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Top Ranked Projects
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 5. 2D Coordinate Mapping (core/rank.py)                                │
│    - Normalizes X (Problem Fit) and Y (Solution Fit)                   │
│    - Assigns quadrant labels and visual coordinates for canvas map     │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Market Map
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 6. Grounded Report Generation (core/report.py via Groq)                │
│    - Writes Overlap, Differentiators, Market Gaps, and Pitfalls        │
│    - Validates citations: strictly purges any ungrounded project refs  │
│    - Formulates executable next steps for founder validation           │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ Complete Intelligence Payload
                                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 7. Follow-up Advisory Chat (core/groq.py)                              │
│    - Interactive conversational sparring partner with report context   │
└────────────────────────────────────────────────────────────────────────┘
```

### Data Flow Diagram

```
Client (Browser)             FastAPI Server                   LLMs & Remote APIs
      │                            │                                   │
      │── 1. POST /api/check ─────>│                                   │
      │   (Idea text + image)      │── 2. Guardrail Checks             │
      │                            │   (Local - Zero API)              │
      │<── 3. Return {job_id} ─────│                                   │
      │                            │                                   │
      │                            │── 4. Query Plan ─────────────────>│ Gemma 4 (Gemini API)
      │                            │<── Return queries & claim ────────│
      │                            │                                   │
      │                            │── 5. Concurrent Crawl ───────────>│ GitHub / HF / HN
      │                            │<── Return repos & spaces ─────────│
      │                            │                                   │
      │                            │── 6. Dense Embeddings (Local)     │
      │                            │   (sentence-transformers)         │
      │                            │                                   │
      │                            │── 7. Generate Intelligence ──────>│ gpt-oss-120b (Groq)
      │                            │<── Grounded Report ───────────────│
      │                            │                                   │
      │── 8. GET /api/check/{id} ─>│                                   │
      │<── 9. Final Payload ───────│                                   │
      │                            │                                   │
      │── 10. POST /api/chat ─────>│                                   │
      │   (Ask follow-up question) │── 11. Grounded Context Chat ─────>│ gpt-oss (Groq)
      │<── 12. Strategic Advice ───│<── Strategic Response ────────────│
```

### Core Subsystems

#### 1. Input Guard (`core/guard.py`)
Intercepts raw user submissions before any remote network call is dispatched.
- **Length Filtering**: Rejects submissions shorter than 20 characters or 4 words (for Latin scripts), or over 1200 characters.
- **Content Density Analysis**: Normalizes character repetitions (e.g. `waassup` $\rightarrow$ `wasup`) and matches tokens against a comprehensive stopword/filler dictionary. If fewer than 3 unique content words remain, the submission is rejected as vague.
- **Non-Product Question & Meme Filter**: Detects questions and lyrical phrases (`"WHO LET THE DOGS OUT"`, `"why is the sky blue"`) lacking software product indicators (`app`, `website`, `tool`, `bot`, `cli`, etc.) and prompts for a concrete tool description.
- **Harm & Weaponization Detection**: Flags requests involving malware, credential harvesting, biometric stalking, bomb creation, or bodily harm. Permits defensive cybersecurity and harm-prevention projects (e.g. anti-suicide hotlines, plant poison detectors) via contextual exception rules.

#### 2. Query Planner (`core/gemma.py`)
Encapsulates Google's Gemma 4 (`gemma-4-26b-a4b-it`) via the Google GenAI SDK.
- Deconstructs the submission into structured JSON: `problem`, `solution`, `target_audience`, and `core_claim`.
- Generates platform-specific search keywords.
- When an image is provided, Gemma analyzes the UI layout, visual features, and tech clues from the rival's interface.

#### 3. Multi-Source Crawlers (`core/sources.py`)
- **GitHub**: Queries the GitHub Search API (`/search/repositories`). Parses repository names, full descriptions, star counts, primary languages, license types, and topics.
- **Hugging Face Hub**: Queries both Hugging Face Spaces (demos) and Models APIs.
- **Hacker News**: Leverages Algolia's real-time HN index to find historic "Show HN" posts.
- **Disk Caching**: All query results are cached locally in `.cache/` with a 24-hour TTL, preventing quota drain during iterative testing.

#### 4. Semantic Ranker (`core/rank.py`)
Uses `sentence-transformers/all-MiniLM-L6-v2` locally to encode candidate text against the user's idea.
- Generates two discrete cosine similarity metrics per candidate:
  1. **Problem Fit Score**: Does this rival address the same underlying customer pain point?
  2. **Solution Fit Score**: Does this rival use the same technical architecture or implementation approach?
- Discards noisy candidates scoring below `0.35` threshold.

#### 5. Report Synthesizer (`core/report.py`)
Calls Groq with open-weight models (`openai/gpt-oss-120b`, falling back to `openai/gpt-oss-20b`).
- Produces five analytical sections:
  1. `overlap`: Where current projects already implement your vision.
  2. `differs`: Features and approaches that are genuinely distinct.
  3. `gaps`: Unmet user demands and open niches in existing projects.
  4. `mistakes`: Common failures, deprecated tech, or complaints in competitor repos.
  5. `next_step`: Concrete validation task for day one.
- **Hallucination Prevention**: Enforces strict citation validation. Every reference citation (`[P1]`, `[P2]`, etc.) is mapped against actual retrieved projects. If the model invents a citation or hallucinates a non-existent feature, the citation is stripped.

---

## 2D Competitive Matrix & Semantic Ranking

Projects are projected onto an interactive 2D canvas across two axes:

```text
               High Solution Fit (Same Tech / Same Build)
                                │
          Quadrant 2:           │          Quadrant 1:
    Technical Competitor        │      Direct Competitor
 (Same architecture/build,      │  (Same problem, same users,
  targeting a different niche)  │   identical product model)
                                │
── Low Problem Fit ─────────────┼───────────── High Problem Fit ──
 (Different problem / users)    │   (Same target user & pain point)
                                │
          Quadrant 4:           │          Quadrant 3:
      Peripheral Match          │     Functional Alternative
 (Loosely related libraries,    │  (Solves the exact same problem
  tools, or infrastructure)     │   using a completely different way)
                                │
               Low Solution Fit (Different Implementation)
```

1. **Direct Competitors (Top-Right)**: Teams trying to do what you want to do, for the people you want to serve.
2. **Technical Overlap (Top-Left)**: Codebases with identical architecture or stack, but aimed at different verticals (e.g., medical flashcards vs. legal exam prep).
3. **Alternative Solutions (Bottom-Right)**: Projects solving your target problem without your proposed mechanism (e.g., manual spreadsheets vs. automated SaaS).
4. **Peripheral Projects (Bottom-Left)**: Lower-scoring foundational tools and dependencies.

---

## API Reference

The FastAPI server exposes the following JSON endpoints:

### 1. `GET /api/health`
Inspects backend readiness, API keys, and local model states.

**Response (200 OK):**
```json
{
  "gemma": true,
  "groq": true,
  "github_token": true,
  "embed_ready": true,
  "safety_version": 5,
  "embed_error": "",
  "models": {
    "plan": "gemma-4-26b-a4b-it",
    "embed": "sentence-transformers/all-MiniLM-L6-v2",
    "report": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
    "speech": "whisper-large-v3-turbo"
  }
}
```

---

### 2. `POST /api/check`
Submits a product idea for competitive analysis.

**Form Parameters:**
- `idea` (*string, required*): The product concept (20–1200 characters) or GitHub URL.
- `image` (*file upload, optional*): Competitor screenshot (PNG, JPEG, WebP, max 5 MB).
- `force` (*boolean, optional*): When `true`, bypasses the 2-hour server memory cache.

**Response (200 OK):**
```json
{
  "job_id": "a7945d82086e41b99786a3bcf4402324",
  "cached": false
}
```

---

### 3. `GET /api/check/{job_id}`
Polls the execution state of a running check.

**Response (200 OK - In Progress):**
```json
{
  "state": "running",
  "stage": "search",
  "label": "Searching GitHub, Hugging Face and Hacker News",
  "detail": "searching: medical flashcards, slide deck spaced repetition",
  "stages": [
    ["read", "Reading your idea"],
    ["plan", "Planning search queries"],
    ["search", "Searching GitHub, Hugging Face and Hacker News"],
    ["rank", "Ranking matching projects"],
    ["report", "Writing your report"]
  ]
}
```

**Response (200 OK - Complete):**
Returns the finished object including `status`, `top` candidates, `map` coordinates, `verdict`, and the grounded `report`.

---

### 4. `POST /api/chat`
Follow-up conversational questions about positioning and strategy.

**Request Body:**
```json
{
  "job_id": "a7945d82086e41b99786a3bcf4402324",
  "messages": [
    {
      "role": "user",
      "content": "What is the smallest MVP I can build this weekend to test the flashcard gap?"
    }
  ]
}
```

**Response (200 OK):**
```json
{
  "reply": "Focus strictly on parsing PDF slide headers and bullet points into basic Anki-compatible CSV cards. Do not build custom spaced repetition algorithms or authentication.",
  "model": "openai/gpt-oss-120b"
}
```

---

### 5. `POST /api/transcribe`
Transcribes voice dictation using Groq's hosted Whisper model.

**Form Parameters:**
- `audio` (*file upload, required*): WebM/WAV/MP3 audio blob (max 10 MB, up to 2 mins).
- `language` (*string, optional*): ISO 639-1 language code (e.g., `en`, `es`, `fr`).

**Response (200 OK):**
```json
{
  "text": "An automated testing tool for WebRTC audio applications."
}
```

---

### 6. `GET /api/demo`
Returns the static pre-recorded check payload from `demo/demo_result.json`. Used for offline demonstrations.

---

## Environment Variables

Configure these settings in `.env`:

| Variable | Type | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | String | *(None)* | **Required for Gemma planning.** Free API key from Google AI Studio. |
| `GEMMA_MODEL` | String | `gemma-4-26b-a4b-it` | Target Gemma model name on Google GenAI. |
| `GROQ_API_KEY` | String | *(None)* | **Required for report & chat.** Free API key from Groq Console. |
| `GROQ_MODELS` | CSV | `openai/gpt-oss-120b,openai/gpt-oss-20b` | Comma-separated prioritized list of Groq report models. |
| `GROQ_STT_MODEL`| String | `whisper-large-v3-turbo` | Whisper speech-to-text model on Groq. |
| `GITHUB_TOKEN` | String | *(None)* | Optional GitHub Personal Access Token to raise search rate limits. |
| `HF_TOKEN` | String | *(None)* | Optional Hugging Face User Access Token. |
| `EMBED_MODEL` | String | `sentence-transformers/all-MiniLM-L6-v2` | Hugging Face model identifier for local dense ranking. |
| `PORT` | Integer | `8000` | Port for the Uvicorn web server. |
| `HOST` | String | `0.0.0.0` | Host IP binding (`0.0.0.0` exposes server to LAN & containers). |
| `TRUST_PROXY` | Boolean | `0` | Set `1` when running behind Nginx or Cloudflare so rate limiting uses `X-Forwarded-For`. |
| `LIMIT_CHECKS` | Integer | `8` | Maximum full checks per client IP per 10-minute window. |
| `LIMIT_CHAT` | Integer | `40` | Maximum chat messages per client IP per 10-minute window. |
| `LIMIT_SPEECH` | Integer | `30` | Maximum audio transcriptions per IP per 10-minute window. |
| `MAX_PARALLEL_CHECKS`| Integer | `2` | Maximum concurrent analysis jobs executing at once. |
| `MAX_WAITING_CHECKS` | Integer | `20` | Queue depth limit before server rejects requests with 503 Busy. |
| `GEMMA_TIMEOUT_MS` | Integer | `20000` | Timeout in ms for Gemma planning before falling back to Groq. |
| `GEMMA_THINKING` | String | `minimal` | Gemma 4 thinking level. `default` turns the setting off (much slower plans). |
| `PLAN_HEDGE_S` | Float | `6` | Seconds before gpt-oss starts planning alongside Gemma. |
| `PLAN_GEMMA_GRACE_S` | Float | `10` | How long a finished gpt-oss plan waits for Gemma before it is used. |

---

## Available Scripts

### Run Development Server
```bash
python server.py
```
Starts FastAPI on port 8000 with hot-reloading and LAN address discovery.

### Prefetch Embedding Models
```bash
python scripts/prefetch.py
```
Downloads `sentence-transformers/all-MiniLM-L6-v2` to your local cache so tests and cold-starts run without network pauses.

### Generate Offline Demo Cache
```bash
python scripts/make_demo.py "Your test product concept here"
```
Runs a real check with your active API keys and writes the output directly to `demo/demo_result.json` for offline usage.

### Run Automated Tests
```bash
pytest
```
Executes the comprehensive offline test suite across all modules.

---

## Testing Guide

The test suite runs completely offline with no live API calls or keys required.

```bash
# Run all tests
pytest -v

# Run with coverage report
pytest --cov=core --cov=server tests/

# Run a specific test suite
pytest tests/test_core.py -v
pytest tests/test_server.py -v
pytest tests/test_ui_clean.py -v
```

### Test Suites Overview

1. **`tests/test_core.py`**:
   - Validates input guardrails (`core/guard.py`): length enforcement, filler words, meme checks, cyberattack refusals, and defensive security allowance.
   - Tests ranking mathematics (`core/rank.py`): cosine similarities, vector deduplication, thresholding, and quadrant positioning.
   - Verifies citation grounding (`core/report.py`): confirms hallucinated project citations are discarded.
   - Tests fallback resilience: verifies pipeline behavior when Gemini or Groq are offline or rate-limited.

2. **`tests/test_server.py`**:
   - Validates all FastAPI endpoints using Starlette `TestClient`.
   - Tests rate-limiting mechanics, 2-hour result memory caching, and request size boundaries.
   - Asserts security headers (Content Security Policy, X-Frame-Options, nosniff).

3. **`tests/test_ui_clean.py`**:
   - Asserts the absence of AI buzzwords or self-glazing in the UI.
   - Validates serving of custom `Pixelon` font binaries (`.otf`, `.ttf`).
   - Confirms clean prompt composer and chat container semantics.

---

## Deployment

### Local Area Network (LAN) Access

By default, `server.py` binds to `0.0.0.0`. When launched, the console logs both the localhost address and your workstation's LAN IP:

```text
Already Built? running locally on http://localhost:8000
Available on your LAN on    http://192.168.1.15:8000
```

Any device on the same Wi-Fi network (phones, tablets, laptops) can open `http://<YOUR_LAN_IP>:8000` directly.

---

### Docker Container

#### 1. Create a `Dockerfile` in the project root:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Prefetch the sentence transformers model during image build
RUN python scripts/prefetch.py

EXPOSE 8000

CMD ["python", "server.py"]
```

#### 2. Build and Run:

```bash
# Build Docker image
docker build -t already-built:latest .

# Run container with environment variables
docker run -d \
  --name already-built \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  already-built:latest
```

---

### Production Reverse Proxy (Nginx / Caddy)

When deploying behind a reverse proxy, set `TRUST_PROXY=1` in your `.env` so client rate limits track user IPs rather than the proxy.

#### Sample Nginx Configuration

```nginx
server {
    listen 80;
    server_name alreadybuilt.example.com;

    # Enforce HTTPS redirect
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name alreadybuilt.example.com;

    ssl_certificate /etc/letsencrypt/live/alreadybuilt.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/alreadybuilt.example.com/privkey.pem;

    client_max_body_size 12M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket & chunked streaming support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

### Systemd Service (Linux VPS)

To run the application as a background service on Ubuntu / Debian:

1. Create a service unit file:
   ```bash
   sudo nano /etc/systemd/system/already-built.service
   ```

2. Add configuration:
   ```ini
   [Unit]
   Description=Already Built? Application Service
   After=network.target

   [Service]
   Type=simple
   User=www-data
   WorkingDirectory=/var/www/already-built
   EnvironmentFile=/var/www/already-built/.env
   ExecStart=/var/www/already-built/.venv/bin/python server.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable already-built
   sudo systemctl start already-built
   sudo systemctl status already-built
   ```

---

## Troubleshooting

### 1. `Embedding model failed to load`
- **Cause**: PyTorch or `sentence-transformers` could not download `all-MiniLM-L6-v2` due to missing internet access or TLS/firewall blocks.
- **Solution**: Run `python scripts/prefetch.py` manually on an open connection. Check that `~/.cache/huggingface/` has read and write permissions.

### 2. `Rate Limit: 429 Too Many Requests`
- **Cause**: The IP has exceeded the allowed number of checks (`LIMIT_CHECKS=8` per 10 minutes) or GitHub's search rate limit has been hit.
- **Solution**:
  - Wait for the rate-limit window to expire (typically under 10 minutes).
  - Add a personal access token via `GITHUB_TOKEN` in `.env` to raise GitHub limits from 10 to 30 requests/min.
  - Adjust `LIMIT_CHECKS` in `.env` for higher internal limits.

### 3. `Speech Recognition / Microphone Not Working`
- **Cause**: Browsers restrict Web Audio and microphone access on non-secure (`http://`) origins unless on `localhost`.
- **Solution**:
  - When accessing via LAN IP (`http://192.168.x.x`), modern browsers may block the microphone. Serve through HTTPS via a reverse proxy (e.g., Caddy or Nginx with self-signed or Let's Encrypt certificates).
  - Ensure microphone permissions are allowed in the browser settings.

### 4. `Gemma 4 Timeout / Quota Exhaustion`
- **Cause**: Gemini API key expired, hit quota limits, or network latency exceeded 20 seconds.
- **Solution**:
  - The pipeline automatically falls back to Groq for query planning. If Groq is also down, it falls back to local regex search queries. Verify your `GEMINI_API_KEY` at [Google AI Studio](https://aistudio.google.com/apikey).

---

## Privacy & Security

- **No Remote Tracking**: No Google Analytics, third-party cookies, or telemetry beacons.
- **Client Storage**: User search history and past checks are stored strictly in the client browser's `localStorage`. No user history database exists on the server.
- **Transient Memory Cache**: The backend retains check results in server RAM for 2 hours strictly to enable follow-up chat sessions before garbage-collecting them.
- **Tight CSP Headers**: Strict Content-Security-Policy headers block unauthorized script injection, iframe embedding (`X-Frame-Options: DENY`), and MIME sniffing.

---

## Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork the repository** and create a descriptive feature branch (`git checkout -b feature/improved-ranking`).
2. **Follow TDD (Test-Driven Development)**: Write failing tests in `tests/` before introducing new logic.
3. **Verify all tests pass**:
   ```bash
   pytest -v
   ```
4. **Keep it simple**: Avoid bloated dependencies and unnecessary abstractions. Native Python standard libraries and clean functional code are preferred.
5. **Open a Pull Request** with a concise summary of the changes and test results.

---

## License

This project is open-source under the **[MIT License](LICENSE)**.
