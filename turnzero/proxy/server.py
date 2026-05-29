"""TurnZero proxy ASGI server — intercepts OAI-compatible requests and injects priors."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from turnzero.config import get_data_dir, load_config
from turnzero.proxy.injection import extract_prompt, maybe_inject
from turnzero.proxy.providers import (
    OPENAI_API_URL,
    provider_label_for_url,
    resolve_provider_url,
)
from turnzero.proxy.session import (
    get_blocks_count,
    get_or_create,
    is_turn_0,
    new_session_id,
)
from turnzero.telemetry import track_proxy_turn

_CHAT_PATH = "/v1/chat/completions"
_SECRET_HEADER = "X-TurnZero-Secret"
_SESSION_HEADER = "X-TurnZero-Session"
_SKIP_HEADERS = {"host", "content-length", _SECRET_HEADER.lower(), _SESSION_HEADER.lower()}


def _unauthorized() -> JSONResponse:
    return JSONResponse({"error": "unauthorized"}, status_code=401)


def _forward_headers(request: Request) -> dict[str, str]:
    return {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_HEADERS}


def _resolve_url(request: Request, provider_url: str) -> str:
    path = request.url.path
    query = f"?{request.url.query}" if request.url.query else ""
    return f"{provider_url.rstrip('/')}{path}{query}"


def _load_proxy_config() -> dict[str, Any]:
    """Read proxy section from config.yaml fresh on each call — no restart needed."""
    try:
        raw = load_config(get_data_dir()).get("proxy", {})
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _get_provider_url(request: Request, model: str) -> str:
    proxy_cfg = _load_proxy_config()
    if override := proxy_cfg.get("provider_url"):
        return str(override).rstrip("/")
    user_rules: list[dict[str, str]] | None = proxy_cfg.get("provider_rules") or None
    return resolve_provider_url(
        request.headers.get("Authorization"),
        model,
        user_rules=user_rules,
    )


async def _proxy_chat(request: Request, secret: str) -> Response:
    if request.headers.get(_SECRET_HEADER) != secret:
        return _unauthorized()

    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    model: str = body.get("model", "")
    is_stream: bool = bool(body.get("stream", False))

    session_id = request.headers.get(_SESSION_HEADER) or new_session_id()
    get_or_create(session_id)

    was_turn_0 = is_turn_0(session_id)
    prompt_word_count = len(extract_prompt(messages).split())
    body["messages"] = maybe_inject(messages, session_id)
    injection_happened = was_turn_0 and not is_turn_0(session_id)

    provider_url = _get_provider_url(request, model)
    target = f"{provider_url}{_CHAT_PATH}"
    headers = _forward_headers(request)

    track_proxy_turn(
        session_id=session_id,
        reason="turn_0" if was_turn_0 else "skip",
        prompt_word_count=prompt_word_count,
        injection_happened=injection_happened,
        blocks_count=get_blocks_count(session_id) if injection_happened else 0,
        provider=provider_label_for_url(provider_url),
        model=model,
    )

    if is_stream:
        return await _stream_response(target, body, headers, session_id)
    return await _json_response(target, body, headers)


async def _stream_response(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    session_id: str,
) -> Response:
    async def _generate() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=None) as client, client.stream("POST", url, json=body, headers=headers) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk
        except httpx.ConnectError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n".encode()

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={_SESSION_HEADER: session_id},
    )


async def _json_response(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
) -> Response:
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/json"),
            )
    except httpx.ConnectError as exc:
        return JSONResponse({"error": f"provider unreachable: {exc}"}, status_code=502)


async def _passthrough(request: Request, secret: str) -> Response:
    if request.headers.get(_SECRET_HEADER) != secret:
        return _unauthorized()

    proxy_cfg = _load_proxy_config()
    provider_url = str(proxy_cfg.get("provider_url", OPENAI_API_URL)).rstrip("/")
    target = _resolve_url(request, provider_url)
    headers = _forward_headers(request)
    body_bytes = await request.body()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                request.method, target, content=body_bytes, headers=headers
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "application/json"),
            )
    except httpx.ConnectError as exc:
        return JSONResponse({"error": f"provider unreachable: {exc}"}, status_code=502)


def build_app(secret: str) -> Starlette:
    """Build and return the TurnZero proxy ASGI app.

    Args:
        secret: Shared secret — clients must send X-TurnZero-Secret: <secret>.
    """
    async def chat_handler(request: Request) -> Response:
        return await _proxy_chat(request, secret)

    async def passthrough_handler(request: Request) -> Response:
        return await _passthrough(request, secret)

    return Starlette(routes=[
        Route(_CHAT_PATH, endpoint=chat_handler, methods=["POST"]),
        Route("/{path:path}", endpoint=passthrough_handler, methods=["GET", "POST", "DELETE", "PUT", "PATCH"]),
    ])
