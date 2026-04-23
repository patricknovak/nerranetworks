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
from typing import Any, Dict, List, Optional, Tuple


def _get_xai_api_key() -> str:
    # Workflows historically use GROK_API_KEY. xAI docs use XAI_API_KEY.
    return (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()


def grok_generate_text(
    *,
    prompt: str,
    model: str = "grok-4.20-non-reasoning",
    temperature: float = 0.7,
    max_tokens: int = 3500,
    timeout_seconds: float = 3600.0,
    enable_web_search: bool = False,
    enable_x_search: bool = False,
    x_handles: Optional[List[str]] = None,
    max_turns: Optional[int] = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate text from Grok.

    - If enable_web_search / enable_x_search is True, uses xai-sdk's
      SearchParameters API (structured search, forced mode).
    - Otherwise uses OpenAI-compatible chat/completions WITHOUT any
      ``search_parameters``.

    Parameters
    ----------
    x_handles : list[str], optional
        When enable_x_search is True, restrict X search to these handles.
        Uses ``XSource(included_x_handles=...)`` for targeted retrieval.

    Returns: (text, meta) where meta may include usage/citations.
    """
    api_key = _get_xai_api_key()
    if not api_key:
        raise RuntimeError("Missing GROK_API_KEY (or XAI_API_KEY).")

    want_search = bool(enable_web_search or enable_x_search)

    if want_search:
        try:
            from xai_sdk import Client as XAIClient
            from xai_sdk.chat import SearchParameters, user as xai_user, chat_pb2
        except ImportError as exc:
            logging.error(
                "xai-sdk import failed — search tools will NOT work. "
                "Install with: pip install 'xai-sdk>=1.5.0'. Error: %s",
                exc,
            )
            want_search = False
        except Exception as exc:
            logging.error(
                "xai-sdk failed to load: %s — %s",
                type(exc).__name__, exc,
            )
            want_search = False

    if want_search:
        xai_client = XAIClient(api_key=api_key, timeout=timeout_seconds)

        # Build structured search sources
        sources = []
        if enable_x_search:
            x_kwargs = {}
            if x_handles:
                x_kwargs["included_x_handles"] = [
                    h.lstrip("@") for h in x_handles
                ]
            sources.append(chat_pb2.Source(x=chat_pb2.XSource(**x_kwargs)))
        if enable_web_search:
            sources.append(chat_pb2.Source(web=chat_pb2.WebSource()))

        search_params = SearchParameters(
            sources=sources if sources else None,
            mode="on",
            max_search_results=15,
            return_citations=True,
        )

        search_model = model
        kwargs: Dict[str, Any] = {"search_parameters": search_params}
        if max_turns is not None:
            kwargs["max_turns"] = max_turns

        logging.info(
            "xai-sdk: calling %s with SearchParameters(mode=on, sources=%d, x_handles=%s)",
            search_model,
            len(sources),
            x_handles or "all",
        )

        chat = xai_client.chat.create(model=search_model, **kwargs)
        chat.append(xai_user(prompt))
        resp = chat.sample()

        text = (getattr(resp, "content", "") or "").strip()
        logging.info("xai-sdk: got %d chars from %s", len(text), search_model)

        meta: Dict[str, Any] = {"provider": "xai_sdk", "model": search_model}
        usage = getattr(resp, "usage", None)
        if usage is not None:
            meta["usage"] = usage
        citations = getattr(resp, "citations", None)
        if citations is not None:
            meta["citations"] = citations
        return text, meta

    # Plain generation: OpenAI-compatible endpoint.
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

