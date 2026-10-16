"""Test dell'agente con un LLM finto (nessun modello reale richiesto)."""
import pytest

from app import config, db
from app.agent import Agent
from app.llm import normalize_message


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return normalize_message(self.script.pop(0))


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "agent.db")
    c = db.connect()
    db.init_db(c)
    c.close()


def test_tool_round_then_reply():
    llm = FakeLLM([
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_menu", "arguments": {"category": "Dolci"}}}]},
        {"role": "assistant", "content": "Abbiamo tiramisù, panna cotta e sorbetto."},
    ])
    agent = Agent(llm)
    out = agent.handle("sessione-test-1", "Che dolci avete?")
    assert out["reply"].startswith("Abbiamo") and out["actions"][0]["tool"] == "get_menu"
    tool_msg = llm.calls[1][-1]
    assert tool_msg["role"] == "tool" and "Tiramis" in tool_msg["content"]
    # la sessione ricorda il turno precedente
    llm.script.append({"role": "assistant", "content": "Prego!"})
    agent.handle("sessione-test-1", "Grazie")
    assert [m["role"] for m in llm.calls[-1][1:]] == ["user", "assistant", "tool", "assistant", "user"]


def test_text_tool_calls_are_recovered():
    m = normalize_message({"content": 'Verifico.<tool_call>{"name": "get_restaurant_info", "arguments": {}}</tool_call>'})
    assert m["tool_calls"][0]["function"]["name"] == "get_restaurant_info" and m["content"] == "Verifico."
    m = normalize_message({"content": "<function=get_menu>\n<parameter=category>\nPrimi\n</parameter>\n</function>"})
    assert m["tool_calls"][0]["function"] == {"name": "get_menu", "arguments": {"category": "Primi"}}


def test_leftover_markup_and_think_removed():
    m = normalize_message({"content": "<think>bla</think>Confermo alle 20:30?\n<tool_call>"})
    assert m["content"] == "Confermo alle 20:30?" and not m.get("tool_calls")


def test_loop_limit(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_TOOL_ROUNDS", 2)
    call = {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_restaurant_info", "arguments": {}}}]}
    out = Agent(FakeLLM([call, call])).handle("sessione-test-2", "info")
    assert "non sono riuscito" in out["reply"]
