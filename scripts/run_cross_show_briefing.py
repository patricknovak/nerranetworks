#!/usr/bin/env python3
"""Generate cross-show weekly intelligence briefing."""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.synthesizer import synthesize_cross_show_briefing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate cross-show intelligence briefing",
    )
    parser.add_argument("--date", type=str,
                        help="Week ending date YYYY-MM-DD (default: today)")
    parser.add_argument("--output-dir", type=str, default="outputs/briefings")
    args = parser.parse_args()

    week_ending = date.fromisoformat(args.date) if args.date else date.today()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Generating cross-show briefing for week ending %s", week_ending)

    briefing_md = synthesize_cross_show_briefing(week_ending)
    if not briefing_md:
        logger.warning("Insufficient data for cross-show briefing")
        return

    filename = f"nerra_intelligence_{week_ending.isoformat()}.md"
    (output_dir / filename).write_text(briefing_md, encoding="utf-8")
    logger.info("Saved: %s", output_dir / filename)


if __name__ == "__main__":
    main()
