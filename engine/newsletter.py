"""Newsletter publishing via Buttondown API.

Converts markdown digests to email-friendly HTML and sends via the
Buttondown API (``POST /v1/emails``).  Supports per-show tag filtering
so subscribers only receive emails for shows they opted into.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

BUTTONDOWN_API_BASE = "https://api.buttondown.com/v1"


def convert_digest_to_email_html(markdown_text: str) -> str:
    """Convert a markdown digest to clean, mobile-friendly email HTML.

    Applies minimal inline styling for email client compatibility.
    Does not depend on external CSS — all styles are inline.
    """
    lines = markdown_text.split("\n")
    html_parts = [
        '<!DOCTYPE html>',
        '<html><head><meta charset="utf-8"></head>',
        '<body style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', '
        'Roboto, sans-serif; line-height: 1.6; color: #1a1a2e; max-width: 600px; '
        'margin: 0 auto; padding: 16px;">',
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            html_parts.append("<br>")
            continue

        # Headers
        if stripped.startswith("# "):
            html_parts.append(
                f'<h1 style="font-size: 1.4em; margin: 16px 0 8px; color: #1a1a2e;">'
                f'{_md_inline(stripped[2:])}</h1>'
            )
        elif stripped.startswith("## "):
            html_parts.append(
                f'<h2 style="font-size: 1.2em; margin: 14px 0 6px; color: #2d3748;">'
                f'{_md_inline(stripped[3:])}</h2>'
            )
        elif stripped.startswith("### "):
            html_parts.append(
                f'<h3 style="font-size: 1.05em; margin: 12px 0 4px; color: #4a5568;">'
                f'{_md_inline(stripped[4:])}</h3>'
            )
        # Horizontal rules / separators
        elif stripped.startswith("━") or stripped.startswith("---"):
            html_parts.append(
                '<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 16px 0;">'
            )
        # Bullet items
        elif stripped.startswith("- "):
            html_parts.append(
                f'<p style="margin: 4px 0 4px 16px;">• {_md_inline(stripped[2:])}</p>'
            )
        # Numbered items
        elif re.match(r"^\d+\.\s", stripped):
            html_parts.append(
                f'<p style="margin: 4px 0 4px 16px;">{_md_inline(stripped)}</p>'
            )
        else:
            html_parts.append(f'<p style="margin: 4px 0;">{_md_inline(stripped)}</p>')

    html_parts.append("</body></html>")
    return "\n".join(html_parts)


def _md_inline(text: str) -> str:
    """Convert inline markdown (bold, italic, links) to HTML."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Links
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color: #2b6cb0;">\1</a>',
        text,
    )
    return text


# ---------------------------------------------------------------------------
# API key validation
# ---------------------------------------------------------------------------


def validate_api_key(api_key: str) -> bool:
    """Test if the Buttondown API key is valid by calling GET /v1/emails."""
    try:
        resp = requests.get(
            f"{BUTTONDOWN_API_BASE}/emails",
            headers={"Authorization": f"Token {api_key}"},
            timeout=10,
            params={"limit": 1},
        )
        if resp.status_code == 401:
            logger.error("Buttondown API key is INVALID or EXPIRED (401 Unauthorized)")
            return False
        if resp.status_code == 200:
            logger.info("Buttondown API key validated successfully")
            return True
        logger.warning("Buttondown API key check returned status %d", resp.status_code)
        return True
    except Exception as e:
        logger.error("Buttondown API key validation failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


def send_newsletter(
    subject: str,
    body: str,
    *,
    api_key: str,
    status: str = "about_to_send",
    tags: Optional[List[str]] = None,
) -> Optional[str]:
    """Send a newsletter issue via Buttondown API.

    Parameters
    ----------
    subject:
        Email subject line.
    body:
        Markdown body text (Buttondown renders markdown natively).
    api_key:
        Buttondown API key.
    status:
        One of ``"about_to_send"``, ``"draft"``, or ``"scheduled"``.
    tags:
        Optional list of Buttondown tag names.  When provided, the email
        is sent **only** to subscribers who have any of the listed tags.
        This enables per-show targeting from a single Buttondown account.

    Returns
    -------
    str or None
        The email ID on success, ``None`` on failure.
    """
    data = {
        "subject": subject,
        "body": body,
        "status": status,
        "filters": {
            "filters": [{"field": "tag", "operator": "includes", "value": t} for t in tags] if tags else [],
            "groups": [],
        },
    }

    resp = requests.post(
        f"{BUTTONDOWN_API_BASE}/emails",
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "application/json",
        },
        json=data,
        timeout=30,
    )

    if resp.status_code in (200, 201):
        result = resp.json()
        email_id = result.get("id", "unknown")
        logger.info("Newsletter sent: %s (status=%s, tags=%s)", email_id, status, tags)
        return email_id
    else:
        logger.error("Newsletter send failed: %s %s", resp.status_code, resp.text[:200])
        return None


def send_show_newsletter(
    digest_text: str,
    config,
    episode_num: int,
    today_str: str,
) -> Optional[str]:
    """Send newsletter for a show if newsletter is configured.

    Reads the API key from the environment variable specified in
    ``config.newsletter.api_key_env``.  Applies tag filtering if the
    show's ``newsletter.tag`` is set (so only subscribers tagged for this
    show receive the email).

    Returns the email ID on success, ``None`` if not configured or failed.
    """
    newsletter = getattr(config, "newsletter", None)
    if not newsletter or not newsletter.enabled:
        return None

    api_key = os.getenv(newsletter.api_key_env, "").strip()
    if not api_key:
        logger.info("Newsletter API key not set (%s). Skipping.", newsletter.api_key_env)
        return None

    subject = f"{config.name} — {today_str} (Episode {episode_num})"

    tag = getattr(newsletter, "tag", "") or ""
    tags_list = [tag] if tag else None

    return send_newsletter(
        subject=subject,
        body=digest_text,
        api_key=api_key,
        status=getattr(newsletter, "status", "about_to_send"),
        tags=tags_list,
    )
