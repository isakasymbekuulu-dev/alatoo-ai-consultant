"""Tests for the RIASEC test module and API.

Run:  pytest tests/test_riasec.py -v
(LLM/Qdrant are not required: scoring is pure Python, API tests stub the RAG call.)
"""
import os
import sys
from collections import Counter

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("LOG_DB", "/tmp/alatoo-test-logs/chat.db")

from app import riasec  # noqa: E402


# ---------------------------------------------------------------- module ---
def test_item_bank():
    assert len(riasec.ITEMS) == 60
    assert Counter(it["type"] for it in riasec.ITEMS) == {t: 10 for t in "RIASEC"}
    assert len({it["id"] for it in riasec.ITEMS}) == 60
    for it in riasec.ITEMS:  # all three languages present
        assert it["ru"] and it["ky"] and it["en"]
    assert len(riasec.PRESENTATION) == 60


def _answers(weights):
    return {it["id"]: weights[it["type"]] for it in riasec.ITEMS}


def test_scoring_profile():
    r = riasec.score(_answers({"A": 5, "S": 4, "I": 3, "E": 2, "R": 1, "C": 1}))
    assert r["code"] == "ASI"
    assert r["scores"]["A"] == 50 and r["percents"]["A"] == 100
    assert r["scores"]["R"] == 10 and r["percents"]["R"] == 0


def test_tie_break_canonical_order():
    r = riasec.score({it["id"]: 3 for it in riasec.ITEMS})
    assert r["code"] == "RIA"


def test_validation():
    with pytest.raises(ValueError):
        riasec.score({it["id"]: 3 for it in riasec.ITEMS[:59]})
    bad = {it["id"]: 3 for it in riasec.ITEMS}
    bad["R1"] = 9
    with pytest.raises(ValueError):
        riasec.score(bad)


def test_recommendations_match_profile():
    r = riasec.score(_answers({"A": 5, "S": 4, "I": 3, "E": 2, "R": 1, "C": 1}))
    recs = riasec.recommend(r["scores"])
    assert len(recs) == 6
    assert recs[0]["code"][0] in "AS"          # humanities/social on top
    assert recs == sorted(recs, key=lambda x: -x["match"])

    r2 = riasec.score(_answers({"I": 5, "R": 4, "C": 4, "A": 1, "S": 1, "E": 2}))
    top = riasec.recommend(r2["scores"])[0]
    assert top["code"].startswith("I")          # engineering/CS on top


def test_summary_for_llm():
    r = riasec.score(_answers({"I": 5, "C": 4, "R": 3, "A": 2, "S": 3, "E": 4}))
    r["recommendations"] = riasec.recommend(r["scores"])
    s = riasec.summary_for_llm(r)
    assert "Код Голланда" in s and r["code"] in s
    assert "Рекомендованные программы" in s


# ------------------------------------------------------------------- API ---
@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    import app.main as m
    # Stub out retrieval/LLM so no Qdrant or GitHub Models needed.
    monkeypatch.setattr(m, "build_messages",
                        lambda h, riasec_summary=None: ([{"role": "system", "content": "x"}], []))
    monkeypatch.setattr(m, "chat", lambda msgs, temperature=0.2: "ok")
    return TestClient(m.app)


def test_api_questions_three_langs(client):
    for lang in ("ru", "ky", "en"):
        data = client.get(f"/riasec/api/questions?lang={lang}").json()
        assert len(data["questions"]) == 60


def test_api_submit_and_result_roundtrip(client):
    ans = _answers({"I": 5, "C": 4, "R": 3, "A": 2, "S": 3, "E": 4})
    res = client.post("/riasec/api/submit",
                      json={"answers": ans, "lang": "ru", "chat_id": "chat-t1", "consent": True})
    assert res.status_code == 200
    body = res.json()
    assert body["session_id"] == "chat-t1"
    assert len(body["recommendations"]) == 6

    got = client.get(f"/riasec/api/result?id={body['result_id']}&lang=en")
    assert got.status_code == 200
    assert got.json()["types"]["I"]["name"] == "Investigative"

    # test turn is visible in the same session log
    from app import logging_store
    msgs = logging_store.session_messages("chat-t1")
    assert any(x["source"] == "riasec-test" for x in msgs)


def test_api_submit_incomplete_422(client):
    ans = _answers({"I": 5, "C": 4, "R": 3, "A": 2, "S": 3, "E": 4})
    partial = dict(list(ans.items())[:30])
    assert client.post("/riasec/api/submit",
                       json={"answers": partial, "lang": "ru", "consent": True}).status_code == 422


def test_api_result_not_found(client):
    assert client.get("/riasec/api/result?id=nope").status_code == 404
