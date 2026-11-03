"""Offline tests: a fake Claude client drives the real agent loop, tools, policy and API."""
import asyncio
import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from app import config, main
from app.agent import Agent, parse_final
from app.memory import Memory
from app.tools import load_tools


class FakeClient:
    """Plays back scripted responses; records what the agent sent."""
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    async def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=str)))
        return self.script.pop(0)


def text(t):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=t)])


def use(name, args, uid="t1"):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=uid, name=name, input=args)])


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mem(tmp_path):
    return Memory(tmp_path / "t.db")


def test_tools_discovered():
    assert {"remember", "forget", "set_timer", "open_url", "open_on_computer", "play_youtube", "send_telegram"} <= set(load_tools())


def test_parse_final_variants():
    assert parse_final('{"reply":"Salom","emotion":"happy","lang":"uz"}')["emotion"] == "happy"
    assert parse_final('Mana:\n```json\n{"reply":"Hi","emotion":"love","lang":"en"}\n```')["reply"] == "Hi"
    p = parse_final("just text")
    assert p == {"reply": "just text", "emotion": "neutral", "gesture": "", "lang": "uz"}
    assert parse_final('{"reply":"x","emotion":"furious"}')["emotion"] == "neutral"


def test_plain_chat_saves_history(mem):
    a = Agent(mem, load_tools(), FakeClient([text('{"reply":"Salom!","emotion":"happy","lang":"uz"}')]))
    out = run(a.chat("salom"))
    assert out["reply"] == "Salom!" and out["actions"] == [] and out["pending"] == []
    assert [m["role"] for m in mem.recent_messages()] == ["user", "assistant"]


def test_remember_and_timer_run_without_confirmation(mem):
    fc = FakeClient([use("remember", {"fact": "CTF dars seshanba kuni"}),
                     use("set_timer", {"seconds": 300, "label": "choy"}, "t2"),
                     text('{"reply":"Eslab qoldim, taymer qoʻydim.","emotion":"happy","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).chat("eslab qol va taymer qoʻy"))
    assert mem.facts() == ["CTF dars seshanba kuni"]
    assert out["actions"] == [{"type": "timer", "seconds": 300, "label": "choy"}]
    # the remembered fact is in the system prompt of later calls
    fc2 = FakeClient([text('{"reply":"ok"}')])
    run(Agent(mem, load_tools(), fc2).chat("nima bor?"))
    assert "CTF dars seshanba kuni" in fc2.calls[0]["system"]


def test_youtube_fallback_when_search_fails(mem, monkeypatch):
    from app.tools import youtube_tool
    monkeypatch.setattr(youtube_tool, "_search", lambda q: (_ for _ in ()).throw(RuntimeError("offline")))
    fc = FakeClient([use("play_youtube", {"query": "Bevafo"}), text('{"reply":"Qidiruv ochildi"}')])
    out = run(Agent(mem, load_tools(), fc).chat("Bevafoni qoʻy"))
    assert out["actions"][0]["type"] == "open_url" and "Bevafo" in out["actions"][0]["url"]


def test_youtube_hit(mem, monkeypatch):
    from app.tools import youtube_tool
    monkeypatch.setattr(youtube_tool, "_search", lambda q: {"id": "abc123XYZ00", "title": "Song"})
    fc = FakeClient([use("play_youtube", {"query": "song"}), text('{"reply":"Qoʻydim"}')])
    out = run(Agent(mem, load_tools(), fc).chat("qoʻy"))
    assert out["actions"] == [{"type": "youtube", "id": "abc123XYZ00", "title": "Song", "url": "https://youtu.be/abc123XYZ00"}]


def _setup_telegram(monkeypatch):
    config.CONTACTS_FILE.write_text(json.dumps({"Ali": "@ali_test"}), encoding="utf-8")
    monkeypatch.setattr(config, "TELEGRAM_API_ID", 1)
    monkeypatch.setattr(config, "TELEGRAM_API_HASH", "h")
    monkeypatch.setattr(config, "TELEGRAM_SESSION", "s")


def test_telegram_needs_confirmation_then_sends(mem, monkeypatch):
    _setup_telegram(monkeypatch)
    from app.tools import telegram_tool
    sent = []

    async def fake_run(self, args, ctx):
        sent.append(args)
        return {"status": "sent"}
    monkeypatch.setattr(telegram_tool.SendTelegram, "run", fake_run)

    fc = FakeClient([use("send_telegram", {"recipient": "ali", "text": "Salom"}),
                     text('{"reply":"Aliga Salom yuboraymi? Ha ni bosing.","emotion":"neutral"}')])
    a = Agent(mem, load_tools(), fc)
    out = run(a.chat("aliga salom deb yoz"))
    assert sent == [] and len(out["pending"]) == 1
    assert "@ali_test" in out["pending"][0]["summary"]
    tool_result = json.loads(fc.calls[1]["messages"][-1]["content"][0]["content"])
    assert tool_result["status"] == "awaiting_user_confirmation"

    pid = out["pending"][0]["id"]
    assert run(a.confirm(pid, True))["status"] == "done"
    assert sent == [{"recipient": "ali", "text": "Salom"}]
    assert run(a.confirm(pid, True))["status"] == "not_found"  # cannot be replayed
    statuses = [r["status"] for r in mem.audit_log()]
    assert statuses[:2] == ["ok", "pending"]


def test_telegram_rejects_unknown_contact_without_queueing(mem, monkeypatch):
    _setup_telegram(monkeypatch)
    fc = FakeClient([use("send_telegram", {"recipient": "begona", "text": "hi"}), text('{"reply":"Bu kontakt roʻyxatda yoʻq"}')])
    out = run(Agent(mem, load_tools(), fc).chat("begonaga yoz"))
    assert out["pending"] == []
    res = fc.calls[1]["messages"][-1]["content"][0]
    assert res["is_error"] is True and "whitelist" in res["content"]


def test_decline(mem, monkeypatch):
    _setup_telegram(monkeypatch)
    fc = FakeClient([use("send_telegram", {"recipient": "ali", "text": "x"}), text('{"reply":"?"}')])
    a = Agent(mem, load_tools(), fc)
    pid = run(a.chat("yoz"))["pending"][0]["id"]
    assert run(a.confirm(pid, False))["status"] == "rejected"
    assert run(a.confirm(pid, True))["status"] == "not_found"


def test_autonomy_zero_confirms_open_url(mem, monkeypatch):
    monkeypatch.setattr(config, "AUTONOMY_LEVEL", 0)
    fc = FakeClient([use("open_url", {"url": "https://kun.uz"}), text('{"reply":"Tasdiqlang"}')])
    out = run(Agent(mem, load_tools(), fc).chat("kun.uz ni och"))
    assert out["actions"] == [] and out["pending"][0]["tool"] == "open_url"


def test_bad_url_and_injection_target_rejected(mem):
    fc = FakeClient([use("open_url", {"url": "javascript:alert(1)"}),
                     use("open_on_computer", {"target": "calc; rm -rf ~"}, "t2"),
                     text('{"reply":"Boʻlmaydi"}')])
    out = run(Agent(mem, load_tools(), fc).chat("x"))
    assert out["actions"] == []
    assert fc.calls[1]["messages"][-1]["content"][0]["is_error"] is True
    assert fc.calls[2]["messages"][-1]["content"][0]["is_error"] is True


def test_api_auth_and_flow(monkeypatch):
    c = TestClient(main.app)
    assert c.get("/api/health").json()["ok"] is True
    assert c.post("/api/chat", json={"text": "hi"}).status_code == 401
    assert c.post("/api/chat", json={"text": "hi"}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    main._agent = Agent(main.memory, main.tools, FakeClient([text('{"reply":"Hello","emotion":"happy","lang":"en"}')]))
    r = c.post("/api/chat", json={"text": "hi"}, headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200 and r.json()["reply"] == "Hello"
    assert c.get("/api/audit", headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_llm_error_detail_is_returned_and_key_masked(monkeypatch):
    class Boom:
        def __init__(self): self.messages = self
        async def create(self, **kw):
            e = RuntimeError("Your credit balance is too low (key sk-test)")
            e.status_code = 400
            raise e
    c = TestClient(main.app)
    main._agent = Agent(main.memory, main.tools, Boom())
    r = c.post("/api/chat", json={"text": "hi"}, headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 502
    assert "credit balance" in r.json()["detail"] and "sk-test" not in r.json()["detail"]


# ---------- OpenAI-compatible provider (Gemini / Groq / Ollama) ----------
import httpx as _httpx

from app.llm import LLMError, OpenAICompatLLM


def _oa_transport(responses, seen):
    def handler(request):
        seen.append(json.loads(request.content))
        status, body = responses.pop(0)
        return _httpx.Response(status, json=body)
    return _httpx.MockTransport(handler)


def test_openai_compat_tool_loop(mem):
    seen = []
    responses = [
        (200, {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "set_timer", "arguments": '{"seconds": 60, "label": "test"}'}}]}}]}),
        (200, {"choices": [{"message": {"content": '```json\n{"reply":"Taymer qoʻyildi","emotion":"happy","lang":"uz"}\n```'}}]}),
    ]
    llm = OpenAICompatLLM("https://example.test/v1", "k", "m-fast", transport=_oa_transport(responses, seen))
    out = run(Agent(mem, load_tools(), llm=llm).chat("1 daqiqaga taymer"))
    assert out["reply"] == "Taymer qoʻyildi" and out["actions"][0]["seconds"] == 60
    first, second = seen
    assert first["model"] == "m-fast" and first["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in first["tools"]} >= {"set_timer", "send_telegram"}
    assert second["messages"][-2]["tool_calls"][0]["function"]["name"] == "set_timer"
    assert second["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true, "seconds": 60}'}


def test_openai_compat_error_and_missing_ids(mem):
    seen = []
    llm = OpenAICompatLLM("https://example.test/v1", "k", "m", transport=_oa_transport(
        [(429, [{"error": {"code": 429, "message": "Resource has been exhausted"}}])], seen))
    with pytest.raises(LLMError) as e:
        run(llm.complete("s", [{"role": "user", "content": "hi"}], []))
    assert e.value.status_code == 429 and "exhausted" in e.value.message
    llm2 = OpenAICompatLLM("https://example.test/v1", "", "m", transport=_oa_transport(
        [(200, {"choices": [{"message": {"tool_calls": [{"function": {"name": "dance", "arguments": "not json"}}]}}]})], seen))
    step = run(llm2.complete("s", [{"role": "user", "content": "hi"}], []))
    assert step["tool_calls"][0]["id"].startswith("call_") and step["tool_calls"][0]["input"] == {}


def test_openai_compat_timeout_is_clear(monkeypatch):
    def handler(request):
        raise _httpx.ReadTimeout("slow", request=request)
    monkeypatch.setattr(config, "OPENAI_REASONING_EFFORT", "low")
    llm = OpenAICompatLLM("https://example.test/v1", "k", "m", transport=_httpx.MockTransport(handler))
    with pytest.raises(LLMError) as e:
        run(llm.complete("s", [{"role": "user", "content": "hi"}], []))
    assert e.value.status_code == 504 and "did not answer" in e.value.message


def test_openai_compat_falls_back_on_overload(monkeypatch):
    seen = []
    monkeypatch.setattr(config, "OPENAI_MODEL_FALLBACKS", ["backup-a", "backup-b"])
    llm = OpenAICompatLLM("https://example.test/v1", "k", "busy", transport=_oa_transport([
        (503, [{"error": {"code": 503, "message": "high demand"}}]),
        (429, {"error": {"message": "quota"}}),
        (200, {"choices": [{"message": {"content": "ok"}}]})], seen))
    step = run(llm.complete("s", [{"role": "user", "content": "hi"}], []))
    assert step["text"] == "ok" and [b["model"] for b in seen] == ["busy", "backup-a", "backup-b"]
    llm2 = OpenAICompatLLM("https://example.test/v1", "k", "m", transport=_oa_transport(
        [(400, {"error": {"message": "bad schema"}})], seen))
    with pytest.raises(LLMError):  # non-retryable errors are not hidden by fallbacks
        run(llm2.complete("s", [{"role": "user", "content": "hi"}], []))


# ---------- server TTS ----------
def test_tts_endpoint_and_cache(monkeypatch):
    import sys
    import types
    calls = []

    class FakeCommunicate:
        def __init__(self, text, voice, **kw):
            calls.append((text, voice, kw))

        async def stream(self):
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"ID3fake"}
    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))
    from app import tts
    tts._cache.clear()
    c = TestClient(main.app)
    h = {"Authorization": "Bearer test-token"}
    assert c.post("/api/tts", json={"text": "salom"}).status_code == 401
    r = c.post("/api/tts", json={"text": "Salom,   qalaysiz?", "lang": "uz"}, headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake"
    assert calls[0][1] == config.TTS_VOICE_UZ and calls[0][0] == "Salom, qalaysiz?"
    c.post("/api/tts", json={"text": "Salom, qalaysiz?", "lang": "uz"}, headers=h)
    assert len(calls) == 1  # second time served from cache
    c.post("/api/tts", json={"text": "Привет", "lang": "ru"}, headers=h)
    assert calls[-1][1] == config.TTS_VOICE_RU


def test_openai_compat_echoes_gemini_thought_signature(mem):
    seen = []
    sig = {"google": {"thought_signature": "SIG123"}}
    responses = [
        (200, {"choices": [{"message": {"role": "assistant", "tool_calls": [
            {"id": "c1", "type": "function", "extra_content": sig,
             "function": {"name": "set_timer", "arguments": '{"seconds": 30}'}}]}}]}),
        (200, {"choices": [{"message": {"content": '{"reply":"ok","emotion":"happy","lang":"uz"}'}}]}),
    ]
    llm = OpenAICompatLLM("https://example.test/v1", "k", "gemini-x", transport=_oa_transport(responses, seen))
    out = run(Agent(mem, load_tools(), llm=llm).chat("30 soniya"))
    assert out["reply"] == "ok"
    sent_call = seen[1]["messages"][-2]["tool_calls"][0]
    assert sent_call["extra_content"] == sig and sent_call["id"] == "c1"
    assert sent_call["function"]["name"] == "set_timer"


def test_new_emotions_accepted():
    for e in ("laughing", "shy", "wink", "proud", "scared", "bored"):
        assert parse_final('{"reply":"x","emotion":"%s"}' % e)["emotion"] == e



# ---------- dates, celebrations, gestures ----------
from datetime import date as _date

from app import events as ev


def test_gesture_parsing():
    assert parse_final('{"reply":"Salom","emotion":"happy","gesture":"wave"}')["gesture"] == "wave"
    assert parse_final('{"reply":"x","gesture":"backflip"}')["gesture"] == ""


def test_parse_date():
    assert ev.parse_date("05-15") == (None, 5, 15)
    assert ev.parse_date("1995-05-15") == (1995, 5, 15)
    assert ev.parse_date("02-29") == (None, 2, 29)
    for bad in ("13-01", "2025-02-30", "hello", ""):
        with pytest.raises(ValueError):
            ev.parse_date(bad)


def test_events_today_upcoming_and_holidays(mem):
    mem.add_event("birthday", "Mening tugʻilgan kunim", 5, 15, 1995, "user")
    mem.add_event("holiday", "Ramazon hayiti", 3, 10, 2027)
    today = ev.on_day(mem, _date(2026, 5, 15))
    assert today[0]["name"] == "Mening tugʻilgan kunim" and today[0]["age"] == 31
    assert [e["name"] for e in ev.on_day(mem, _date(2026, 3, 21))] == ["Navroʻz bayrami"]
    assert ev.on_day(mem, _date(2026, 3, 10)) == []           # one-time date only in its own year
    assert ev.on_day(mem, _date(2027, 3, 10))[0]["name"] == "Ramazon hayiti"
    soon = ev.upcoming(mem, _date(2026, 5, 10), days=7)
    assert soon[0]["in_days"] == 5 and soon[0]["date"] == "2026-05-15"


def test_save_event_and_celebrate_tools(mem):
    fc = FakeClient([use("save_event", {"name": "Alining tugʻilgan kuni", "date": "11-03", "kind": "birthday", "person": "Ali"}),
                     use("celebrate", {"style": "confetti"}, "t2"),
                     use("save_event", {"name": "x", "date": "31-12", "kind": "birthday"}, "t3"),
                     text('{"reply":"Saqladim!","emotion":"proud","gesture":"thumbs_up","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).chat("Alining tugʻilgan kuni 3-noyabr"))
    assert mem.events()[0]["name"] == "Alining tugʻilgan kuni"
    assert {"type": "celebrate", "style": "confetti"} in out["actions"]
    assert fc.calls[3]["messages"][-1]["content"][0]["is_error"] is True   # bad date rejected
    assert out["gesture"] == "thumbs_up" and out["emotion"] == "proud"
    assert "Coming in the next 7 days" in fc.calls[0]["system"]


def test_greet_today(mem, monkeypatch):
    a = Agent(mem, load_tools(), FakeClient([]))
    monkeypatch.setattr(ev, "on_day", lambda m, d=None: [])
    assert run(a.greet_today()) == {"events": []}            # nothing today -> no LLM call
    monkeypatch.setattr(ev, "on_day", lambda m, d=None: [{"kind": "birthday", "name": "Mening tugʻilgan kunim", "person": "user"}])
    fc = FakeClient([text('{"reply":"Tugʻilgan kuningiz bilan!","emotion":"excited","gesture":"clap","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).greet_today())
    assert out["reply"] == "Tugʻilgan kuningiz bilan!" and out["style"] == "fireworks" and out["gesture"] == "clap"
    assert "tools" not in fc.calls[0]                          # greeting call sends no tools
    rows = mem._exec("SELECT role, content FROM messages ORDER BY id DESC LIMIT 1").fetchall()
    assert tuple(rows[0]) == ("assistant", "Tugʻilgan kuningiz bilan!")   # kept for conversation context
