from __future__ import annotations

import os
import sys
import types

import pytest

# Provide a minimal fake `mcp.server.fastmcp` when the real package isn't installed
if "mcp" not in sys.modules:
    mcp_mod = types.ModuleType("mcp")
    server_pkg = types.ModuleType("mcp.server")
    fastmcp_mod = types.ModuleType("mcp.server.fastmcp")

    class FakeFastMCP:
        def __init__(self, name: str = "fake"):
            self._name = name

        def tool(self):
            def decorator(fn):
                return fn

            return decorator

        def run(self):
            return None

    fastmcp_mod.FastMCP = FakeFastMCP
    fastmcp_mod.ResponseError = RuntimeError
    server_pkg.fastmcp = fastmcp_mod
    mcp_mod.server = server_pkg
    sys.modules["mcp"] = mcp_mod
    sys.modules["mcp.server"] = server_pkg
    sys.modules["mcp.server.fastmcp"] = fastmcp_mod

import rlm_corpus_server as server
from corpus_manager import create_corpus


def _inject_fake_openai(monkeypatch=None):
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    class Resp:
                        choices = [type("C", (), {"message": type("M", (), {"content": "FAKE_SUMMARY"})})]

                    return Resp()

    fake = types.ModuleType("openai")
    fake.OpenAI = lambda api_key=None: FakeClient()
    sys.modules["openai"] = fake

@pytest.fixture(autouse=True)
def reset_state():
    server.corpora.clear()
    server.sessions.clear()
    yield
    server.corpora.clear()
    server.sessions.clear()
    if "openai" in sys.modules:
        del sys.modules["openai"]


def test_llm_query_with_mocked_openai(monkeypatch):
    # Prepare fake client
    _inject_fake_openai(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "testkey")

    # Load a tiny corpus
    corpus = server.load_corpus(name="Test", documents=[{"text": "alpha beta gamma"}])
    session_resp = server.open_session(corpus_id=corpus["corpus_id"], enable_llm_query=True)
    session_id = session_resp["session_id"]

    # Execute code that calls llm_query
    res = server.exec_repl(
        session_id=session_id,
        code="answer = llm_query('Explain this')",
        capture_variables=["answer"],
    )

    assert "answer" in res["exports"]
    assert "FAKE_SUMMARY" in res["exports"]["answer"]


def test_llm_query_error_is_handled(monkeypatch):
    # Inject an openai module that raises on call
    class BadClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    raise RuntimeError("boom")

    fake = type("m", (), {})()
    fake.OpenAI = lambda api_key=None: BadClient()
    sys.modules["openai"] = fake
    monkeypatch.setenv("OPENAI_API_KEY", "testkey")

    corpus = server.load_corpus(name="Test2", documents=[{"text": "x y z"}])
    session_resp = server.open_session(corpus_id=corpus["corpus_id"], enable_llm_query=True)
    session_id = session_resp["session_id"]

    res = server.exec_repl(
        session_id=session_id,
        code="answer = llm_query('Explain this')",
        capture_variables=["answer"],
    )

    assert "ERROR:" in res["exports"]["answer"]
