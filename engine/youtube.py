"""YouTube publishing wrapper for the podcast pipeline.

Provides:

  - :func:`upload_video` — resumable video upload + thumbnail set in one
    call. Mirrors the ``post_to_x()`` style: explicit credentials in,
    watch URL out.
  - :func:`build_oauth_credentials` — turn a long-lived refresh token
    into a usable :class:`google.oauth2.credentials.Credentials`. Used
    in production (CI) where we cannot run a browser flow.
  - :func:`get_channel_credentials_from_env` — convenience wrapper that
    reads the four ``YOUTUBE_*`` env vars used by the workflow.

Every upload sets ``status.containsSyntheticMedia=True`` because all
Nerra Network episodes use ElevenLabs voice synthesis. This is the API
field YouTube introduced in October 2024 for AI/A&S disclosure; setting
it via the API renders the same "Altered or synthetic content" label
the Studio UI applies, and is required for monetization-eligible AI
audio uploads.

Quotas
------
``videos.insert`` costs **1,600 quota units** per upload. The default
project quota is 10,000 units/day. ``thumbnails.set`` adds another
50 units. Plan accordingly — see ``docs/youtube_setup.md``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# OAuth scopes required for upload + thumbnail set + channel read.
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# Google's OAuth token endpoint. Held as a constant rather than an env
# var so misconfigured deployments fail loudly at import time, not
# halfway through a run.
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def build_oauth_credentials(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
):
    """Return a refreshable :class:`Credentials` for the YouTube API.

    The refresh token is what we mint **once** via the bootstrap script
    (``scripts/youtube_oauth_bootstrap.py``) and store as a GitHub
    secret. Google's library automatically swaps it for a short-lived
    access token on every API call.
    """
    from google.oauth2.credentials import Credentials

    if not client_id or not client_secret:
        raise ValueError(
            "YouTube OAuth client_id/client_secret are required"
        )
    if not refresh_token:
        raise ValueError("YouTube OAuth refresh_token is required")

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=GOOGLE_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=YOUTUBE_SCOPES,
    )


def get_channel_credentials_from_env(channel: str = "en"):
    """Read the four ``YOUTUBE_*`` env vars and return Credentials.

    *channel* picks which refresh token to load: ``"en"`` →
    ``YOUTUBE_REFRESH_TOKEN_EN``, ``"ru"`` →
    ``YOUTUBE_REFRESH_TOKEN_RU``. Returns ``None`` (not an exception)
    if any value is missing — the caller decides whether to skip the
    upload or fail the run.
    """
    client_id = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
    suffix = "RU" if channel.lower() == "ru" else "EN"
    refresh_token = os.getenv(f"YOUTUBE_REFRESH_TOKEN_{suffix}", "").strip()

    if not all([client_id, client_secret, refresh_token]):
        logger.info(
            "YouTube credentials not fully set for channel=%s — skipping",
            channel,
        )
        return None

    return build_oauth_credentials(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

# Errors that warrant a retry. Pulled in lazily inside
# ``_should_retry_http`` so the module imports cleanly even when the
# google libraries are missing (e.g. in pure-unit-test environments).
def _is_retryable_http_error(exc: BaseException) -> bool:
    try:
        from googleapiclient.errors import HttpError
    except ImportError:  # pragma: no cover
        return False
    if not isinstance(exc, HttpError):
        return False
    status = getattr(getattr(exc, "resp", None), "status", 0)
    return status in (429, 500, 502, 503, 504)


def _build_video_body(
    *,
    title: str,
    description: str,
    tags: List[str],
    category_id: int,
    default_language: str,
    privacy_status: str,
    contains_synthetic_media: bool,
    made_for_kids: bool,
) -> dict:
    """Construct the request body for ``youtube.videos().insert()``."""
    return {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": str(category_id),
            "defaultLanguage": default_language,
            "defaultAudioLanguage": default_language,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
            "containsSyntheticMedia": contains_synthetic_media,
            # Skip YouTube's gradual rollout to subscribers' homepages
            # (we have RSS + X for that). False = publish to subs feed.
            "publishToSubscriptions": True,
        },
    }


@retry(
    retry=retry_if_exception_type(Exception) & retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    reraise=True,
)
def _execute_resumable_upload(insert_request) -> dict:
    """Drive the chunked upload loop until the API returns a video resource.

    Tenacity wraps the whole call so a hard 5xx during chunk transfer
    gets retried from scratch with backoff. ``next_chunk`` itself does
    not retry — it returns ``(status, response)`` per chunk.
    """
    response = None
    while response is None:
        status, response = insert_request.next_chunk()
        if status:
            logger.info("YouTube upload progress: %d%%",
                        int(status.progress() * 100))
    return response


def upload_video(
    video_path: Path,
    *,
    credentials,
    title: str,
    description: str,
    tags: List[str],
    category_id: int,
    default_language: str = "en",
    privacy_status: str = "public",
    thumbnail_path: Optional[Path] = None,
    contains_synthetic_media: bool = True,
    made_for_kids: bool = False,
) -> str:
    """Upload a single video and (optionally) its custom thumbnail.

    Parameters
    ----------
    video_path:
        Local MP4 to upload.
    credentials:
        Refreshable :class:`google.oauth2.credentials.Credentials` —
        usually from :func:`get_channel_credentials_from_env`.
    title, description, tags, category_id, default_language:
        Snippet metadata. ``description`` may include the YouTube
        chapter block; YouTube parses it automatically when the format
        is right (first stamp ``0:00``, ≥ 2 stamps).
    privacy_status:
        ``"public"`` | ``"unlisted"`` | ``"private"``.
    thumbnail_path:
        Optional 1280x720 JPEG/PNG. Skipped silently when ``None``.
    contains_synthetic_media:
        Sets ``status.containsSyntheticMedia``. Defaults to ``True``
        because every Nerra Network episode uses synthesized voice.
    made_for_kids:
        ``status.selfDeclaredMadeForKids``. Default ``False``; flip per
        show in the YAML if a show is targeted at < 13.

    Returns
    -------
    str
        The canonical watch URL (``https://www.youtube.com/watch?v=…``).
    """
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    # Lazy imports so ``import engine.youtube`` works in environments
    # where the google libs aren't installed (e.g. fresh CI before
    # ``pip install -r requirements.txt``).
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=credentials,
                    cache_discovery=False)

    body = _build_video_body(
        title=title,
        description=description,
        tags=tags,
        category_id=category_id,
        default_language=default_language,
        privacy_status=privacy_status,
        contains_synthetic_media=contains_synthetic_media,
        made_for_kids=made_for_kids,
    )

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=8 * 1024 * 1024,
        resumable=True,
    )

    logger.info(
        "Uploading to YouTube: %s (%.1f MiB, privacy=%s, AI-disclosed)",
        video_path.name,
        video_path.stat().st_size / (1024 * 1024),
        privacy_status,
    )

    insert_request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = _execute_resumable_upload(insert_request)
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(
            f"YouTube upload returned no video id: {response!r}"
        )
    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info("Uploaded: %s", watch_url)

    if thumbnail_path and thumbnail_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=str(thumbnail_path),
            ).execute()
            logger.info("Thumbnail set for %s", video_id)
        except Exception as exc:  # pragma: no cover - thumbnail is best-effort
            logger.warning("Thumbnail upload failed (non-fatal): %s", exc)

    return watch_url
