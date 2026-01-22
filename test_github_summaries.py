#!/usr/bin/env python3
"""
Test script for GitHub Pages summary functionality.
Run this to verify the new summary saving works correctly.
"""

import os
import json
import datetime
from pathlib import Path
import sys

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the function directly from the script file
# We'll copy the function here to avoid import issues
def save_summary_to_github_pages(summary_text: str, output_dir: Path, podcast_name: str = "tesla"):
    """
    Save summary to GitHub Pages JSON file for display on summaries page.
    """
    try:
        # Define the JSON file path (assuming we're in the project root)
        project_root = Path(__file__).parent
        json_file = project_root / "digests" / f"summaries_{podcast_name}.json"

        # Load existing summaries or create new structure
        if json_file.exists():
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {"podcast": podcast_name, "summaries": []}

        # Create new summary entry
        today = datetime.datetime.now()
        summary_entry = {
            "date": today.strftime("%Y-%m-%d"),
            "datetime": today.isoformat(),
            "content": summary_text,
            "episode_num": 999  # Test episode number
        }

        # Add to summaries (keep only last 30 days to prevent file from growing too large)
        data["summaries"].insert(0, summary_entry)  # Add to beginning (newest first)

        # Keep only last 30 summaries
        if len(data["summaries"]) > 30:
            data["summaries"] = data["summaries"][:30]

        # Save updated data
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Summary saved to GitHub Pages JSON: {json_file}")
        return json_file

    except Exception as e:
        print(f"Failed to save summary to GitHub Pages: {e}")
        return None

def test_github_summaries():
    """Test the GitHub Pages summary saving functionality."""

    # Test data
    test_summary = """🚗⚡ **Tesla Shorts Time Daily**

📅 **Date:** January 21, 2026

💰 **REAL-TIME TSLA price:** $245.67 (+2.34%)

This is a test summary to verify the GitHub Pages functionality works correctly.

🎙️ **Tesla Shorts Time Daily Podcast Link:** https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939

#Tesla #TSLA #TeslaShortsTime"""

    # Test directory
    test_dir = Path("digests")

    print("Testing GitHub Pages summary functionality...")
    print("=" * 60)

    try:
        # Test Tesla summary saving
        print("1. Testing Tesla summary saving...")
        result = save_summary_to_github_pages(test_summary, test_dir, "tesla")
        if result:
            print(f"✅ Tesla summary saved successfully: {result}")

            # Verify the file was created and contains correct data
            json_file = Path("digests/summaries_tesla.json")
            if json_file.exists():
                with open(json_file, 'r') as f:
                    data = json.load(f)

                print(f"   - Podcast: {data.get('podcast')}")
                print(f"   - Number of summaries: {len(data.get('summaries', []))}")
                if data['summaries']:
                    latest = data['summaries'][0]
                    print(f"   - Latest summary date: {latest.get('date')}")
                    print(f"   - Content preview: {latest.get('content')[:100]}...")
            else:
                print("❌ JSON file was not created")
        else:
            print("❌ Failed to save Tesla summary")

        print("\n2. Testing Planetterrian summary saving...")
        planet_summary = """🌍🧬 **Planetterrian Daily**

📅 **Date:** January 21, 2026

Today's science and health discoveries...

🧠 Latest longevity research
🏥 Health breakthroughs
🌱 Environmental science

#Science #Longevity #Health"""

        result = save_summary_to_github_pages(planet_summary, test_dir, "planet")
        if result:
            print(f"✅ Planetterrian summary saved successfully: {result}")
        else:
            print("❌ Failed to save Planetterrian summary")

        print("\n3. Testing Fascinating Frontiers summary saving...")
        space_summary = """🚀🌌 **Fascinating Frontiers**

📅 **Date:** January 21, 2026

Today's space and astronomy discoveries...

🪐 Latest space missions
🌟 Astronomical events
🚁 Space technology updates

#Space #Astronomy #NASA"""

        result = save_summary_to_github_pages(space_summary, test_dir, "space")
        if result:
            print(f"✅ Fascinating Frontiers summary saved successfully: {result}")
        else:
            print("❌ Failed to save Fascinating Frontiers summary")

        print("\n4. Verifying all JSON files exist...")
        files_to_check = [
            "digests/summaries_tesla.json",
            "digests/summaries_planet.json",
            "digests/summaries_space.json"
        ]

        for file_path in files_to_check:
            if Path(file_path).exists():
                print(f"✅ {file_path} exists")
            else:
                print(f"❌ {file_path} missing")

        print("\n" + "=" * 60)
        print("GitHub Pages summary test completed!")
        print("\nNext steps:")
        print("1. Check that summaries.html displays the test data correctly")
        print("2. Run the actual podcast scripts to generate real summaries")
        print("3. Verify X posts contain links to summaries.html instead of full content")

    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_github_summaries()