#!/usr/bin/env python3
"""
Universal Digest Poster
Run with: python post_digest.py tesla
          python post_digest.py planet
          python post_digest.py space
          python post_digest.py omni
          python post_digest.py all
"""

import sys
import subprocess

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python post_digest.py [tesla | planet | space | omni | all]")
        sys.exit(1)

    choice = sys.argv[1].lower()

    if choice in ["tesla", "all"]:
        print("Posting Tesla Shorts Time...")
        # Run Tesla script directly
        result = subprocess.run([sys.executable, "digests/tesla_shorts_time.py"], cwd=".")
        if result.returncode != 0:
            print("Tesla posting failed")

    if choice in ["planet", "all"]:
        print("Posting Planetterrian Daily...")
        # Run Planetterrian script directly
        result = subprocess.run([sys.executable, "digests/planetterrian.py"], cwd=".")
        if result.returncode != 0:
            print("Planetterrian posting failed")

    if choice in ["space", "all"]:
        print("Posting Fascinating Frontiers...")
        # Run Fascinating Frontiers script directly
        result = subprocess.run([sys.executable, "digests/fascinating_frontiers.py"], cwd=".")
        if result.returncode != 0:
            print("Fascinating Frontiers posting failed")

    if choice in ["omni", "all"]:
        print("Posting Omni View...")
        # Run Omni View script directly
        result = subprocess.run([sys.executable, "digests/omni_view.py"], cwd=".")
        if result.returncode != 0:
            print("Omni View posting failed")

    print("All done. The future just got brighter. ⚡️🚀🧬⚖️")