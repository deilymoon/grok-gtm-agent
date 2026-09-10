"""xAI API client: chat JSON + Responses API research with web_search / x_search.

Live research uses xAI built-in server-side tools (web_search, x_search) via
POST https://api.x.ai/v1/responses — not model-knowledge-only discovery.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from url_utils import validate_url

DEFAULT_MODEL = "grok-4-1-fast-reasoning"
FALLBACK_MODELS = (
    "grok-4-1-fast-reasoning",
    "grok-4-1-fast",
    "grok-4-fast",
    "grok-4-fast-reasoning",
)


class XAIError(Exception):
    """Base error for xAI client failures."""


class AuthError(XAIError):
    pass


class RateLimitError(XAIError):
    pass


class TimeoutError(XAIError):  # noqa: A001 — intentional domain name
    pass


class InvalidResponseError(XAIError):
    pass


class ResearchError(XAIError):
    pass


@dataclass
class ResearchResult:
    text: str
    citations: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    model: str = ""


def _strip_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _raise_for_status(status: int, body: str) -> None:
    if status in (401, 403):
        raise AuthError(f"xAI auth failed (HTTP {status}). Check XAI_API_KEY.")
    if status == 429:
        raise RateLimitError(f"xAI rate limit (HTTP {status}).")
    if status >= 400:
        snippet = (body or "")[:400]
        raise ResearchError(f"xAI HTTP {status}: {snippet}")


def _collect_urls_from_obj(obj: Any, found: set[str]) -> None:
    if isinstance(obj, str):
        if obj.startswith("http://") or obj.startswith("https://"):
            if validate_url(obj):
                found.add(obj.strip())
        else:
            for m in re.findall(r"https?://[^\s\]\"'<>]+", obj):
                cleaned = m.rstrip(").,;]")
                if validate_url(cleaned):
                    found.add(cleaned)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in {"url", "uri", "source_url", "href", "link"} and isinstance(v, str):
                if validate_url(v):
                    found.add(v.strip())
            else:
                _collect_urls_from_obj(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_urls_from_obj(item, found)


def extract_citations(payload: dict[str, Any]) -> list[str]:
    """Parse citation URLs from Responses API output (citations, annotations, tool calls)."""
    found: set[str] = set()

    cites = payload.get("citations") or []
    if isinstance(cites, list):
        for c in cites:
            if isinstance(c, str) and validate_url(c):
                found.add(c.strip())
            elif isinstance(c, dict):
                _collect_urls_from_obj(c, found)

    output = payload.get("output") or []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            itype = item.get("type") or ""
            if itype in {"web_search_call", "x_search_call", "web_search", "x_search"}:
                _collect_urls_from_obj(item, found)
            if itype == "message":
                content = item.get("content") or []
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        for ann in part.get("annotations") or []:
                            _collect_urls_from_obj(ann, found)
                        text = part.get("text") or ""
                        if isinstance(text, str):
                            _collect_urls_from_obj(text, found)
                elif isinstance(content, str):
                    _collect_urls_from_obj(content, found)

    if not found:
        _collect_urls_from_obj(payload, found)

    return sorted(found)


def extract_output_text(payload: dict[str, Any]) -> str:
    """Extract final assistant text from Responses API payload."""
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"].strip()

    texts: list[str] = []
    output = payload.get("output") or []
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message":
                continue
            content = item.get("content") or []
            if isinstance(content, str):
                texts.append(content)
                continue
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        t = part.get("text") or part.get("output_text")
                        if isinstance(t, str) and t.strip():
                            texts.append(t)
                    elif isinstance(part, str):
                        texts.append(part)
    if texts:
        return "\n".join(texts).strip()

    choices = payload.get("choices") or []
    if choices and isinstance(choices, list):
        msg = (choices[0] or {}).get("message") or {}
        content = msg.get("content") or ""
        if isinstance(content, str):
            return content.strip()

    raise InvalidResponseError("No text content in xAI response.")


class XAIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        model: str = DEFAULT_MODEL,
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise AuthError("XAI_API_KEY is missing.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout, connect=30.0),
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "XAIClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self._http.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"xAI request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ResearchError(f"xAI transport error: {exc}") from exc
        _raise_for_status(resp.status_code, resp.text)
        try:
            return resp.json()
        except Exception as exc:
            raise InvalidResponseError(f"Non-JSON xAI response: {exc}") from exc

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.3,
        model: Optional[str] = None,
        retry_on_malformed: bool = True,
    ) -> dict[str, Any]:
        """Structured JSON via chat completions (no tools). Retries once on bad JSON."""
        use_model = model or self.model
        last_err: Exception | None = None
        attempts = 2 if retry_on_malformed else 1
        for attempt in range(attempts):
            payload = {
                "model": use_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
            }
            try:
                data = self._post("/chat/completions", payload)
            except ResearchError as exc:
                if "model" in str(exc).lower() or "404" in str(exc):
                    for fb in FALLBACK_MODELS:
                        if fb == use_model:
                            continue
                        payload["model"] = fb
                        try:
                            data = self._post("/chat/completions", payload)
                            use_model = fb
                            self.model = fb
                            break
                        except Exception:
                            continue
                    else:
                        raise
                else:
                    raise
            try:
                text = extract_output_text(data)
                text = _strip_fences(text)
                return json.loads(text)
            except (json.JSONDecodeError, InvalidResponseError) as exc:
                last_err = exc
                if attempt + 1 < attempts:
                    user = (
                        user
                        + "\n\nIMPORTANT: Previous reply was not valid JSON. "
                        "Return ONLY a single JSON object, no markdown."
                    )
                    continue
                raise InvalidResponseError(f"Failed to parse JSON from Grok: {exc}") from exc
        raise InvalidResponseError(f"Failed to parse JSON from Grok: {last_err}")

    def research_with_tools(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        model: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> ResearchResult:
        """Call Responses API with web_search + x_search; return text + citation URLs.

        Live research uses xAI built-in web_search and x_search server-side tools.
        """
        use_model = model or self.model
        tool_list = tools or [{"type": "web_search"}, {"type": "x_search"}]
        input_items: list[dict[str, Any]] = []
        if system:
            input_items.append({"role": "system", "content": system})
        input_items.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": use_model,
            "input": input_items,
            "tools": tool_list,
        }

        last_exc: Exception | None = None
        models_to_try = [use_model] + [m for m in FALLBACK_MODELS if m != use_model]
        data: dict[str, Any] | None = None
        used_model = use_model
        for m in models_to_try:
            payload["model"] = m
            try:
                data = self._post("/responses", payload)
                used_model = m
                if m != self.model:
                    self.model = m
                break
            except (ResearchError, AuthError, RateLimitError, TimeoutError) as exc:
                last_exc = exc
                if isinstance(exc, (AuthError, RateLimitError, TimeoutError)):
                    raise
                continue
        if data is None:
            raise ResearchError(f"Responses API failed: {last_exc}")

        try:
            text = extract_output_text(data)
        except InvalidResponseError as exc:
            raise ResearchError(str(exc)) from exc
        citations = extract_citations(data)
        return ResearchResult(text=text, citations=citations, raw=data, model=used_model)
