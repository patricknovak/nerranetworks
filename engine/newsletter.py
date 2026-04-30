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

    # Engagement footer — encourage sharing and listening
    html_parts.append(
        '<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0 16px;">'
        '<p style="margin: 8px 0; font-size: 0.9em; color: #718096;">'
        'Enjoyed this? Forward it to a friend who would too.'
        '</p>'
        '<p style="margin: 8px 0; font-size: 0.9em; color: #718096;">'
        '<a href="https://nerranetwork.com" style="color: #7C5CFF;">Listen on nerranetwork.com</a>'
        ' &middot; '
        '<a href="https://nerranetwork.com/player.html" style="color: #7C5CFF;">Open Player</a>'
        ' &middot; '
        '<a href="https://nerranetwork.com#subscribe" style="color: #7C5CFF;">Subscribe to more shows</a>'
        '</p>'
        '<p style="margin: 8px 0; font-size: 0.8em; color: #a0aec0;">'
        'Nerra Network &mdash; 10 daily podcasts, ad-free, from Vancouver, Canada.'
        '</p>'
    )

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
    """Test if the Buttondown API key is valid by calling GET /v1/emails.

    Returns ``True`` only on a clean ``200``. ``401``/``403`` mean the
    key is bad. Other status codes (``429``, ``5xx``, network errors)
    return ``False`` too — the caller can't safely proceed when
    Buttondown's reachability is unknown, and the previous behavior
    (returning ``True`` on any non-401) created false confidence
    that pre-flight passed when the service was down.
    """
    try:
        resp = requests.get(
            f"{BUTTONDOWN_API_BASE}/emails",
            headers={"Authorization": f"Token {api_key}"},
            timeout=10,
            params={"limit": 1},
        )
    except Exception as e:
        logger.error("Buttondown API key validation failed: %s", e)
        return False

    if resp.status_code == 200:
        logger.info("Buttondown API key validated successfully")
        return True
    if resp.status_code in (401, 403):
        logger.error(
            "Buttondown API key is INVALID or EXPIRED (HTTP %d)",
            resp.status_code,
        )
        return False
    # 429 / 5xx / anything else — we can't confirm the key is good and
    # we shouldn't claim it is. Surface as a soft failure so the
    # newsletter stage skips this run cleanly rather than queuing a
    # send against a potentially-unhealthy Buttondown.
    logger.warning(
        "Buttondown API key check returned HTTP %d — treating as "
        "transient unavailability (validation failed).",
        resp.status_code,
    )
    return False


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


_VALID_STATUSES = {"about_to_send", "draft", "scheduled"}


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
    # Strip newlines from subject to prevent email header injection
    subject = subject.replace("\r", "").replace("\n", " ").strip()

    if status not in _VALID_STATUSES:
        logger.error(
            "Newsletter status %r is invalid — must be one of %s. "
            "Refusing to send to avoid wasting an API call on a 400.",
            status, sorted(_VALID_STATUSES),
        )
        return None

    data = {
        "subject": subject,
        "body": body,
        "status": status,
    }

    if tags:
        # Buttondown's email-send filters use a tree structure with
        # ``filters`` (leaf conditions), ``groups`` (nested filter
        # groups), and ``predicate`` ("and"/"or") for the join.
        # Older clients sent ``{operator, predicates}`` and got
        # HTTP 422; the predicate enum is also strict — only "and"
        # or "or" are accepted (not "any"/"all").
        data["filters"] = {
            "filters": [
                {"field": "tag", "operator": "equals", "value": t}
                for t in tags
            ],
            "groups": [],
            "predicate": "or",  # OR semantics across the listed tags
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
        recipient_count = result.get("secondary_id", result.get("num_recipients", "?"))
        logger.info(
            "Newsletter created: id=%s status=%s tags=%s recipients=%s",
            email_id, status, tags, recipient_count,
        )
        # Zero recipients when tag filters are set is a misconfiguration —
        # the email was accepted but nobody received it. Surface this as a
        # failure so the caller can alert/retry rather than logging "sent".
        if tags and result.get("num_recipients", 1) == 0:
            logger.error(
                "Newsletter %s was created but has 0 recipients — "
                "tag filter %s matched no subscribers. Treating as failure.",
                email_id, tags,
            )
            return None
        return email_id
    else:
        logger.error(
            "Newsletter send failed: %s %s",
            resp.status_code, resp.text[:500],
        )
        return None


def send_show_newsletter(
    digest_text: str,
    config,
    episode_num: int,
    today_str: str,
    *,
    hook: str = "",
) -> Optional[str]:
    """Send newsletter for a show if newsletter is configured.

    Reads the API key from the environment variable specified in
    ``config.newsletter.api_key_env``.  Applies tag filtering if the
    show's ``newsletter.tag`` is set (so only subscribers tagged for this
    show receive the email).

    When *hook* is provided, it is used in the subject line to give
    subscribers a reason to open the email.  Otherwise falls back to a
    generic "Episode N" subject.

    Returns the email ID on success, ``None`` if not configured or failed.
    """
    newsletter = getattr(config, "newsletter", None)
    if not newsletter or not newsletter.enabled:
        return None

    api_key = os.getenv(newsletter.api_key_env, "").strip()
    if not api_key:
        logger.info("Newsletter API key not set (%s). Skipping.", newsletter.api_key_env)
        return None

    # Use the hook for a compelling subject line (truncate to 80 chars
    # to stay within email client subject line limits).
    if hook and len(hook) > 10:
        hook_short = hook[:80].rstrip(". ") if len(hook) > 80 else hook.rstrip(".")
        subject = f"{config.name}: {hook_short}"
    else:
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
