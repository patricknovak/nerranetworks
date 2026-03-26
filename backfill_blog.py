#!/usr/bin/env python3
"""Backfill blog posts from existing episode digest markdown files.

Scans all shows' digest directories, converts each markdown episode to a
blog post HTML file, generates index pages, and builds blog RSS feeds.

Usage:
    python backfill_blog.py              # All shows
    python backfill_blog.py --show tesla # Single show
    python backfill_blog.py --dry-run    # Preview without writing
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def backfill_show(slug, *, dry_run=False):
    """Backfill blog posts for a single show."""
    from generate_html import (
        NETWORK_SHOWS,
        generate_blog_posts,
        generate_blog_index,
    )
    from engine.publisher import update_blog_rss

    if slug not in NETWORK_SHOWS:
        print(f"Error: unknown show '{slug}'")
        return []

    cfg = NETWORK_SHOWS[slug]
    print(f"\n{'='*60}")
    print(f"Backfilling blog: {cfg['name']} ({slug})")
    print(f"{'='*60}")

    # Generate all blog post HTML files
    results = generate_blog_posts(slug, dry_run=dry_run)
    posts = [meta for meta, _ in results]

    if not posts:
        print(f"  No episodes found for {slug}")
        return []

    print(f"  Generated {len(posts)} blog posts")

    # Generate blog index page
    generate_blog_index(slug, dry_run=dry_run, posts=posts)

    # Generate blog RSS feed
    if not dry_run:
        rss_path = ROOT / f"blog_{slug}.rss"
        update_blog_rss(
            rss_path,
            posts,
            channel_title=f"{cfg['name']} — Blog",
            channel_link=f"https://nerranetwork.com/blog/{slug}/index.html",
            channel_description=f"Blog posts from {cfg['name']} podcast episodes. {cfg.get('description', '')}",
            channel_image=cfg.get("podcast_image", ""),
            show_slug=slug,
        )
        print(f"  Blog RSS: {rss_path}")
    else:
        print(f"  [dry-run] Would write blog_{slug}.rss")

    return posts


def backfill_network_rss(all_posts, *, dry_run=False):
    """Generate the network-wide aggregated blog RSS."""
    from engine.publisher import update_blog_rss

    if not all_posts:
        return

    if dry_run:
        print(f"\n[dry-run] Would write blog.rss ({len(all_posts)} total entries)")
        return

    rss_path = ROOT / "blog.rss"
    update_blog_rss(
        rss_path,
        all_posts,
        channel_title="Nerra Network — Blog",
        channel_link="https://nerranetwork.com",
        channel_description="Blog posts from all Nerra Network podcast shows.",
        channel_image="assets/nerra-logo-icon.svg",
        show_slug="network",
    )
    print(f"\nNetwork blog RSS: {rss_path} ({len(all_posts)} entries)")


def main():
    parser = argparse.ArgumentParser(description="Backfill blog posts from episode digests.")
    parser.add_argument("--show", type=str, help="Backfill a single show by slug")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    args = parser.parse_args()

    from generate_html import NETWORK_SHOWS

    all_posts = []

    if args.show:
        posts = backfill_show(args.show, dry_run=args.dry_run)
        all_posts.extend(posts)
    else:
        for slug in NETWORK_SHOWS:
            posts = backfill_show(slug, dry_run=args.dry_run)
            all_posts.extend(posts)

    # Network-wide RSS
    backfill_network_rss(all_posts, dry_run=args.dry_run)

    print(f"\nDone! {len(all_posts)} total blog posts processed.")


if __name__ == "__main__":
    main()
