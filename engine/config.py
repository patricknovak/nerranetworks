"""Show configuration schema and YAML loader for the podcast pipeline.

Each show is defined by a YAML file under ``shows/``.  The ``load_config()``
function parses the YAML and returns a typed ``ShowConfig`` dataclass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclass hierarchy
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    url: str
    label: str = ""


@dataclass
class LLMConfig:
    provider: str = "xai"
    model: str = "grok-3"
    system_prompt_file: str = ""
    digest_prompt_file: str = ""
    podcast_prompt_file: str = ""
    digest_temperature: float = 0.7
    podcast_temperature: float = 0.7
    max_tokens: int = 3500


@dataclass
class TTSConfig:
    voice_id: str = "dTrBzPvD2GpAqkk1MUzA"
    model: str = "eleven_turbo_v2_5"
    stability: float = 0.65
    similarity_boost: float = 0.9
    style: float = 0.85
    use_speaker_boost: bool = True
    max_chars: int = 5000


@dataclass
class AudioConfig:
    music_file: Optional[str] = None
    background_music_file: Optional[str] = None
    intro_duration: float = 5.0
    overlap_duration: float = 3.0
    fade_duration: float = 18.0
    outro_duration: float = 30.0
    intro_volume: float = 0.6
    overlap_volume: float = 0.5
    fade_volume: float = 0.4
    outro_volume: float = 0.4
    voice_intro_delay: float = 0.0


@dataclass
class PublishingConfig:
    rss_file: str = "podcast.rss"
    rss_title: str = "Podcast"
    rss_description: str = ""
    rss_summary: str = ""
    rss_link: str = ""
    rss_author: str = "Patrick"
    rss_email: str = "contact@example.com"
    rss_image: str = ""
    rss_category: str = "Technology"
    rss_language: str = "en-us"
    guid_prefix: str = "podcast"
    base_url: str = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
    audio_subdir: str = "digests"
    summaries_json: str = "digests/summaries.json"
    summaries_podcast_name: str = ""
    player_html: str = ""
    summaries_html: str = ""
    x_enabled: bool = True
    x_env_prefix: str = "X_"
    x_teaser_template: str = ""
    x_hashtags: str = ""


@dataclass
class EpisodeConfig:
    prefix: str = "Podcast"
    filename_pattern: str = "{prefix}_Ep{num:03d}_{date:%Y%m%d_%H%M%S}.mp3"
    output_dir: str = "digests"
    mp3_glob: str = "*_Ep*.mp3"


@dataclass
class StorageConfig:
    provider: str = "github"  # "github" (default) or "r2"
    bucket: str = "podcast-audio"
    endpoint_env: str = "R2_ENDPOINT_URL"
    access_key_env: str = "R2_ACCESS_KEY_ID"
    secret_key_env: str = "R2_SECRET_ACCESS_KEY"
    public_base_url: str = ""


@dataclass
class ShowConfig:
    name: str = ""
    slug: str = ""
    description: str = ""
    sources: List[SourceConfig] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    publishing: PublishingConfig = field(default_factory=PublishingConfig)
    episode: EpisodeConfig = field(default_factory=EpisodeConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _build_sources(raw: list) -> List[SourceConfig]:
    """Convert a list of dicts or strings into SourceConfig objects."""
    sources = []
    for item in raw or []:
        if isinstance(item, str):
            sources.append(SourceConfig(url=item))
        elif isinstance(item, dict):
            sources.append(SourceConfig(url=item.get("url", ""), label=item.get("label", "")))
    return sources


def _build_nested(cls, raw: dict):
    """Instantiate a dataclass from a dict, ignoring unknown keys."""
    if not raw or not isinstance(raw, dict):
        return cls()
    known = {f.name for f in cls.__dataclass_fields__.values()}
    return cls(**{k: v for k, v in raw.items() if k in known})


def load_config(yaml_path: str | Path) -> ShowConfig:
    """Load a show configuration from a YAML file.

    Parameters
    ----------
    yaml_path:
        Path to a YAML file (absolute or relative to cwd).

    Returns
    -------
    ShowConfig
        Fully populated config with defaults for any missing fields.
    """
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    config = ShowConfig(
        name=data.get("name", ""),
        slug=data.get("slug", ""),
        description=data.get("description", ""),
        sources=_build_sources(data.get("sources")),
        keywords=data.get("keywords", []),
        llm=_build_nested(LLMConfig, data.get("llm")),
        tts=_build_nested(TTSConfig, data.get("tts")),
        audio=_build_nested(AudioConfig, data.get("audio")),
        publishing=_build_nested(PublishingConfig, data.get("publishing")),
        episode=_build_nested(EpisodeConfig, data.get("episode")),
        storage=_build_nested(StorageConfig, data.get("storage")),
    )
    logger.info("Loaded config for '%s' from %s", config.name, path)
    return config
