"""
xAI Grok helper for this repo.

Goal: make workflow runs resilient to xAI API migrations.
- Never use deprecated `search_parameters` on /chat/completions (causes 410).
- Use xAI's Agent Tools API (via xai-sdk) when "live search" is desired.
- Fall back to plain Grok text generation when tools are unavailable.
"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional, Tuple


def _get_xai_api_key() -> str:
    # Workflows historically use GROK_API_KEY. xAI docs use XAI_API_KEY.
    return (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()


def grok_generate_text(
    *,
    prompt: str,
    model: str = "grok-4",
    temperature: float = 0.7,
    max_tokens: int = 3500,
    timeout_seconds: float = 3600.0,
    enable_web_search: bool = False,
    enable_x_search: bool = False,
    max_turns: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate text from Grok.

    - If enable_web_search / enable_x_search is True, uses xai-sdk agent tools API (recommended).
    - Otherwise uses OpenAI-compatible chat/completions WITHOUT any `search_parameters`.

    Returns: (text, meta) where meta may include usage/citations.
    """
    api_key = _get_xai_api_key()
    if not api_key:
        raise RuntimeError("Missing GROK_API_KEY (or XAI_API_KEY).")

    want_tools = bool(enable_web_search or enable_x_search)

    # Preferred path for tool usage: xAI Python SDK (agent tools).
    if want_tools:
        try:
            from xai_sdk import Client as XAIClient
            from xai_sdk.chat import user as xai_user
            from xai_sdk.tools import web_search, x_search
        except Exception as exc:
            logging.warning(
                "xai-sdk not available; falling back to non-tool Grok generation. (%s)",
                exc,
            )
            want_tools = False
        else:
            xai_client = XAIClient(api_key=api_key, timeout=timeout_seconds)
            tools = []
            if enable_web_search:
                tools.append(web_search())
            if enable_x_search:
                tools.append(x_search())

            # Tool calling works best with the agentic model.
            tools_model = "grok-4-1-fast"
            kwargs: Dict[str, Any] = {}
            if max_turns is not None:
                kwargs["max_turns"] = max_turns

            chat = xai_client.chat.create(
                model=tools_model,
                tools=tools,
                **kwargs,
            )
            chat.append(xai_user(prompt))
            resp = chat.sample()

            text = (getattr(resp, "content", "") or "").strip()
            meta: Dict[str, Any] = {
                "provider": "xai_sdk",
                "model": tools_model,
            }
            usage = getattr(resp, "usage", None)
            if usage is not None:
                meta["usage"] = usage
            citations = getattr(resp, "citations", None)
            if citations is not None:
                meta["citations"] = citations
            return text, meta

    # Plain generation: OpenAI-compatible endpoint, but WITHOUT deprecated search_parameters.
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1", timeout=timeout_seconds)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = resp.choices[0].message.content.strip()
    meta = {
        "provider": "openai_compat",
        "model": model,
        "usage": getattr(resp, "usage", None),
    }
    return text, meta

