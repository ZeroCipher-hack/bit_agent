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


# ---------- images (camera / screenshot) ----------
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_image_goes_to_anthropic_and_is_not_stored(mem):
    fc = FakeClient([text('{"reply":"Bu kichkina rasm","emotion":"surprised","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).chat("bu nima?", image={"media_type": "image/png", "data": PNG}))
    assert out["reply"] == "Bu kichkina rasm"
    content = fc.calls[0]["messages"][-1]["content"]
    assert content[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG}}
    assert content[1] == {"type": "text", "text": "bu nima?"}
    stored = mem.recent_messages()[0]["content"]
    assert stored == "bu nima? [rasm biriktirilgan]" and PNG not in stored


def test_image_goes_to_openai_compat_as_data_url(mem):
    seen = []
    llm = OpenAICompatLLM("https://example.test/v1", "k", "m", transport=_oa_transport(
        [(200, {"choices": [{"message": {"content": '{"reply":"Ekranda terminal","emotion":"neutral"}'}}]})], seen))
    out = run(Agent(mem, load_tools(), llm=llm).chat("ekranimda nima bor?", image={"media_type": "image/png", "data": PNG}))
    part = seen[0]["messages"][-1]["content"][0]
    assert out["reply"] == "Ekranda terminal" and part["image_url"]["url"].startswith("data:image/png;base64,iVBOR")


def test_api_image_validation():
    c = TestClient(main.app)
    h = {"Authorization": "Bearer test-token"}
    main._agent = Agent(main.memory, main.tools, FakeClient([text('{"reply":"ok"}')]))
    assert c.post("/api/chat", json={"text": "x", "image": "data:text/html;base64,PHNjcmlwdD4="}, headers=h).status_code == 400
    assert c.post("/api/chat", json={"text": "x", "image": "data:image/png;base64," + PNG}, headers=h).status_code == 200


# ---------- reminders, weather, quiz, pomodoro, smart home ----------
import time as _time
from datetime import datetime as _dt, timedelta as _td


def test_reminder_flow(mem):
    when = (_dt.now() + _td(minutes=10)).strftime("%Y-%m-%d %H:%M")
    fc = FakeClient([use("set_reminder", {"when": when, "text": "Darsga tayyorlan"}),
                     use("set_reminder", {"when": "2020-01-01 08:00", "text": "eski"}, "t2"),
                     text('{"reply":"Eslataman!","emotion":"happy"}')])
    out = run(Agent(mem, load_tools(), fc).chat("10 daqiqadan keyin eslat"))
    assert [r["text"] for r in mem.reminders()] == ["Darsga tayyorlan"]
    assert {"type": "notify_permission"} in out["actions"]
    assert "past" in fc.calls[2]["messages"][-1]["content"][0]["content"]
    assert mem.take_due_for_app(_time.time()) == []                       # not yet due
    due = mem.take_due_for_app(_time.time() + 3600)
    assert [r["text"] for r in due] == ["Darsga tayyorlan"]
    assert mem.take_due_for_app(_time.time() + 3600) == []                # handed out once


def test_reminders_go_to_telegram_saved_messages(monkeypatch):
    main.memory.add_reminder(_time.time() - 5, "Telegramga ham")
    monkeypatch.setattr(config, "TELEGRAM_SESSION", "s"); monkeypatch.setattr(config, "TELEGRAM_API_ID", 1)
    got = []

    async def sender(t):
        got.append(t)
    assert run(main.deliver_reminders_once(sender)) >= 1 and "⏰ Bit: Telegramga ham" in got
    got.clear()
    run(main.deliver_reminders_once(sender))
    assert "⏰ Bit: Telegramga ham" not in got                              # not sent twice


def test_weather_tool(mem, monkeypatch):
    from app.tools import weather_tool

    def handler(req):
        if "geocoding" in req.url.host:
            assert req.url.params["name"] == "Tashkent"
            return _httpx.Response(200, json={"results": [{"name": "Tashkent", "country": "Uzbekistan", "latitude": 41.3, "longitude": 69.2}]})
        return _httpx.Response(200, json={
            "current": {"temperature_2m": 12.5, "apparent_temperature": 10.1, "relative_humidity_2m": 40, "weather_code": 2, "wind_speed_10m": 9},
            "daily": {"time": ["2026-11-03"], "temperature_2m_max": [15], "temperature_2m_min": [5],
                      "precipitation_probability_max": [10], "weather_code": [61]}})
    monkeypatch.setattr(weather_tool, "TRANSPORT", _httpx.MockTransport(handler))
    res = run(weather_tool.GetWeather().run({}, None))
    assert res["place"] == "Tashkent, Uzbekistan" and res["now"]["sky"] == "partly cloudy" and res["days"][0]["sky"] == "light rain"


def test_quiz_flow(mem):
    fc = FakeClient([use("quiz_start", {"topic": "Linux", "total": 2, "level": "kids"}), text('{"reply":"1-savol: ls nima qiladi? A) ... "}')])
    out = run(Agent(mem, load_tools(), fc).chat("Linux boʻyicha viktorina"))
    assert out["quiz"]["total"] == 2 and out["quiz"]["asked"] == 0
    fc2 = FakeClient([use("quiz_answer", {"correct": True}), text('{"reply":"Toʻgʻri! 2-savol..."}')])
    out2 = run(Agent(mem, load_tools(), fc2).chat("A"))
    assert out2["quiz"]["correct"] == 1 and "QUIZ RUNNING" in fc2.calls[0]["system"]
    fc3 = FakeClient([use("quiz_answer", {"correct": False}), use("quiz_end", {}, "t2"), text('{"reply":"1/2","emotion":"proud"}')])
    out3 = run(Agent(mem, load_tools(), fc3).chat("B"))
    assert out3["quiz"] is None
    ended = json.loads(fc3.calls[2]["messages"][-1]["content"][0]["content"])
    assert ended["correct"] == 1 and ended["asked"] == 2 and ended["ended"] is True


def test_pomodoro_action(mem):
    fc = FakeClient([use("pomodoro", {"work_min": 25, "break_min": 5, "cycles": 2}), text('{"reply":"Boshladik!"}')])
    out = run(Agent(mem, load_tools(), fc).chat("pomodoro"))
    assert out["actions"] == [{"type": "pomodoro", "work_min": 25, "break_min": 5, "cycles": 2}]


def _ha_setup(monkeypatch, calls):
    from app.tools import home_tools
    monkeypatch.setattr(config, "HA_URL", "http://ha.test:8123"); monkeypatch.setattr(config, "HA_TOKEN", "tok")
    config.DEVICES_FILE.write_text(json.dumps({"konditsioner": "climate.zal", "eshik": "lock.front"}), encoding="utf-8")
    states = [{"entity_id": "climate.zal", "state": "cool", "attributes": {"friendly_name": "Zal konditsioner", "temperature": 22}},
              {"entity_id": "number.fridge_temp", "state": "4", "attributes": {"friendly_name": "Muzlatgich harorati"}},
              {"entity_id": "lock.front", "state": "locked", "attributes": {"friendly_name": "Old eshik"}},
              {"entity_id": "sensor.cpu", "state": "3", "attributes": {"friendly_name": "CPU"}}]

    def handler(req):
        assert req.headers["authorization"] == "Bearer tok"
        if req.method == "GET":
            return _httpx.Response(200, json=states)
        calls.append((req.url.path, json.loads(req.content)))
        return _httpx.Response(200, json=[])
    monkeypatch.setattr(home_tools, "TRANSPORT", _httpx.MockTransport(handler))


def test_smart_home_control(mem, monkeypatch):
    calls = []
    _ha_setup(monkeypatch, calls)
    fc = FakeClient([use("home_control", {"device": "konditsioner", "action": "turn_off"}),
                     use("home_control", {"device": "muzlatgich", "action": "set_temperature", "value": 3}, "t2"),
                     text('{"reply":"Konditsionerni oʻchirdim, muzlatgichni 3 gradusga qoʻydim.","emotion":"proud"}')])
    out = run(Agent(mem, load_tools(), fc).chat("konditsionerni oʻchir, muzlatgichni 3 ga tushir"))
    assert calls == [("/api/services/climate/turn_off", {"entity_id": "climate.zal"}),
                     ("/api/services/number/set_value", {"entity_id": "number.fridge_temp", "value": 3.0})]
    assert out["pending"] == []


def test_smart_home_lock_needs_confirmation(mem, monkeypatch):
    calls = []
    _ha_setup(monkeypatch, calls)
    fc = FakeClient([use("home_control", {"device": "eshik", "action": "unlock"}), text('{"reply":"Tasdiqlang"}')])
    a = Agent(mem, load_tools(), fc)
    out = run(a.chat("eshikni och"))
    assert calls == [] and out["pending"][0]["tool"] == "home_control"
    assert run(a.confirm(out["pending"][0]["id"], True))["status"] == "done"
    assert calls == [("/api/services/lock/unlock", {"entity_id": "lock.front"})]


def test_smart_home_not_configured(mem, monkeypatch):
    monkeypatch.setattr(config, "HA_URL", "")
    fc = FakeClient([use("home_control", {"device": "chiroq", "action": "turn_on"}), text('{"reply":"Ulanmagan"}')])
    run(Agent(mem, load_tools(), fc).chat("chiroqni yoq"))
    res = fc.calls[1]["messages"][-1]["content"][0]
    assert res["is_error"] and "not connected" in res["content"]


# ---------- games & on-screen hands ----------
def test_games(mem, monkeypatch):
    import secrets as _s
    from app.tools import game_tools
    monkeypatch.setattr(game_tools.secrets, "choice", lambda seq: seq[0])     # bit plays "rock" / "heads"
    monkeypatch.setattr(game_tools.secrets, "randbelow", lambda n: 3)         # dice = 4
    fc = FakeClient([use("play_game", {"game": "shot"}),
                     use("play_game", {"game": "rps", "user_choice": "paper"}, "t2"),
                     use("play_game", {"game": "dice"}, "t3"),
                     use("play_game", {"game": "coin"}, "t4"),
                     use("play_game", {"game": "rps"}, "t5"),
                     text('{"reply":"Voy! ... Tirikman!","emotion":"laughing","gesture":"point"}')])
    out = run(Agent(mem, load_tools(), fc).chat("paq!"))
    acts = out["actions"]
    assert acts[0] == {"type": "game", "game": "shot"}
    assert acts[1] == {"type": "game", "game": "rps", "user": "paper", "bit": "rock", "winner": "user"}
    assert acts[2]["value"] == 4 and acts[3]["side"] == "heads"
    assert fc.calls[5]["messages"][-1]["content"][0]["is_error"] is True      # rps without a choice -> ask first
    assert out["gesture"] == "point"


def test_new_gestures_parse():
    for g in ("raise_hands", "peekaboo", "point", "peace"):
        assert parse_final('{"reply":"x","gesture":"%s"}' % g)["gesture"] == g


def test_congratulation_always_brings_fireworks(mem):
    fc = FakeClient([text('{"reply":"Tugʻilgan kuningiz muborak boʻlsin!","emotion":"excited","gesture":"none","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).chat("bugun mening tugʻilgan kunim"))
    assert {"type": "celebrate", "style": "fireworks"} in out["actions"] and out["gesture"] == "clap"
    fc2 = FakeClient([text('{"reply":"Bugun havo yaxshi.","emotion":"neutral"}')])
    assert run(Agent(mem, load_tools(), fc2).chat("havo qanday?"))["actions"] == []
    fc3 = FakeClient([text('{"reply":"Afsus, bayram bekor boʻlibdi.","emotion":"sad"}')])
    assert run(Agent(mem, load_tools(), fc3).chat("bayram bekor"))["actions"] == []   # no fireworks when sad


def test_appearance_tool_and_api(mem):
    fc = FakeClient([use("set_appearance", {"eye_color": "#4da3ff"}), use("set_appearance", {"body_color": "pink"}, "t2"),
                     text('{"reply":"Koʻzlarim endi koʻk!","emotion":"happy"}')])
    out = run(Agent(mem, load_tools(), fc).chat("koʻzingni koʻk qil"))
    assert mem.kv_get("appearance") == {"eye": "#4DA3FF"}
    assert {"type": "appearance", "eye": "#4DA3FF", "replace": True} in out["actions"]
    assert fc.calls[2]["messages"][-1]["content"][0]["is_error"] is True        # "pink" is not hex
    run(Agent(mem, load_tools(), FakeClient([use("set_appearance", {"eye_color": "default", "body_color": "#26242E"}),
                                              text('{"reply":"ok"}')])).chat("x"))
    assert mem.kv_get("appearance") == {"body": "#26242E"}
    c = TestClient(main.app); h = {"Authorization": "Bearer test-token"}
    assert c.post("/api/appearance", json={"eye": "#00FF00"}, headers=h).json()["eye"] == "#00FF00"
    assert c.get("/api/appearance", headers=h).json()["eye"] == "#00FF00"
    assert c.post("/api/appearance", json={"eye": "javascript:x"}, headers=h).status_code == 400


def test_themes_and_face_style(mem):
    fc = FakeClient([use("set_appearance", {"theme": "purple"}), use("set_appearance", {"face_style": "classic", "accent_color": "#00FFAA"}, "t2"),
                     use("set_appearance", {"theme": "disco"}, "t3"), text('{"reply":"Binafsha boʻldim!","emotion":"happy"}')])
    run(Agent(mem, load_tools(), fc).chat("binafsha boʻl"))
    assert mem.kv_get("appearance") == {"body": "#7B4DFF", "neon": "#00FFAA", "style": "classic"}
    assert fc.calls[3]["messages"][-1]["content"][0]["is_error"] is True
    run(Agent(mem, load_tools(), FakeClient([use("set_appearance", {"theme": "classic", "face_style": "neon"}), text('{"reply":"ok"}')])).chat("x"))
    assert mem.kv_get("appearance") == {"style": "neon"}
    c = TestClient(main.app); h = {"Authorization": "Bearer test-token"}
    assert c.post("/api/appearance", json={"style": "weird"}, headers=h).status_code == 400


def test_lesson_is_parsed_and_remembered(mem):
    reply = {"reply": "Keling, parolni oddiy qilib tushuntiraman.", "emotion": "happy", "gesture": "point", "lang": "uz",
             "lesson": {"title": "Kuchli parol", "points": ["Parol — uyingiz kaliti.", "Uzun boʻlsin: 12+ belgi.", "Har saytga boshqa parol."],
                        "example": "Yomon: 123456\\nYaxshi: Olma-Kitob-7-Quyosh", "check": "Nega bitta parolni hamma joyda ishlatmaslik kerak?"}}
    fc = FakeClient([text(json.dumps(reply, ensure_ascii=False))])
    out = run(Agent(mem, load_tools(), fc).chat("bolalarga kuchli parolni tushuntir"))
    assert out["lesson"]["title"] == "Kuchli parol" and len(out["lesson"]["points"]) == 3 and "123456" in out["lesson"]["example"]
    assert "Teacher mode" in fc.calls[0]["system"] and fc.calls[0]["max_tokens"] == 2048
    stored = mem.recent_messages()[-1]["content"]
    assert "[lesson on the board: Kuchli parol" in stored and "check:" in stored        # so Bit can grade the answer next turn
    assert "lesson" not in parse_final('{"reply":"Salom"}')
    assert "lesson" not in parse_final('{"reply":"x","lesson":"just text"}')


# ---------- fun actions happen even when the model forgets the tool ----------
from app.agent import detect_intent


def test_detect_intent():
    assert detect_intent("Paq!")[0] == "shot" and detect_intent("seni otdim")[0] == "shot" and detect_intent("пиу-пиу")[0] == "shot"
    assert detect_intent("zar tashla")[0] == "dice" and detect_intent("tanga tashla")[0] == "coin"
    assert detect_intent("qoʻlingni koʻtar")[1] == "raise_hands" and detect_intent("qarsak chal")[1] == "clap"
    assert detect_intent("tosh")[2] == "rock" and detect_intent("qogʻoz!")[2] == "paper"
    assert detect_intent("bugun havo qanday?") == (None, None, None)
    assert detect_intent("paqir olib kel")[0] is None          # 'paqir' (bucket) is not a shot


def test_shot_added_when_model_only_talks(mem):
    fc = FakeClient([text('{"reply":"Voy, yana urdingiz! Qayta yuklanyapman.","emotion":"scared","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).chat("paq!"))
    assert {"type": "game", "game": "shot"} in out["actions"]


def test_dice_added_and_reply_matches_result(mem, monkeypatch):
    from app.tools import game_tools
    monkeypatch.setattr(game_tools.secrets, "randbelow", lambda n: 2)
    fc = FakeClient([text('{"reply":"Zar tashladim, 6 chiqdi!","emotion":"excited","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).chat("zar tashla"))
    assert {"type": "game", "game": "dice", "value": 3} in out["actions"] and out["reply"] == "Zar tashladim: 3!"


def test_gesture_added(mem):
    fc = FakeClient([text('{"reply":"Mana!","emotion":"happy","gesture":"none","lang":"uz"}')])
    assert run(Agent(mem, load_tools(), fc).chat("qoʻlingni koʻtar"))["gesture"] == "raise_hands"


def test_rps_answer_after_bit_asked(mem):
    mem.add_message("user", "tosh-qaychi-qogʻoz oʻynaymiz")
    mem.add_message("assistant", "Zoʻr! Tosh, qaychi yoki qogʻoz — tanlang!")
    fc = FakeClient([text('{"reply":"Koʻramiz!","emotion":"excited","lang":"uz"}')])
    out = run(Agent(mem, load_tools(), fc).chat("qaychi"))
    g = [a for a in out["actions"] if a.get("type") == "game"][0]
    assert g["game"] == "rps" and g["user"] == "scissors" and g["winner"] in ("bit", "user", "draw")


def test_no_double_game_when_model_used_tool(mem):
    fc = FakeClient([use("play_game", {"game": "shot"}), text('{"reply":"Voy!","emotion":"scared"}')])
    out = run(Agent(mem, load_tools(), fc).chat("paq"))
    assert [a for a in out["actions"] if a["type"] == "game"] == [{"type": "game", "game": "shot"}]


def test_emotion_demo_intent(mem):
    fc = FakeClient([text('{"reply":"Mana mening emotsiyalarim!","emotion":"happy","lang":"uz"}')])
    assert {"type": "demo"} in run(Agent(mem, load_tools(), fc).chat("emotsiyalaringni koʻrsat"))["actions"]


# ---------- whiteboard, image generation, assistant fallbacks ----------
def test_board_parsing_and_latex_repair(mem):
    raw = ('{"reply":"Keling, misol yechamiz.","emotion":"happy","lang":"uz","board":{"title":"Kasrlar","problem":"$\\frac{1}{2}+\\frac{1}{4}$ = ?",'
           '"steps":[{"write":"$\\frac{1}{2}=\\frac{2}{4}$","say":"Avval maxrajni tenglaymiz."},{"write":"$\\frac{2}{4}+\\frac{1}{4}=\\frac{3}{4}$","say":"Suratlarni qoʻshamiz."}],'
           '"answer":"$\\frac{3}{4}$","check":"$\\frac{1}{3}+\\frac{1}{6}$ = ?"}}')
    fc = FakeClient([text(raw)])                          # note: \\f in JSON source = unescaped \f (form feed) for the parser
    out = run(Agent(mem, load_tools(), fc).chat("kasrlarni tushuntir"))
    b = out["board"]
    assert b["title"] == "Kasrlar" and len(b["steps"]) == 2
    assert b["steps"][0]["write"] == "$\\frac{1}{2}=\\frac{2}{4}$" and b["answer"] == "$\\frac{3}{4}$"
    assert "[whiteboard: Kasrlar" in mem.recent_messages()[-1]["content"]
    # invalid JSON escapes like \sqrt are tolerated
    assert parse_final('{"reply":"ok","board":{"steps":[{"write":"$\\sqrt{9}=3$","say":"x"}]}}')["board"]["steps"][0]["write"] == "$\\sqrt{9}=3$"


def _img_transport(calls, gemini_ok=True):
    def handler(req):
        calls.append(req.url.host)
        if "generativelanguage" in req.url.host:
            if not gemini_ok:
                return _httpx.Response(429, json={"error": {"message": "quota"}})
            return _httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": PNG}}]}}]})
        return _httpx.Response(200, content=b"\x89PNGfake", headers={"content-type": "image/jpeg"})
    return _httpx.MockTransport(handler)


def test_generate_image_gemini_then_fallback(mem, monkeypatch):
    from app.tools import image_tool
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai"); monkeypatch.setattr(config, "OPENAI_API_KEY", "k")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    calls = []
    monkeypatch.setattr(image_tool, "TRANSPORT", _img_transport(calls))
    fc = FakeClient([use("generate_image", {"prompt": "a cute robot drinking tea"}), text('{"reply":"Mana rasm!","emotion":"proud"}')])
    out = run(Agent(mem, load_tools(), fc).chat("rasm chizib ber"))
    img = [a for a in out["actions"] if a["type"] == "image"]
    assert len(img) == 1 and img[0]["src"] == "data:image/png;base64," + PNG and calls == ["generativelanguage.googleapis.com"]
    calls.clear(); monkeypatch.setattr(image_tool, "TRANSPORT", _img_transport(calls, gemini_ok=False))
    ctx = __import__("app.tools", fromlist=["ToolContext"]).ToolContext(memory=mem)
    run(image_tool.GenerateImage().run({"prompt": "cat"}, ctx))
    assert calls == ["generativelanguage.googleapis.com", "image.pollinations.ai"] and ctx.client_actions[0]["src"].startswith("data:image/jpeg;base64,")


def test_image_and_video_fallbacks(mem, monkeypatch):
    from app.tools import image_tool, youtube_tool
    calls = []
    monkeypatch.setattr(image_tool, "TRANSPORT", _img_transport(calls))
    monkeypatch.setattr(config, "LLM_PROVIDER", "anthropic")
    fc = FakeClient([text('{"reply":"Albatta, chizaman!","emotion":"happy"}')])
    out = run(Agent(mem, load_tools(), fc).chat("menga mushuk rasmini chizib ber"))
    assert any(a["type"] == "image" for a in out["actions"]) and calls == ["image.pollinations.ai"]
    seen = {}
    monkeypatch.setattr(youtube_tool, "_search", lambda q: seen.setdefault("q", q) and {"id": "abcdefghijk", "title": "T"})
    fc2 = FakeClient([text('{"reply":"Ochyapman!","emotion":"happy"}')])
    out2 = run(Agent(mem, load_tools(), fc2).chat("youtube'da Sherali Joʻrayev qoʻshigʻini qoʻyib ber"))
    assert any(a["type"] == "youtube" for a in out2["actions"]) and "sherali" in seen["q"] and "youtube" not in seen["q"]
    fc3 = FakeClient([text('{"reply":"Salom! Bugun nimada yordam beray?","emotion":"happy"}')])
    assert run(Agent(mem, load_tools(), fc3).chat("salom"))["actions"] == []
    assert "Your main job is to be genuinely useful" in fc3.calls[0]["system"] and "do not suggest games" in fc3.calls[0]["system"]
