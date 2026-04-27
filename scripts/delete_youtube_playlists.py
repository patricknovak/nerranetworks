#!/usr/bin/env python3
"""Delete YouTube playlists by ID. Used to clean up after the
``create_youtube_playlists.py`` script accidentally targeted the
wrong channel.

Reads the IDs from a JSON file produced by the create script
(``youtube_playlists_<channel>.json`` — a ``{slug: playlist_id}`` dict)
and deletes each one via the YouTube Data API.

You'll need to sign in with the **same channel** that owns the
playlists you want to delete (otherwise the API returns 403).

Usage::

    python3 scripts/delete_youtube_playlists.py client_secrets.json \
        youtube_playlists_en.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCOPES = ["https://www.googleapis.com/auth/youtube"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Delete YouTube playlists by ID.")
    p.add_argument("client_secrets", type=Path)
    p.add_argument("playlists_json", type=Path,
                   help="JSON file mapping show_slug → playlist_id (the "
                        "output of create_youtube_playlists.py).")
    p.add_argument("--port", type=int, default=0)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if not args.client_secrets.exists():
        sys.exit(f"client_secrets not found: {args.client_secrets}")
    if not args.playlists_json.exists():
        sys.exit(f"playlists_json not found: {args.playlists_json}")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except ImportError:
        sys.exit("Run `pip3 install google-api-python-client "
                 "google-auth-oauthlib` and try again.")

    ids = json.loads(args.playlists_json.read_text())
    if not ids:
        print("No IDs in the JSON. Nothing to delete.")
        return 0

    print(f"Will delete {len(ids)} playlists:")
    for slug, pid in ids.items():
        print(f"  - {slug:30s}  →  {pid}")
    print()
    print("Sign in with the channel that OWNS these playlists.")
    print("(If you ran create against Patrick Novak by mistake, sign in "
          "as Patrick Novak now.)\n")

    flow = InstalledAppFlow.from_client_secrets_file(
        str(args.client_secrets), SCOPES,
    )
    creds = flow.run_local_server(port=args.port, prompt="consent",
                                  access_type="offline")
    youtube = build("youtube", "v3", credentials=creds)

    me = youtube.channels().list(part="snippet", mine=True).execute()
    items = me.get("items", [])
    if items:
        print(f"Authorized channel: {items[0]['snippet']['title']}  "
              f"(id={items[0]['id']})\n")

    failed = {}
    deleted = []
    for slug, pid in ids.items():
        try:
            youtube.playlists().delete(id=pid).execute()
            print(f"  ✓ deleted  {slug}: {pid}")
            deleted.append(slug)
        except HttpError as exc:
            print(f"  ❌ failed   {slug}: {pid}  →  {exc}")
            failed[slug] = str(exc)

    print(f"\nDeleted {len(deleted)} of {len(ids)} playlists.")
    if failed:
        print(f"Failed: {list(failed.keys())}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
