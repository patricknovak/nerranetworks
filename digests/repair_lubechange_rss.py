#!/usr/bin/env python3
"""
Manual RSS feed repair script for Lube Change podcast.
Scans for existing MP3 files and adds any missing episodes to the RSS feed.
"""

import sys
from pathlib import Path

# Add parent directory to path to import lubechange functions
sys.path.insert(0, str(Path(__file__).parent.parent))

from digests.lubechange import (
    scan_existing_episodes_from_files,
    update_rss_feed,
    rss_path,
    digests_dir
)
import logging
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def main():
    """Repair RSS feed by adding any missing episodes."""
    print("=" * 80)
    print("LUBE CHANGE RSS FEED REPAIR")
    print("=" * 80)
    
    base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
    
    # Scan for existing episodes
    print("\nScanning for existing episode files...")
    existing_episodes = scan_existing_episodes_from_files(digests_dir, base_url)
    print(f"Found {len(existing_episodes)} episode file(s)")
    
    if not existing_episodes:
        print("No episode files found. Nothing to repair.")
        return
    
    # Parse RSS feed to see what episodes are already there
    rss_episodes = set()
    if rss_path.exists():
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find('channel')
            if channel is not None:
                for item in channel.findall('item'):
                    itunes_episode = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')
                    if itunes_episode is not None and itunes_episode.text:
                        try:
                            rss_episodes.add(int(itunes_episode.text))
                        except ValueError:
                            pass
        except Exception as e:
            logging.warning(f"Could not parse RSS feed: {e}")
    
    print(f"Found {len(rss_episodes)} episode(s) in RSS feed: {sorted(rss_episodes)}")
    
    # Find episodes that exist as files but not in RSS feed
    missing_episodes = [ep for ep in existing_episodes if ep['episode_num'] not in rss_episodes]
    
    if not missing_episodes:
        print("\n✅ All episodes are in the RSS feed. No repair needed.")
        return
    
    print(f"\n⚠️  Found {len(missing_episodes)} missing episode(s): {[ep['episode_num'] for ep in missing_episodes]}")
    
    # Add missing episodes to RSS feed
    for ep_data in missing_episodes:
        try:
            episode_title = f"Lube Change - Oilers Daily News - Episode {ep_data['episode_num']}"
            episode_description = f"Daily Edmonton Oilers news for {ep_data['date'].strftime('%B %d, %Y')}."
            
            print(f"\nAdding Episode {ep_data['episode_num']} to RSS feed...")
            update_rss_feed(
                rss_path=rss_path,
                episode_num=ep_data['episode_num'],
                episode_title=episode_title,
                episode_description=episode_description,
                episode_date=ep_data['date'],
                mp3_filename=ep_data['filename'],
                mp3_duration=ep_data['duration'],
                mp3_path=ep_data['path'],
                base_url=base_url
            )
            print(f"✅ Added Episode {ep_data['episode_num']} to RSS feed")
        except Exception as e:
            logging.error(f"❌ Failed to add Episode {ep_data['episode_num']}: {e}", exc_info=True)
    
    print("\n" + "=" * 80)
    print("RSS FEED REPAIR COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()

