"""Pexels-backed scene-image fetcher for the YouTube long-form pipeline.

Replaces the static-cover background with a slideshow of royalty-free
photos relevant to the show's topic. The keyword set comes straight
from each show's YAML ``keywords:`` list, so the operator never has
to curate per-show artwork — TST gets Tesla / EV photos, Fascinating
Frontiers gets space photos, Финансы Просто gets finance photos,
etc.

Why Pexels:

  - Free tier covers 200 req/hour, 20k/month. We use ≤ 10 req/day
    across all shows. Way under the cap.
  - All photos are royalty-free with no attribution legally required
    (Pexels License). We add credits in the video description anyway
    because it's polite and signals to YouTube we sourced legitimately.
  - Their search returns recent, varied photos for common topics.

If ``PEXELS_API_KEY`` isn't set, or the API call fails, the function
falls back to the show's static cover image — the long-form pipeline
keeps working, just less visually varied.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class Scene:
    """One scene image plus its attribution metadata."""
    path: Path
    photographer: str = ""
    photographer_url: str = ""
    pexels_url: str = ""

    def attribution_line(self) -> str:
        """One-line credit suitable for the video description."""
        if not self.photographer:
            return ""
        if self.photographer_url:
            return f"Photo by {self.photographer} ({self.photographer_url})"
        return f"Photo by {self.photographer}"


@dataclass
class SceneSet:
    """Collection of scenes for one episode + cache metadata."""
    scenes: List[Scene] = field(default_factory=list)
    is_fallback: bool = False  # True when we returned the cover only

    def __len__(self) -> int:
        return len(self.scenes)

    def paths(self) -> List[Path]:
        return [s.path for s in self.scenes]

    def attribution_lines(self) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for scene in self.scenes:
            line = scene.attribution_line()
            if line and line not in seen:
                seen.add(line)
                out.append(line)
        return out


# ---------------------------------------------------------------------------
# Pexels client
# ---------------------------------------------------------------------------

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
DEFAULT_PHOTO_COUNT = 8
DEFAULT_KEYWORDS_PER_QUERY = 5


@retry(
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=15),
    reraise=True,
)
def _pexels_search(query: str, *, api_key: str,
                   per_page: int = 3) -> dict:
    """Run one Pexels search request. Retries transient network errors."""
    response = requests.get(
        PEXELS_SEARCH_URL,
        params={
            "query": query,
            "per_page": per_page,
            "orientation": "landscape",
            "size": "large",
        },
        headers={"Authorization": api_key},
        timeout=15,
    )
    response.raise_for_status()
    return response.json() or {}


def _download_image(url: str, dest: Path) -> Optional[Path]:
    """Download a single image. Returns None if the download fails."""
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        return dest
    except (requests.RequestException, OSError) as exc:
        logger.warning("Failed to download %s: %s", url, exc)
        return None


def _select_keywords(keywords: List[str],
                     limit: int = DEFAULT_KEYWORDS_PER_QUERY) -> List[str]:
    """Pick the *limit* most useful keywords for image search.

    Single-word, lowercase, deduped. Skips boilerplate tokens that
    are technical jargon ('hw4', 'lfp', 'fsd' etc. — Pexels gets
    nothing useful for those).
    """
    # Skip technical SKUs / acronyms that return junk on Pexels.
    skip_too_short = {
        "ai", "hw", "lfp", "ev", "fsd", "tsla", "hw4", "hw5",
        "ai5", "ipo", "etf", "gic", "tfsa", "rrsp",
    }
    seen: set = set()
    out: List[str] = []
    for kw in keywords:
        if not isinstance(kw, str):
            continue
        clean = kw.strip().lower()
        if not clean or clean in seen or clean in skip_too_short:
            continue
        # Skip obvious technical SKUs / acronyms (only digits or 2-3 char tokens).
        if clean.isdigit() or (len(clean) <= 3 and clean.isalpha() and clean.isupper()):
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_dir(work_dir: Path, episode_num: int) -> Path:
    return work_dir / f"scenes_ep{episode_num:03d}"


def _manifest_path(cache_dir: Path) -> Path:
    return cache_dir / "manifest.json"


def _load_cached_scenes(cache_dir: Path) -> Optional[SceneSet]:
    """Return a cached SceneSet if every file referenced still exists."""
    manifest = _manifest_path(cache_dir)
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    scenes: List[Scene] = []
    for entry in data.get("scenes", []):
        path = Path(entry.get("path", ""))
        if not path.exists():
            return None  # cache invalid; refetch
        scenes.append(Scene(
            path=path,
            photographer=entry.get("photographer", ""),
            photographer_url=entry.get("photographer_url", ""),
            pexels_url=entry.get("pexels_url", ""),
        ))
    if not scenes:
        return None
    return SceneSet(scenes=scenes, is_fallback=bool(data.get("is_fallback")))


def _save_manifest(cache_dir: Path, scene_set: SceneSet) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "is_fallback": scene_set.is_fallback,
        "scenes": [
            {
                "path": str(s.path),
                "photographer": s.photographer,
                "photographer_url": s.photographer_url,
                "pexels_url": s.pexels_url,
            }
            for s in scene_set.scenes
        ],
    }
    _manifest_path(cache_dir).write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_scene_images(
    *,
    work_dir: Path,
    episode_num: int,
    keywords: List[str],
    fallback_cover: Path,
    api_key: Optional[str] = None,
    target_count: int = DEFAULT_PHOTO_COUNT,
) -> SceneSet:
    """Fetch a slideshow of royalty-free photos for the episode.

    Parameters
    ----------
    work_dir:
        Per-episode YouTube work directory (typically
        ``digests/<slug>/youtube_tmp``). Cache lives at
        ``work_dir/scenes_ep<NNN>/``.
    episode_num:
        Episode number — keys the cache so reruns don't re-fetch.
    keywords:
        Show YAML's ``keywords:`` list. We pick the most useful 5,
        query each, and dedupe results.
    fallback_cover:
        Path to the show's cover JPG. Used as the only scene if
        Pexels is disabled / unavailable / returns nothing.
    api_key:
        Pexels API key. Defaults to ``PEXELS_API_KEY`` env var. When
        empty, we return a fallback ``SceneSet`` containing only
        ``fallback_cover``.
    target_count:
        Target number of distinct photos. Stops querying once we
        have at least this many.

    Returns
    -------
    SceneSet
        Always non-empty (worst case: just the cover).
    """
    if api_key is None:
        api_key = os.getenv("PEXELS_API_KEY", "").strip()

    cache_dir = _cache_dir(work_dir, episode_num)
    cached = _load_cached_scenes(cache_dir)
    if cached is not None:
        logger.info("Using cached scene set from %s (%d photos)",
                    cache_dir, len(cached))
        return cached

    if not api_key:
        logger.info("PEXELS_API_KEY not set — using show cover as the "
                    "single scene")
        scene_set = SceneSet(
            scenes=[Scene(path=fallback_cover)],
            is_fallback=True,
        )
        _save_manifest(cache_dir, scene_set)
        return scene_set

    if not fallback_cover.exists():
        # The cover is required as a last-resort fallback; if the file
        # is missing the caller has bigger problems and shouldn't have
        # called us.
        raise FileNotFoundError(f"fallback_cover missing: {fallback_cover}")

    selected = _select_keywords(keywords)
    if not selected:
        logger.info("No usable keywords for slideshow — using cover")
        scene_set = SceneSet(scenes=[Scene(path=fallback_cover)],
                             is_fallback=True)
        _save_manifest(cache_dir, scene_set)
        return scene_set

    cache_dir.mkdir(parents=True, exist_ok=True)
    scenes: List[Scene] = []
    seen_pexels_ids: set = set()

    for query in selected:
        if len(scenes) >= target_count:
            break
        try:
            payload = _pexels_search(query, api_key=api_key, per_page=3)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", "?")
            logger.warning("Pexels search '%s' failed (HTTP %s)", query, status)
            continue
        except Exception as exc:  # noqa: BLE001 — we want to never crash here
            logger.warning("Pexels search '%s' errored: %s", query, exc)
            continue

        for photo in payload.get("photos", []) or []:
            if len(scenes) >= target_count:
                break
            photo_id = photo.get("id")
            if not photo_id or photo_id in seen_pexels_ids:
                continue
            src = photo.get("src") or {}
            image_url = src.get("large2x") or src.get("large") or src.get("original")
            if not image_url:
                continue
            ext = Path(image_url.split("?")[0]).suffix or ".jpg"
            # Filename keys by photo id so cache hits across keywords work.
            filename = f"pexels_{photo_id}{ext}"
            dest = cache_dir / filename
            if not dest.exists():
                downloaded = _download_image(image_url, dest)
                if downloaded is None:
                    continue
            scenes.append(Scene(
                path=dest,
                photographer=str(photo.get("photographer", "")).strip(),
                photographer_url=str(photo.get("photographer_url", "")).strip(),
                pexels_url=str(photo.get("url", "")).strip(),
            ))
            seen_pexels_ids.add(photo_id)

    if not scenes:
        logger.info("Pexels returned no usable photos — using cover")
        scene_set = SceneSet(scenes=[Scene(path=fallback_cover)],
                             is_fallback=True)
    else:
        scene_set = SceneSet(scenes=scenes, is_fallback=False)
        logger.info(
            "Built %d-photo slideshow for ep%d (queries: %s)",
            len(scenes), episode_num, ", ".join(selected),
        )

    _save_manifest(cache_dir, scene_set)
    return scene_set


def keyword_cache_key(keywords: List[str]) -> str:
    """Stable hash of the keyword list. Used for cache invalidation.

    Currently informational — the per-episode cache key already
    keys on the episode number, but if a show's keywords change
    mid-episode we want manual invalidation to be a single delete.
    """
    return hashlib.sha1(
        ",".join(sorted(k.lower() for k in keywords)).encode("utf-8"),
    ).hexdigest()[:8]
