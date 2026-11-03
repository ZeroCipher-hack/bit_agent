"""LLM providers behind one interface, so Bit can run on Claude (paid) or any OpenAI-compatible API:
Google Gemini (free tier), Groq (free tier), OpenRouter, or a local Ollama model (free, offline).

Neutral transcript the agent keeps:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "input"}]}
  {"role": "tool_results", "results": [{"id", "content": str, "is_error": bool}]}
complete() returns {"text": str, "tool_calls": [{"id", "name", "input"}]}."""
import json
import uuid

import httpx

from . import config


class LLMError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AnthropicLLM:
    def __init__(self, client=None):
        if client is None:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.client = client

    @staticmethod
    def _convert(transcript):
        out = []
        for m in transcript:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content", "").strip() else []
                blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["input"]} for c in m.get("tool_calls", [])]
                out.append({"role": "assistant", "content": blocks or m.get("content", "")})
            elif m["role"] == "tool_results":
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"], "is_error": r["is_error"]}
                    for r in m["results"]]})
        return out

    async def complete(self, system, transcript, tools, smart=False):
        resp = await self.client.messages.create(
            model=config.MODEL_SMART if smart else config.MODEL_FAST, max_tokens=1024, system=system,
            tools=[t.schema() for t in tools], messages=self._convert(transcript))
        text = "\n".join(b.text for b in resp.content if b.type == "text")
        calls = [{"id": b.id, "name": b.name, "input": dict(b.input or {})} for b in resp.content if b.type == "tool_use"]
        return {"text": text, "tool_calls": calls if resp.stop_reason == "tool_use" or calls else []}


class OpenAICompatLLM:
    def __init__(self, base_url=None, api_key=None, model_fast=None, model_smart=None, transport=None):
        self.base_url = (base_url or config.OPENAI_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else config.OPENAI_API_KEY
        self.model_fast = model_fast or config.OPENAI_MODEL_FAST
        self.model_smart = model_smart or config.OPENAI_MODEL_SMART or self.model_fast
        self.transport = transport

    @staticmethod
    def _convert(system, transcript):
        out = [{"role": "system", "content": system}]
        for m in transcript:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("content") or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c["id"], "type": "function",
                                          "function": {"name": c["name"], "arguments": json.dumps(c["input"], ensure_ascii=False)}}
                                         for c in m["tool_calls"]]
                out.append(msg)
            elif m["role"] == "tool_results":
                out += [{"role": "tool", "tool_call_id": r["id"], "content": r["content"]} for r in m["results"]]
        return out

    async def complete(self, system, transcript, tools, smart=False):
        body = {"model": self.model_smart if smart else self.model_fast, "max_tokens": 1024,
                "messages": self._convert(system, transcript),
                "tools": [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                             "parameters": t.input_schema}} for t in tools]}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=90, transport=self.transport) as client:
            r = await client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
        if r.status_code >= 400:
            try:
                err = r.json()
                err = err[0] if isinstance(err, list) else err
                detail = (err.get("error") or {}).get("message") or r.text
            except (ValueError, AttributeError):
                detail = r.text
            raise LLMError(f"HTTP {r.status_code}: {detail[:300]}", r.status_code)
        msg = (r.json().get("choices") or [{}])[0].get("message") or {}
        calls = []
        for c in msg.get("tool_calls") or []:
            fn = c.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": c.get("id") or "call_" + uuid.uuid4().hex[:8], "name": fn.get("name", ""),
                          "input": args if isinstance(args, dict) else {}})
        return {"text": msg.get("content") or "", "tool_calls": calls}


def make_llm():
    if config.LLM_PROVIDER == "anthropic":
        return AnthropicLLM()
    return OpenAICompatLLM()
