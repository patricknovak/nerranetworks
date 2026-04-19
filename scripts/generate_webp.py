#!/usr/bin/env python3
"""Generate WebP variants of all cover art in assets/covers/.

For each JPG in ``assets/covers/``, writes ``<name>.webp`` at full size
and ``<name>-800.webp``, ``<name>-400.webp`` at responsive widths.
Keeps the source JPG untouched so <picture> can fall back.

Idempotent: skips regeneration when the WebP is newer than the source JPG.

Typical saving: ~65% file size vs JPG at equivalent visual quality.
"""

from __future__ import annotations

import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
COVERS_DIR = ROOT / "assets" / "covers"

# Responsive widths + quality settings. Podcast directories require
# >= 1400 square cover art, so 1400 is our "full" size.
TARGETS = [
    # (suffix, max_dimension_px, quality)
    ("",       1400, 82),   # full-size (same filename, .webp extension)
    ("-800",    800, 80),
    ("-400",    400, 78),
]


def convert(src: Path) -> list[Path]:
    """Convert one JPG to all WebP variants. Returns list of written paths."""
    written = []
    with Image.open(src) as im:
        im = im.convert("RGB")
        src_mtime = src.stat().st_mtime
        for suffix, max_dim, quality in TARGETS:
            dst = src.with_name(f"{src.stem}{suffix}.webp")
            if dst.exists() and dst.stat().st_mtime >= src_mtime:
                continue  # up to date

            # Resize if the source is larger than the target
            if im.width > max_dim or im.height > max_dim:
                resized = im.copy()
                resized.thumbnail((max_dim, max_dim), Image.LANCZOS)
            else:
                resized = im

            resized.save(dst, "WEBP", quality=quality, method=6)
            written.append(dst)
            print(f"  wrote {dst.name} ({dst.stat().st_size // 1024} KB)")
    return written


def main():
    if not COVERS_DIR.exists():
        print(f"error: covers dir not found: {COVERS_DIR}", file=sys.stderr)
        sys.exit(1)

    jpgs = sorted(COVERS_DIR.glob("*.jpg"))
    if not jpgs:
        print(f"no JPGs found in {COVERS_DIR}")
        return

    total_written = 0
    total_saved = 0
    for jpg in jpgs:
        print(f"{jpg.name}  ({jpg.stat().st_size // 1024} KB JPG)")
        results = convert(jpg)
        total_written += len(results)
        for p in results:
            total_saved += jpg.stat().st_size - p.stat().st_size

    print()
    print(f"Done. {total_written} WebP files written. "
          f"~{max(0, total_saved) // 1024} KB total saved vs source JPGs.")


if __name__ == "__main__":
    main()
