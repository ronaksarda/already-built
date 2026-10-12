"""Input checks that run before any API call.

Every check here is cheap and local. The goal is to stop bad input early,
so we never burn GitHub or Gemini quota on an empty box or a one-word idea.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

MIN_CHARS = 20
MIN_WORDS = 4
MAX_CHARS = 1200
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_SIDE = 8000
ALLOWED_IMAGE_FORMATS = {"PNG", "JPEG", "WEBP"}

URL_RE = re.compile(r"^\s*(https?://\S+)\s*$", re.IGNORECASE)
GITHUB_REPO_RE = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)", re.IGNORECASE)

# Words that carry no product meaning on their own. An idea made only of
# these ("an ai app for people") is too vague to search.
FILLER_WORDS = {
    "a", "an", "the", "app", "application", "website", "site", "tool", "platform",
    "thing", "things", "something", "project", "idea", "ai", "ml", "using", "with", "for",
    "that", "which", "is", "it", "my", "make", "build", "create", "want", "to",
    "i", "we", "of", "and", "or", "in", "on", "web", "mobile", "simple", "cool",
    "new", "good", "best", "people", "users", "user", "everyone", "some", "like",
    "based", "powered", "smart", "system", "software", "program", "bot", "do",
    "nice", "very", "great", "awesome", "fine", "bad", "okay", "ok", "test", "testing",
    "stuff", "yeah", "yes", "no", "hello", "world", "really",
    "wassup", "waassup", "whassup", "wazzup", "whatsup", "wasup", "sup",
    "hey", "hi", "says", "say", "said", "shows", "show", "displays", "display",
    "plays", "play", "clicks", "click", "just", "only", "simply", "where", "how", "what",
    "who", "whom", "whose", "when", "why", "let", "lets", "out", "into", "from",
    "about", "by", "at", "up", "down", "off", "over", "under", "get", "gets", "got",
    "give", "gives", "take", "takes", "put", "puts", "go", "goes", "went", "come",
    "comes", "came", "see", "saw", "know", "knows", "think", "thinks", "look", "looks",
}

QUESTION_RE = re.compile(
    r"^(?:who|why|when|where|what|how(?:\s+come)?)\s+[^.?!\n]{2,120}\??$",
    re.IGNORECASE,
)
PRODUCT_WORDS = re.compile(
    r"\b(?:app|application|website|site|platform|tool|software|system|extension|plugin|bot|cli|api|service|dashboard|tracker|generator|manager|engine|client)\b",
    re.IGNORECASE,
)

# Short list of clearly harmful intents. Gemma does a second, smarter check;
# this list only catches the obvious cases without spending an API call.
HARM_PATTERNS = [
    r"\bransomware\b", r"\bkeylogger\b", r"\bsteal(?:ing)?\s+(?:passwords?|credentials|cards?)\b",
    r"\bcredential\s+stuff", r"\bddos\b", r"\bbotnet\b", r"\bphishing\s+kit\b",
    r"\bstalk(?:er|ing)?\b", r"\bdoxx?(?:ing)?\b", r"\bchild\s+(?:porn|sexual)", r"\bcsam\b",
    r"\bbomb[- ]making\b", r"\bbioweapon", r"\bnerve\s+agent", r"\bcard\s+skimm",
    r"\bbypass(?:ing)?\s+(?:paywall|drm|2fa|captcha)", r"\bspyware\b", r"\bdeepfake\s+porn",
]

# Violence and self-harm. Checked separately because the defensive side of these
# (prevention, first aid, warnings) is a legitimate project and must pass.
VIOLENCE_PATTERNS = [
    r"\b(?:kill|murder|poison|harm|hurt|injur|maim|assault|tortur|shoot|stab|attack|endanger|suffocat|drown)\w*\b"
    r".{0,40}\b(?:people|persons?|someone|somebody|humans?|users?|kids?|child(?:ren)?|students?|anyone|everyone|him|her|them|others|customers?|visitors?|victims?)\b",
    r"\b(?:people|persons?|someone|humans?|users?|kids?|child(?:ren)?|anyone|everyone|customers?|visitors?)\b.{0,25}\b(?:die|dies|dying|dead|killed|get hurt|gets hurt|injured)\b",
    r"\b(?:can|could|will|would|might|may)\s+(?:potentially\s+)?(?:kill|murder|poison|maim)\b",
    r"\b(?:make|making|build|building|3d[- ]?print\w*|assembl\w*|craft\w*)\b.{0,30}\b(?:weapons?|explosives?|bombs?|guns?|firearms?|poisons?)\b",
    r"\b(?:suicide|self[- ]?harm|kill\s+(?:myself|yourself|themselves))\b",
]
DEFENSIVE_WORDS = re.compile(
    r"\b(?:prevent\w*|detect\w*|protect\w*|warn\w*|alert\w*|report\w*|safety|safe|awareness|helpline|hotline|support|rescue|"
    r"first[- ]aid|emergency|avoid\w*|reduc\w*|stop\w*|recogni[sz]\w*|crisis|counsel\w*)\b",
    re.IGNORECASE,
)
HARM_MESSAGE = (
    "This tool won't help with projects meant to hurt people or break the law, even as a joke. "
    "If you meant the safety side (preventing, detecting or warning about harm), say that in the idea."
)


def is_harmful(text: str) -> bool:
    if any(re.search(p, text, re.IGNORECASE) for p in HARM_PATTERNS):
        return True
    if any(re.search(p, text, re.IGNORECASE) for p in VIOLENCE_PATTERNS):
        return not DEFENSIVE_WORDS.search(text)
    return False


ENGLISH_HINTS = {"the", "a", "an", "and", "for", "to", "that", "with", "of", "in", "app", "tool", "who", "which", "is", "on", "it", "my", "their", "students", "users", "into", "from", "helps", "lets"}


def _looks_non_english(text: str) -> bool:
    """Latin-script but not English (French, Spanish, Hinglish...): few common English words."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 5:
        return False
    return sum(w in ENGLISH_HINTS for w in words) / len(words) < 0.08


@dataclass
class IdeaCheck:
    ok: bool
    kind: str  # ok | empty | short | long | vague | harmful | url
    message: str = ""
    url: str | None = None
    warnings: list[str] = field(default_factory=list)


TRIVIAL_PATTERNS = [
    r"^(?:a\s+)?(?:website|site|app|tool|page|program|bot)\s+(?:that|which)?\s*(?:just\s+|only\s+)?(?:says|displays|shows|plays|speaks|prints|tells|outputs)\s+[\w\s]{1,30}$",
    r"^[\w\s]{1,20}\s+(?:a\s+)?(?:website|site|app|tool|page)\s+(?:that|which)?\s*(?:just\s+|only\s+)?(?:says|displays|shows|plays|speaks|prints|tells|outputs)\s+[\w\s]{1,30}$",
]


def _normalize_word(w: str) -> str:
    # Collapse consecutive duplicate letters: "waassup" -> "wasup", "heeeey" -> "hey"
    return re.sub(r"([a-z])\1+", r"\1", w.lower())


def _content_words(text: str) -> list[str]:
    words = re.findall(r"[^\W\d_]+", text.lower(), flags=re.UNICODE)
    return [w for w in words if w not in FILLER_WORDS and _normalize_word(w) not in FILLER_WORDS and len(w) > 2]


def non_latin_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if ord(c) > 0x024F) / len(letters)


def check_idea(text: str) -> IdeaCheck:
    """Classify raw idea text. Only `ok` and `url` results may reach the APIs."""
    raw = (text or "").strip()
    if not raw:
        return IdeaCheck(False, "empty", "Type your idea first. One to three sentences is enough.")
    if len(raw) > MAX_CHARS:
        return IdeaCheck(False, "long", f"Keep it under {MAX_CHARS} characters. Cut it to the core claim: who it helps and what it does.")

    gh_match = GITHUB_REPO_RE.search(raw)
    if gh_match and (URL_RE.match(raw) or len(raw.split()) <= 6):
        owner, repo = gh_match.group(1), gh_match.group(2)
        repo = repo.removesuffix(".git").rstrip("/")
        if owner.lower() not in {"orgs", "topics", "features", "collections", "trending", "explore", "settings"}:
            return IdeaCheck(True, "url", url=f"https://github.com/{owner}/{repo}")

    url_match = URL_RE.match(raw)
    if url_match:
        return IdeaCheck(True, "url", url=url_match.group(1))

    if is_harmful(raw):
        return IdeaCheck(False, "harmful", HARM_MESSAGE)

    if any(re.search(pat, raw, re.IGNORECASE) for pat in TRIVIAL_PATTERNS):
        return IdeaCheck(
            False, "vague",
            "That's too trivial or vague. What practical problem does it solve, and for whom? "
            "Example: \"An app that turns lecture slides into flashcards for medical students.\"",
        )

    if QUESTION_RE.match(raw) and not PRODUCT_WORDS.search(raw):
        return IdeaCheck(
            False, "vague",
            "That looks like a question or phrase, not a project idea. What specific tool or app do you want to build? "
            "Example: \"A dog tracking app for pet owners.\"",
        )

    words = re.findall(r"[^\W\d_]+", raw.lower(), flags=re.UNICODE)
    words_norm = [_normalize_word(w) for w in words]
    unique_norm = set(words_norm)
    latin = non_latin_ratio(raw) < 0.3
    # Character and word minimums only make sense for space-separated scripts.
    if latin and (len(raw) < MIN_CHARS or len(words) < MIN_WORDS):
        return IdeaCheck(
            False, "short",
            "Add a bit more. Who is it for, and what does it do that they can't do today?",
        )

    content_words = _content_words(raw)
    unique_content = set(_normalize_word(w) for w in content_words)

    if latin and (len(unique_norm) < 4 or len(unique_content) < 3):
        return IdeaCheck(
            False, "vague",
            "That's too vague, trivial, or repetitive. What specific problem does it solve, and for whom? "
            "Example: \"An app that turns lecture slides into flashcards for medical students.\"",
        )

    warnings = []
    if not latin or _looks_non_english(raw):
        warnings.append("Your idea is not in English. Gemma reads it fine, but GitHub search works best in English, so results may be weaker.")
    return IdeaCheck(True, "ok", warnings=warnings)


@dataclass
class ImageCheck:
    ok: bool
    message: str = ""
    data: bytes | None = None
    mime: str | None = None


def check_image(data: bytes | None) -> ImageCheck:
    """Validate a rival screenshot. A bad image never blocks the text flow."""
    if not data:
        return ImageCheck(False)
    if len(data) > MAX_IMAGE_BYTES:
        return ImageCheck(False, "Couldn't read this screenshot: it is over 5 MB. Continuing with text only.")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
    except Exception:
        return ImageCheck(False, "Couldn't read this file as an image. Continuing with text only.")
    if fmt not in ALLOWED_IMAGE_FORMATS:
        return ImageCheck(False, f"Couldn't read this screenshot ({fmt or 'unknown'} format). Use PNG, JPEG or WebP. Continuing with text only.")
    if w < 32 or h < 32 or max(w, h) > MAX_IMAGE_SIDE:
        return ImageCheck(False, "Couldn't read this screenshot: the size is out of range. Continuing with text only.")
    mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]
    return ImageCheck(True, data=data, mime=mime)


def github_repo_from_url(url: str) -> tuple[str, str] | None:
    m = GITHUB_REPO_RE.search(url or "")
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    repo = repo.removesuffix(".git").rstrip("/")
    if owner.lower() in {"orgs", "topics", "features", "collections", "trending", "explore", "settings"}:
        return None
    return owner, repo


STOPWORDS_FOR_QUERY = FILLER_WORDS | {
    "who", "what", "they", "them", "their", "can", "will", "would", "help", "helps", "your", "yours", "you",
    "from", "into", "this", "that", "these", "those", "there", "here", "where", "everywhere",
    "turns", "turn", "lets", "let", "makes", "gives", "uses", "allows", "finds", "shows", "tells", "takes", "gets",
    "are", "is", "was", "were", "am", "be", "been", "being", "has", "have", "had",
    "every", "each", "all", "any", "some", "many", "much", "more", "most", "both",
    "my", "mine", "our", "ours", "their", "theirs", "his", "her", "hers", "its",
    "without", "about", "above", "after", "before", "during", "and", "or", "but", "if", "while", "because",
    "as", "until", "unless", "so", "than", "too", "very", "shall", "should", "may", "might", "must",
}


def fallback_queries(text: str, n: int = 4) -> list[str]:
    """Build focused search queries from raw text using distinct keywords."""
    words = [w for w in re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE) if w not in STOPWORDS_FOR_QUERY and len(w) > 2]
    seen: list[str] = []
    for w in words:
        if w not in seen:
            seen.append(w)
    if not seen:
        return [text.strip()[:80]]
    if len(seen) <= 3:
        return [" ".join(seen)]

    queries: list[str] = []
    anchor = "github" if ("github" in seen or "git" in seen) else ""
    non_anchor = [w for w in seen if w not in {"github", "git"}]

    if anchor and len(non_anchor) >= 2:
        queries.append(f"{anchor} {non_anchor[-2]} {non_anchor[-1]}")
        if len(non_anchor) >= 3:
            queries.append(f"{anchor} {non_anchor[0]} {non_anchor[-1]}")
            queries.append(" ".join(non_anchor[-3:]))
        else:
            queries.append(f"{anchor} {non_anchor[0]}")
    else:
        queries.append(" ".join(seen[:3]))
        if len(seen) >= 4:
            queries.append(" ".join(seen[-3:]))
        if len(seen) >= 5:
            queries.append(f"{seen[0]} {seen[-2]} {seen[-1]}")

    first_chunk = " ".join(seen[:4])
    if first_chunk not in queries:
        queries.append(first_chunk)

    out: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q not in out:
            out.append(q)
    return out[:n]


NAME_RE = re.compile(
    r"""\b(?i:called|named|name\s+is|calling\s+it|brand(?:ed)?\s+as)\s+(?i:it\s+)?["'“‘]?([A-Za-z0-9][\w.+\-]*(?:\s+[A-Z0-9][\w.+\-]*){0,2})"""
)


def project_name_from_text(text: str) -> str:
    """A project name the user stated outright ("an app called Foo"). Never guessed."""
    m = NAME_RE.search(text or "")
    if not m:
        return ""
    name = m.group(1).strip(" .,;:!?\"'”’")
    return "" if name.lower() in FILLER_WORDS or len(name) < 2 else name[:40]


def title_from_text(text: str, words: int = 6) -> str:
    """Plain fallback title: the first words of the idea, without leading filler."""
    ws = re.findall(r"[\w'+.-]+", text or "")
    while ws and ws[0].lower() in {"a", "an", "the", "i", "we", "my", "want", "to", "build", "make", "create"}:
        ws.pop(0)
    t = " ".join(ws[:words])
    return (t[:1].upper() + t[1:] + ("…" if len(ws) > words else "")) if t else "Untitled check"
