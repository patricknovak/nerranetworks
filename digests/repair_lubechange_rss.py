#!/usr/bin/env python3
"""
Manual RSS feed repair script for Lube Change podcast.
Scans for existing MP3 files and adds any missing episodes to the RSS feed.
"""

import sys
import os
from pathlib import Path
import datetime
import re
import subprocess
import xml.etree.ElementTree as ET
import logging

# Add parent directory to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import feedgen
from feedgen.feed import FeedGenerator

# Set up paths
digests_dir = project_root / "digests" / "lubechange"
rss_path = project_root / "lubechange_podcast.rss"

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def get_audio_duration(path: Path) -> float:
    """Return duration in seconds for an audio file."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception as exc:
        logging.warning(f"Unable to determine duration for {path}: {exc}")
        return 0.0

def format_duration(seconds: float) -> str:
    """Format duration in seconds to HH:MM:SS or MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def scan_existing_episodes_from_files(digests_dir: Path, base_url: str) -> list:
    """Scan for existing episode MP3 files and return episode data."""
    episodes = []
    pattern = r"Lube_Change_Ep(\d+)_(\d{8})\.mp3"
    for mp3_file in digests_dir.glob("Lube_Change_Ep*.mp3"):
        match = re.match(pattern, mp3_file.name)
        if match:
            try:
                ep_num = int(match.group(1))
                date_str = match.group(2)
                episode_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                file_size = mp3_file.stat().st_size if mp3_file.exists() else 0
                duration = get_audio_duration(mp3_file)
                episodes.append({
                    'episode_num': ep_num,
                    'date': episode_date,
                    'filename': mp3_file.name,
                    'path': mp3_file,
                    'size': file_size,
                    'duration': duration,
                    'url': f"{base_url}/digests/lubechange/{mp3_file.name}"
                })
            except (ValueError, Exception) as e:
                logging.warning(f"Could not parse episode from file {mp3_file.name}: {e}")
    return sorted(episodes, key=lambda x: x['episode_num'])

def update_rss_feed(
    rss_path: Path,
    episode_num: int,
    episode_title: str,
    episode_description: str,
    episode_date: datetime.date,
    mp3_filename: str,
    mp3_duration: float,
    mp3_path: Path,
    base_url: str = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
):
    """Update or create RSS feed with new episode."""
    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    # Parse existing RSS feed
    existing_episodes = []
    if rss_path.exists():
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find('channel')
            if channel is not None:
                items = channel.findall('item')
                for item in items:
                    episode_data = {}
                    for elem in item:
                        if elem.tag == 'title':
                            episode_data['title'] = elem.text or ''
                        elif elem.tag == 'description':
                            episode_data['description'] = elem.text or ''
                        elif elem.tag == 'guid':
                            if elem.text:
                                episode_data['guid'] = elem.text.strip()
                        elif elem.tag == 'pubDate':
                            episode_data['pubDate'] = elem.text or ''
                        elif elem.tag == 'enclosure':
                            episode_data['enclosure'] = {
                                'url': elem.get('url', ''),
                                'type': elem.get('type', 'audio/mpeg'),
                                'length': elem.get('length', '0')
                            }
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}episode':
                            episode_data['itunes_episode'] = elem.text or ''
                    if episode_data.get('guid'):
                        existing_episodes.append(episode_data)
        except Exception as e:
            logging.warning(f"Could not parse existing RSS feed: {e}")
    
    # Deduplicate existing episodes by episode number
    episodes_by_number = {}
    for ep_data in existing_episodes:
        ep_num_str = ep_data.get('itunes_episode', '')
        if not ep_num_str:
            guid = ep_data.get('guid', '')
            match = re.search(r'ep(\d+)', guid)
            if match:
                ep_num_str = match.group(1)
        
        if ep_num_str:
            try:
                ep_num = int(ep_num_str)
                if ep_num not in episodes_by_number:
                    episodes_by_number[ep_num] = ep_data
                else:
                    existing_guid = episodes_by_number[ep_num].get('guid', '')
                    current_guid = ep_data.get('guid', '')
                    existing_ts = existing_guid.split('-')[-1] if '-' in existing_guid else '000000'
                    current_ts = current_guid.split('-')[-1] if '-' in current_guid else '000000'
                    if current_ts > existing_ts:
                        episodes_by_number[ep_num] = ep_data
            except ValueError:
                pass
    
    # Set channel metadata
    fg.title("Lube Change - Oilers Daily News")
    fg.link(href="https://github.com/patricknovak/Tesla-shorts-time")
    fg.description("Daily Edmonton Oilers news from Oil Country. Hosted by Jason Potter from Hinton, Alberta.")
    fg.language('en-us')
    fg.copyright(f"Copyright {datetime.date.today().year}")
    fg.podcast.itunes_author("Jason Potter")
    fg.podcast.itunes_summary("Daily Edmonton Oilers news from Oil Country. Your daily dose of Oilers news, game recaps, trades, and analysis.")
    fg.podcast.itunes_owner(name='Lube Change', email='contact@lubechange.com')
    fg.podcast.itunes_image(f"{base_url}/lubechange-podcast-image.jpg")
    fg.podcast.itunes_category("Sports")
    fg.podcast.itunes_explicit("no")
    
    # Add existing episodes (skip if same episode number)
    current_time_str = datetime.datetime.now().strftime("%H%M%S")
    new_episode_guid = f"lubechange-ep{episode_num:03d}-{episode_date:%Y%m%d}-{current_time_str}"
    
    for ep_data in episodes_by_number.values():
        ep_num_str = ep_data.get('itunes_episode', '')
        if not ep_num_str:
            guid = ep_data.get('guid', '')
            match = re.search(r'ep(\d+)', guid)
            if match:
                ep_num_str = match.group(1)
        
        if ep_num_str and int(ep_num_str) == episode_num:
            logging.info(f"Skipping existing episode {ep_num_str} - will be replaced with new version")
            continue
        
        if ep_data.get('guid') == new_episode_guid:
            continue
        
        entry = fg.add_entry()
        entry.id(ep_data.get('guid', ''))
        entry.title(ep_data.get('title', ''))
        entry.description(ep_data.get('description', ''))
        if ep_data.get('link'):
            entry.link(href=ep_data['link'])
        
        if ep_data.get('pubDate'):
            try:
                if isinstance(ep_data['pubDate'], datetime.datetime):
                    entry.pubDate(ep_data['pubDate'])
                else:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(ep_data['pubDate'])
                    entry.pubDate(pub_date)
            except Exception:
                pass
        
        if ep_data.get('enclosure'):
            enc = ep_data['enclosure']
            entry.enclosure(url=enc.get('url', ''), type=enc.get('type', 'audio/mpeg'), length=enc.get('length', '0'))
        
        if ep_data.get('itunes_title'):
            entry.podcast.itunes_title(ep_data['itunes_title'])
        if ep_data.get('itunes_summary'):
            entry.podcast.itunes_summary(ep_data['itunes_summary'])
        if ep_data.get('itunes_duration'):
            entry.podcast.itunes_duration(ep_data['itunes_duration'])
        if ep_data.get('itunes_episode'):
            entry.podcast.itunes_episode(ep_data['itunes_episode'])
        if ep_data.get('itunes_season'):
            entry.podcast.itunes_season(ep_data['itunes_season'])
        if ep_data.get('itunes_episode_type'):
            entry.podcast.itunes_episode_type(ep_data['itunes_episode_type'])
        entry.podcast.itunes_explicit("no")
        entry.podcast.itunes_image(f"{base_url}/lubechange-podcast-image.jpg")
    
    # Add new episode
    entry = fg.add_entry()
    entry.id(new_episode_guid)
    entry.title(episode_title)
    entry.description(episode_description)
    entry.link(href=f"{base_url}/digests/lubechange/{mp3_filename}")
    pub_date = datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc)
    entry.pubDate(pub_date)
    
    mp3_url = f"{base_url}/digests/lubechange/{mp3_filename}"
    mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
    entry.enclosure(url=mp3_url, type="audio/mpeg", length=str(mp3_size))
    
    entry.podcast.itunes_title(episode_title)
    entry.podcast.itunes_summary(episode_description)
    entry.podcast.itunes_duration(format_duration(mp3_duration))
    entry.podcast.itunes_episode(str(episode_num))
    entry.podcast.itunes_season("1")
    entry.podcast.itunes_episode_type("full")
    entry.podcast.itunes_explicit("no")
    entry.podcast.itunes_image(f"{base_url}/lubechange-podcast-image.jpg")
    
    fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))
    fg.rss_file(str(rss_path), pretty=True)
    logging.info(f"RSS feed updated → {rss_path}")

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

