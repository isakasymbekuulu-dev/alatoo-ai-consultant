"""Tests for the LangGraph dialog orchestration (routing + trace)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.graph as G


def _stub_build():
    # avoid Qdrant during tests
    G.build_messages = lambda history, riasec_summary=None: (
        [{"role": "system", "content": "x"}], [{"title": "t"}])


def test_router_general_on_greeting():
    _stub_build()
    _, _, intent, trace = G.run_graph([{"role": "user", "content": "привет"}])
    assert intent == "general"
    assert trace and trace[0].startswith("router")


def test_router_rag_on_question():
    _stub_build()
    _, _, intent, _ = G.run_graph(
        [{"role": "user", "content": "Какие документы нужны для поступления?"}])
    assert intent == "rag"


def test_router_riasec_when_profile_and_hint():
    _stub_build()
    _, _, intent, _ = G.run_graph(
        [{"role": "user", "content": "что значит мой результат теста?"}],
        riasec_summary="Код Голланда: SAE")
    assert intent == "riasec"


def test_router_rag_when_profile_but_unrelated():
    _stub_build()
    _, _, intent, _ = G.run_graph(
        [{"role": "user", "content": "сколько стоит обучение"}],
        riasec_summary="Код Голланда: SAE")
    assert intent == "rag"


def test_graph_spec_shape():
    assert {n["id"] for n in G.GRAPH_SPEC["nodes"]} == {"router", "rag", "riasec", "general"}
    assert any(e["to"] == "router" for e in G.GRAPH_SPEC["edges"])
