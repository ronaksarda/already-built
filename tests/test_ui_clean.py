from fastapi.testclient import TestClient

import server
from core import pipeline


def test_footer_removed():
    with TestClient(server.app) as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.text
        assert "<footer" not in html
        assert "MIT licensed." not in html


def test_pixelon_font_served():
    with TestClient(server.app) as client:
        res_otf = client.get("/static/fonts/Pixelon.otf")
        assert res_otf.status_code == 200
        assert res_otf.headers.get("content-type") == "font/otf"
        assert len(res_otf.content) > 1000

        res_ttf = client.get("/static/fonts/Pixelon.ttf")
        assert res_ttf.status_code == 200
        assert res_ttf.headers.get("content-type") == "font/ttf"
        assert len(res_ttf.content) > 1000


def test_css_pixelon_headings():
    with TestClient(server.app) as client:
        res = client.get("/static/style.css")
        assert res.status_code == 200
        css = res.text
        assert "@font-face" in css
        assert "Pixelon" in css
        assert "--pixel:" in css and "Pixelon" in css


def test_pipeline_stages_no_model_buzzwords():
    for stage_id, label in pipeline.STAGES:
        assert "Gemma" not in label
        assert "model" not in label.lower()


def test_clean_prompt_and_chat_boxes():
    with TestClient(server.app) as client:
        res = client.get("/")
        assert res.status_code == 200
        html = res.text
        # Clean composer and chat-form without gradient blobs
        assert 'class="composer"' in html
        assert 'class="chat-form"' in html
        assert "pc-backdrop" not in html
        assert "pc-rim-blobs" not in html
        # Functionality intact - required IDs present
        for required_id in [
            "idea", "micBtn", "micLabel", "shot", "shotLabel", "shotClear",
            "sttLang", "count", "checkBtn", "hint", "demoBtn",
            "chatInput", "chatMic", "chatSend", "mapBlock", "map", "mapLegend"
        ]:
            assert f'id="{required_id}"' in html, f"Missing id: {required_id}"
        assert "Direct rivals (P1–P10)" in html
        assert "Closest projects (P1–P10)" in html


def test_github_repo_url_detection():
    from core.guard import check_idea, github_repo_from_url
    assert github_repo_from_url("github.com/psf/requests") == ("psf", "requests")
    assert github_repo_from_url("https://github.com/psf/requests/") == ("psf", "requests")
    chk = check_idea("github.com/psf/requests")
    assert chk.ok
    assert chk.kind == "url"
    assert chk.url == "https://github.com/psf/requests"


def test_vague_input_rejected():
    from core.guard import check_idea
    chk = check_idea("nice nice nice very nice")
    assert not chk.ok
    assert chk.kind == "vague"

    chk2 = check_idea("cool app cool app cool app")
    assert not chk2.ok
    assert chk2.kind == "vague"


def test_negative_differentiators_dropped():
    from core import report
    from core.sources import Candidate
    c1 = Candidate(id="github:a/one", source="github", name="a/one", url="https://github.com/a/one", score=0.6)
    c2 = Candidate(id="github:b/two", source="github", name="b/two", url="https://github.com/b/two", score=0.5)
    _, idmap = report.project_block([c1, c2])
    out = report.validate_report({
        "differs": [
            {"text": "does not use AI-driven clustering", "cites": ["P1"]},
            {"text": "doesn't rely on invite-only growth", "cites": ["P2"]},
            {"text": "focuses exclusively on retro gaming cartridges", "cites": ["P1"]},
        ],
        "next_step": "test it",
    }, idmap)
    assert len(out["differs"]) == 1
    assert out["differs"][0]["text"] == "focuses exclusively on retro gaming cartridges"


def test_trivial_joke_ideas_rejected():
    from core.guard import check_idea
    for text in [
        "Wassup a website which says waassup",
        "a website which says hello",
        "website that just says hello world",
        "an app that displays hi",
        "WHO LET THE DOGS OUT",
        "who let the dogs out",
        "why is the sky blue",
        "what is love",
    ]:
        chk = check_idea(text)
        assert not chk.ok, f"Expected {text} to be rejected"
        assert chk.kind in ("vague", "short"), f"Expected vague or short for {text}, got {chk.kind}"


def test_verdict_no_glazing():
    from core import rank
    from core.sources import Candidate
    v_empty = rank.verdict([])
    assert "good news" not in v_empty["text"].lower()
    assert "looks open" not in v_empty["text"].lower()

    cand = Candidate(id="github:test/repo", source="github", name="test/repo", url="https://github.com/test/repo", score=0.4)
    v_loose = rank.verdict([cand])
    assert "your angle is the product" not in v_loose["text"].lower()


def test_rules_report_no_glazing():
    from core import report
    rep = report.rules_report([])
    for item in rep["gaps"]:
        assert "unclaimed" not in item["text"].lower()
        assert "good news" not in item["text"].lower()


def test_frontend_no_fake_ownership_labels():
    app_js = (server.WEB / "app.js").read_text(encoding="utf-8")
    assert "Gaps you can own" not in app_js
    assert "How yours differs" not in app_js


def test_gitspace_distinct_keyword_search():
    from core.guard import fallback_queries
    from core.sources import search_github
    idea = "Your GitHub repositories are a world. Every repo is a building. Every developer is an island."
    qs = fallback_queries(idea)
    assert any("island" in q and "github" in q for q in qs), f"Expected 'island' and 'github' in queries, got {qs}"
    # Verify that the direct keyword query finds ronaksarda/GitSpace
    cands = search_github(qs[0], use_cache=True)
    names = [c.name.lower() for c in cands]
    assert "ronaksarda/gitspace" in names, f"Expected ronaksarda/GitSpace in results, got {names}"

