#!/usr/bin/env python3
"""
Lube Change - Oilers Daily News – FULL AUTO X + PODCAST MACHINE
Daily Edmonton Oilers News Digest (Patrick in Vancouver, Canada)
Auto-published to X — December 2025+
"""

import os
import sys
import logging
import datetime
import subprocess
import requests
import tempfile
import html
import json
import re
import xml.etree.ElementTree as ET
from feedgen.feed import FeedGenerator
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
import tweepy
import shutil
import base64

# ========================== LOGGING ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# ========================== CONFIGURATION ==========================
# Set to True to test digest generation only (skips podcast and X posting)
TEST_MODE = False  # Set to False for full run

# Set to False to disable X posting (thread will still be generated and saved)
ENABLE_X_POSTING = True

# Set to False to disable podcast generation and RSS feed updates
ENABLE_PODCAST = True

# Link validation is currently disabled - validation functions have been removed
# Set to True and re-implement validation functions if needed in the future
ENABLE_LINK_VALIDATION = False


# ========================== NUMBER TO WORDS CONVERTER ==========================
def number_to_words(num: float) -> str:
    """
    Convert numbers to words for better TTS pronunciation.
    Handles integers and decimals.
    """
    # Define digit names for decimal conversion
    digit_names = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
    
    def convert_under_1000(n):
        """Convert numbers under 1000 to words."""
        ones = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
                'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
                'seventeen', 'eighteen', 'nineteen']
        tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
        
        if n == 0:
            return 'zero'
        if n < 20:
            return ones[n]
        if n < 100:
            return tens[n // 10] + ('-' + ones[n % 10] if n % 10 else '')
        if n < 1000:
            result = ones[n // 100] + ' hundred'
            remainder = n % 100
            if remainder:
                result += ' ' + convert_under_1000(remainder)
            return result
        return str(n)
    
    # Handle negative numbers
    is_negative = num < 0
    num = abs(num)
    
    # Split into integer and decimal parts
    integer_part = int(num)
    decimal_part = num - integer_part
    
    # Convert integer part
    if integer_part == 0:
        result = 'zero'
    elif integer_part < 1000:
        result = convert_under_1000(integer_part)
    elif integer_part < 1000000:
        thousands = integer_part // 1000
        remainder = integer_part % 1000
        result = convert_under_1000(thousands) + ' thousand'
        if remainder:
            result += ' ' + convert_under_1000(remainder)
    else:
        # For very large numbers, just return the number (TTS usually handles these)
        result = str(integer_part)
    
    # Convert decimal part
    if decimal_part > 0:
        # Convert decimal to words (e.g., 0.17 -> "point one seven")
        decimal_str = f"{decimal_part:.10f}".rstrip('0').rstrip('.')
        if '.' in decimal_str:
            decimal_digits = decimal_str.split('.')[1]
            decimal_words = ' '.join([digit_names[int(d)] if d.isdigit() and int(d) < 10 else d for d in decimal_digits])
            result += ' point ' + decimal_words
    
    return ('negative ' if is_negative else '') + result

# ========================== PRONUNCIATION FIXER v4 – COMPREHENSIVE HOCKEY TERMS ==========================
# Note: Import will be set up after project_root is defined
USE_SHARED_PRONUNCIATION = False

def fix_pronunciation(text: str) -> str:
    """
    Comprehensive pronunciation fixer for hockey/Oilers content.
    Handles acronyms, scores, player numbers, statistics, and common hockey terms
    for optimal TTS pronunciation on Cartesia.
    
    IMPORTANT: This function preserves sentence structure and natural speech patterns.
    """
    import re

    # Comprehensive list of hockey acronyms and terms
    acronyms = {
        # League acronyms
        "NHL": "N H L",
        "NHLPA": "N H L P A",
        "AHL": "A H L",
        "WHL": "W H L",
        "OHL": "O H L",
        "QMJHL": "Q M J H L",
        "ECHL": "E C H L",
        "USHL": "U S H L",
        "NCAA": "N C A A",
        # Game situations
        "PP": "power play",
        "PK": "penalty kill",
        "SHG": "short-handed goal",
        "PPG": "power play goal",
        "ENG": "empty net goal",
        "OT": "overtime",
        # "SO" removed - let it stay as "SO" (or "so") naturally
        "3v3": "three on three",
        "5v5": "five on five",
        "4v4": "four on four",
        # Statistics
        "GAA": "goals against average",
        "SV%": "save percentage",
        "SV": "save percentage",
        "PIM": "penalty minutes",
        "TOI": "time on ice",
        "CF%": "Corsi for percentage",
        "xGF": "expected goals for",
        "xGA": "expected goals against",
        "HDCF": "high danger chances for",
        "HDCA": "high danger chances against",
        "PDO": "P D O",
        "GF": "goals for",
        "GA": "goals against",
        "GF%": "goals for percentage",
        # Positions - Only convert when they appear in hockey context (e.g., "C" position, not just letter "C")
        # These are less likely to appear as standalone words in natural speech, but we'll be careful
        "LW": "left wing",
        "RW": "right wing",
        # Common terms
        "OTL": "overtime loss",
        # "SOL" removed - let it stay as "SOL" naturally
        "PTS": "points",
        "GP": "games played",
        # Single letters removed to prevent unwanted conversions:
        # "C", "D", "G", "F", "W", "L", "P" - these can appear naturally in text
        # and shouldn't be converted unless in specific hockey stat context
        "A": "A",  # Don't convert "A" to "assists" - we want to avoid that word
        "+/-": "plus minus",
        "S%": "shooting percentage",
        "FO%": "faceoff percentage",
        "HIT": "hits",
        "BLK": "blocks",
        "TK": "takeaways",
        "GV": "giveaways",
    }

    # Team name pronunciations (common mispronunciations)
    team_names = {
        "Oilers": "Oilers",
        "Flames": "Flames",
        "Canucks": "Canucks",
        "Maple Leafs": "Maple Leafs",
        "Canadiens": "Canadiens",
        "Avalanche": "Avalanche",
        "Golden Knights": "Golden Knights",
        "Kraken": "Kraken",
        "Sharks": "Sharks",
        "Kings": "Kings",
        "Ducks": "Ducks",
    }
    
    # Comprehensive Oilers pronunciation dictionary
    # Current players (2024-2025 season)
    oilers_players = {
        # Forwards
        "Connor McDavid": "Connor Mc David",
        "McDavid": "Mc David",
        "Leon Draisaitl": "Lee on Dry sight el",
        "Draisaitl": "Dry sight el",
        "Ryan Nugent-Hopkins": "Ryan Nugent Hopkins",
        "Nugent-Hopkins": "Nugent Hopkins",
        "Nugent Hopkins": "Nugent Hopkins",
        "Zach Hyman": "Zach High man",
        "Hyman": "High man",
        "Evander Kane": "Ee van der Kane",
        "Kane": "Kane",
        "Warren Foegele": "Warren Foe glee",
        "Foegele": "Foe glee",
        "Ryan McLeod": "Ryan Mc Leod",
        "McLeod": "Mc Leod",
        "Derek Ryan": "Derek Ryan",
        "Mattias Janmark": "Mat tee as Jan mark",
        "Janmark": "Jan mark",
        "Connor Brown": "Connor Brown",
        "Adam Henrique": "Adam Hen reek",
        "Henrique": "Hen reek",
        "Corey Perry": "Corey Perry",
        "Sam Carrick": "Sam Car rick",
        "Carrick": "Car rick",
        "Sam Gagner": "Sam Gag ner",
        "Gagner": "Gag ner",
        "Dylan Holloway": "Dylan Hol low way",
        "Holloway": "Hol low way",
        
        # Defensemen
        "Darnell Nurse": "Dar nell Nurse",
        "Nurse": "Nurse",
        "Evan Bouchard": "Ee van Boo shard",
        "Bouchard": "Boo shard",
        "Mattias Ekholm": "Mat tee as Ek holm",
        "Ekholm": "Ek holm",
        "Cody Ceci": "Cody See see",
        "Ceci": "See see",
        "Brett Kulak": "Brett Koo lak",
        "Kulak": "Koo lak",
        "Vincent Desharnais": "Vin cent Desh ar nay",
        "Desharnais": "Desh ar nay",
        "Philip Broberg": "Philip Bro berg",
        "Broberg": "Bro berg",
        "Troy Stecher": "Troy Stech er",
        "Stecher": "Stech er",
        
        # Goaltenders
        "Stuart Skinner": "Stu art Skin ner",
        "Skinner": "Skin ner",
        "Calvin Pickard": "Cal vin Pick ard",
        "Pickard": "Pick ard",
        "Jack Campbell": "Jack Camp bell",
        "Campbell": "Camp bell",
    }
    
    # Coaches and Management
    oilers_staff = {
        "Kris Knoblauch": "Kris Nob lock",
        "Knoblauch": "Nob lock",
        "Jay Woodcroft": "Jay Wood croft",
        "Woodcroft": "Wood croft",
        "Ken Holland": "Ken Hol land",
        "Holland": "Hol land",
        "Jeff Jackson": "Jeff Jack son",
        "Jackson": "Jack son",
        "Glen Gulutzan": "Glen Gu lut zan",
        "Gulutzan": "Gu lut zan",
        "Mark Stuart": "Mark Stu art",
        "Stuart": "Stu art",
        "Paul Coffey": "Paul Cof fee",
        "Coffey": "Cof fee",
    }
    
    # Historical Oilers players
    oilers_historical = {
        "Wayne Gretzky": "Wayne Gretz key",
        "Gretzky": "Gretz key",
        "Mark Messier": "Mark Mess ee ay",
        "Messier": "Mess ee ay",
        "Jari Kurri": "Jar ee Kur ee",
        "Kurri": "Kur ee",
        "Grant Fuhr": "Grant Fur",
        "Fuhr": "Fur",
        "Glenn Anderson": "Glen An der son",
        "Anderson": "An der son",
        "Kevin Lowe": "Kevin Low",
        "Lowe": "Low",
        "Esa Tikkanen": "Ee sa Tik ka nen",
        "Tikkanen": "Tik ka nen",
        "Craig MacTavish": "Craig Mac Tav ish",
        "MacTavish": "Mac Tav ish",
        "Charlie Huddy": "Charlie Hud dy",
        "Huddy": "Hud dy",
        "Randy Gregg": "Randy Gregg",
        "Gregg": "Gregg",
        "Dave Semenko": "Dave Se men ko",
        "Semenko": "Se men ko",
        "Dave Hunter": "Dave Hunt er",
        "Hunter": "Hunt er",
        "Pat Hughes": "Pat Hughes",
        "Hughes": "Hughes",
        "Jaroslav Pouzar": "Jar o slav Pou zar",
        "Pouzar": "Pou zar",
        "Mike Krushelnyski": "Mike Kru shel nis ki",
        "Krushelnyski": "Kru shel nis ki",
        "Steve Smith": "Steve Smith",
        "Smith": "Smith",
        "Jeff Beukeboom": "Jeff Boo ke boom",
        "Beukeboom": "Boo ke boom",
        "Bill Ranford": "Bill Ran ford",
        "Ranford": "Ran ford",
        "Andy Moog": "Andy Moog",
        "Moog": "Moog",
        "Ryan Smyth": "Ryan Smyth",
        "Smyth": "Smyth",
        "Doug Weight": "Doug Weight",
        "Weight": "Weight",
        "Jason Arnott": "Jason Ar nott",
        "Arnott": "Ar nott",
        "Curtis Joseph": "Curtis Jo seph",
        "Joseph": "Jo seph",
        "Tommy Salo": "Tommy Sa lo",
        "Salo": "Sa lo",
        "Ales Hemsky": "A les Hem ski",
        "Hemsky": "Hem ski",
        "Shawn Horcoff": "Shawn Hor coff",
        "Horcoff": "Hor coff",
        "Fernando Pisani": "Fer nan do Pi sa ni",
        "Pisani": "Pi sa ni",
        "Dwayne Roloson": "Dwayne Ro lo son",
        "Roloson": "Ro lo son",
    }
    
    # Combine all Oilers-related names
    player_names = {**oilers_players, **oilers_staff, **oilers_historical}
    
    # Common word pronunciations that TTS struggles with
    word_pronunciations = {
        "Years": "Years",  # Keep as-is, ensure it's not being modified
        "years": "years",
        "Lives": "Lives",  # Keep as-is
        "lives": "lives",
        "Planetterrian": "Planet terry an",  # Break into syllables
        "planetterrian": "planet terry an",
        "shootout": "shoot out",  # Ensure two words
        "shoot-out": "shoot out",
        "shoot out": "shoot out",
    }
    
    # Fix NHL - say it naturally as "N H L" (already handled above, but ensure it's clear)
    # NHL is already in acronyms dict, but we want to make sure it's pronounced clearly

    # Fix acronyms (must be whole words) - use spaces instead of ZWJ for better TTS
    for acronym, spelled in acronyms.items():
        pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
        if ' ' in spelled:
            # For phrases like "power play", use as-is
            replacement = spelled
        elif len(spelled) > 3:
            # For full words like "assists", "goals", "points" - use as-is (don't spell out)
            replacement = spelled
        else:
            # For short letter-by-letter acronyms (1-3 chars), use spaces for clearer TTS pronunciation
            # Cartesia handles spaced acronyms better than ZWJ
            replacement = " ".join(list(spelled))
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    # Fix NHL specifically - say "N H L" clearly (but don't double-process if already done)
    # This ensures NHL is always pronounced letter-by-letter
    text = re.sub(r'\bN\s+H\s+L\b', 'N H L', text, flags=re.IGNORECASE)  # Normalize spacing first
    text = re.sub(r'\bNHL\b', 'N H L', text, flags=re.IGNORECASE)
    
    # Fix player names (must be whole words) - do this BEFORE other word fixes
    for name, pronunciation in player_names.items():
        pattern = rf'(?<!\w){re.escape(name)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)
    
    # Fix common word pronunciations - do this AFTER player names
    for word, pronunciation in word_pronunciations.items():
        pattern = rf'(?<!\w){re.escape(word)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)

    # Fix hockey scores (e.g., "5-2" → "five to two", "3-1 OT" → "three to one in overtime")
    def replace_score(match):
        team1_score = match.group(1)
        team2_score = match.group(2)
        suffix = match.group(3) if match.group(3) else ''
        try:
            score1 = int(team1_score)
            score2 = int(team2_score)
            words1 = number_to_words(score1)
            words2 = number_to_words(score2)
            result = f"{words1} to {words2}"
            if suffix:
                suffix_lower = suffix.lower().strip()
                if 'ot' in suffix_lower or 'overtime' in suffix_lower:
                    result += " in overtime"
                elif 'so' in suffix_lower or 'shootout' in suffix_lower:
                    result += " in a shootout"
                else:
                    result += suffix
            return result
        except ValueError:
            return match.group(0)
    
    # Match scores like "5-2", "3-1 OT", "4-3 (OT)", etc.
    text = re.sub(r'(\d+)\s*[-–—]\s*(\d+)\s*(?:\(?(OT|SO|overtime|shootout)\)?)?', replace_score, text, flags=re.IGNORECASE)

    # Fix player numbers (e.g., "#97" → "number ninety-seven", "No. 97" → "number ninety-seven")
    def replace_player_number(match):
        prefix = match.group(1) if match.group(1) else ''
        num_str = match.group(2)
        try:
            num = int(num_str)
            words = number_to_words(num)
            return f"number {words}"
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(?:#|No\.?\s*)(\d+)', replace_player_number, text, flags=re.IGNORECASE)
    text = re.sub(r'number\s+(\d+)', replace_player_number, text, flags=re.IGNORECASE)

    # Convert episode numbers (e.g., "episode 336" → "episode three hundred thirty-six")
    def replace_episode_number(match):
        episode_text = match.group(1)
        num_str = match.group(2)
        try:
            num = int(num_str)
            words = number_to_words(num)
            return f"{episode_text} {words}"
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(episode\s+)(\d+)', replace_episode_number, text, flags=re.IGNORECASE)

    # Convert statistics with numbers (e.g., "25 goals" → "twenty-five goals", "3.5 GAA" → "three point five goals against average")
    def replace_stat_with_number(match):
        num_str = match.group(1)
        stat = match.group(2).strip()
        try:
            num = float(num_str)
            words = number_to_words(num)
            # Map common stat abbreviations to full words
            stat_map = {
                "GAA": "goals against average",
                "SV%": "save percentage",
                "PIM": "penalty minutes",
                "TOI": "time on ice",
            }
            stat_full = stat_map.get(stat.upper(), stat)
            return f"{words} {stat_full}"
        except ValueError:
            return match.group(0)
    
    # Match patterns like "3.5 GAA", "25 goals", "10 helpers" (note: "assists" should already be replaced with "helpers" before this)
    # First ensure "assists" is replaced with "helpers" before processing stats
    text = re.sub(r'\bassists\b', 'helpers', text, flags=re.IGNORECASE)
    text = re.sub(r'\bassist\b', 'helper', text, flags=re.IGNORECASE)
    text = re.sub(r'(\d+\.?\d*)\s+(GAA|SV%|PIM|TOI|goals?|helpers?|points?|saves?|shots?)', replace_stat_with_number, text, flags=re.IGNORECASE)

    # Convert percentages (e.g., "+3.59%" → "plus three point five nine percent")
    def replace_percentage(match):
        sign = match.group(1) if match.group(1) else ''
        num_str = match.group(2)
        try:
            num = float(num_str)
            words = number_to_words(abs(num))
            if sign == '+':
                sign_word = 'plus'
            elif sign == '-':
                sign_word = 'minus'
            else:
                sign_word = ''
            result = f"{sign_word} {words} percent" if sign_word else f"{words} percent"
            return result.strip()
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'([\+\-]?)(\d+\.?\d*)\s*%', replace_percentage, text)

    # Convert dollar amounts (e.g., "$5.5M" → "five point five million dollars", "$2.3B" → "two point three billion dollars")
    def replace_dollar_amount(match):
        dollar_sign = match.group(1)
        num_str = match.group(2)
        suffix = match.group(3) if match.group(3) else ''
        try:
            num = float(num_str)
            words = number_to_words(num)
            if suffix.upper() == 'M':
                suffix_word = ' million dollars'
            elif suffix.upper() == 'B':
                suffix_word = ' billion dollars'
            elif suffix.upper() == 'K':
                suffix_word = ' thousand dollars'
            else:
                suffix_word = ' dollars'
            return f"{words}{suffix_word}"
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(\$)(\d+\.?\d*)\s*([MBK]?)', replace_dollar_amount, text, flags=re.IGNORECASE)

    # Convert standalone numbers in parentheses (e.g., "(25)" → "(twenty-five)")
    def replace_standalone_number(match):
        num_str = match.group(1)
        try:
            num = int(num_str)
            words = number_to_words(num)
            return f"({words})"
        except ValueError:
            return match.group(0)
    
    # Only replace numbers in parentheses if they're standalone (not part of scores or other patterns)
    text = re.sub(r'\((\d+)\)', replace_standalone_number, text)

    # Fix common hockey phrases
    hockey_phrases = {
        r'\bhat trick\b': 'hat trick',
        r'\bpower play goal\b': 'power play goal',
        r'\bshort-handed goal\b': 'short-handed goal',
        r'\bempty net goal\b': 'empty net goal',
        r'\bgame-winning goal\b': 'game-winning goal',
        r'\bpenalty shot\b': 'penalty shot',
        r'\bbreakaway\b': 'breakaway',
        r'\bone-timer\b': 'one-timer',
        r'\bslap shot\b': 'slap shot',
        r'\bwrist shot\b': 'wrist shot',
        r'\bbackhand\b': 'backhand',
    }

    # Fix dates (e.g., "December 2, 2025" → "December second, twenty twenty-five")
    def replace_date(match):
        month = match.group(1)
        day = match.group(2)
        year = match.group(3) if match.group(3) else ''
        try:
            day_num = int(day)
            day_words = number_to_words(day_num)
            result = f"{month} {day_words}"
            if year:
                year_num = int(year)
                year_words = number_to_words(year_num)
                result += f", {year_words}"
            return result
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d+)(?:,\s*(\d{4}))?', replace_date, text, flags=re.IGNORECASE)

    # Fix times (e.g., "3:00 PM" → "three o'clock P M", "9:30 AM" → "nine thirty A M")
    def replace_time(match):
        hour = match.group(1)
        minute = match.group(2) if match.group(2) else '00'
        period = match.group(3) if match.group(3) else ''
        try:
            hour_num = int(hour)
            hour_words = number_to_words(hour_num)
            if minute == '00' or minute == '':
                time_str = f"{hour_words} o'clock"
            else:
                minute_num = int(minute)
                minute_words = number_to_words(minute_num)
                time_str = f"{hour_words} {minute_words}"
            if period:
                period_letters = ' '.join(list(period.upper()))
                time_str += f" {period_letters}"
            return time_str
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(\d{1,2}):(\d{2})\s*(AM|PM)', replace_time, text, flags=re.IGNORECASE)

    # If shared pronunciation module is available, apply common fixes
    # Note: Hockey-specific terms and player names are already handled above
    if USE_SHARED_PRONUNCIATION:
        try:
            # Apply shared pronunciation fixes for common acronyms and terms
            # Player names are handled locally above, so pass empty dict
            text = apply_pronunciation_fixes(
                text,
                acronyms=COMMON_ACRONYMS,
                hockey_terms=HOCKEY_TERMS,
                player_names={},  # Use local player_names dict instead
                word_pronunciations=WORD_PRONUNCIATIONS,
                use_zwj=False  # Use spaces for better TTS
            )
        except Exception as e:
            logging.warning(f"Error applying shared pronunciation fixes: {e}, continuing with local fixes")

    return text

def generate_episode_thumbnail(base_image_path, episode_num, date_str, output_path):
    img = Image.open(base_image_path)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except IOError:
        font = ImageFont.load_default()
    draw.text((50, 50), f"Episode {episode_num}", font=font, fill=(255, 255, 255))
    draw.text((50, 100), date_str, font=font, fill=(255, 255, 255))
    img.save(output_path, "PNG")

# ========================== PATHS & ENV ==========================
script_dir = Path(__file__).resolve().parent        # → .../digests
project_root = script_dir.parent                      # → .../tesla_shorts_time
env_path = project_root / ".env"

if not env_path.exists():
    raise FileNotFoundError(f".env not found at {env_path}")

load_dotenv(dotenv_path=env_path)

# ========================== SET UP SHARED PRONUNCIATION MODULE ==========================
# Try to use shared pronunciation module, fallback to local implementation
try:
    import sys
    # Add project root to path so we can import assets module
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from assets.pronunciation import apply_pronunciation_fixes, COMMON_ACRONYMS, HOCKEY_TERMS, PLAYER_NAMES, WORD_PRONUNCIATIONS
    USE_SHARED_PRONUNCIATION = True
except ImportError:
    USE_SHARED_PRONUNCIATION = False
    logging.warning("Could not import shared pronunciation module, using local implementation")

# TTS provider selection (NO automatic fallback to ElevenLabs)
# - chatterbox (default): local model (requires torch/torchaudio/chatterbox-tts)
# - elevenlabs: ElevenLabs API (requires ELEVENLABS_API_KEY)
# NOTE: We still accept "auto"/"detect" as aliases for "chatterbox" for backwards compatibility.
def _normalize_tts_provider(value: str) -> str:
    v = (value or "").strip().lower()
    if not v:
        return "chatterbox"
    if v in {"auto", "detect"}:
        return "chatterbox"
    if v in {"elevenlabs", "eleven", "11labs", "11-labs"}:
        return "elevenlabs"
    if v in {"chatterbox", "chatterbox-tts", "chatterbox_tts", "cb"}:
        return "chatterbox"
    return v

def _module_available(module_name: str) -> bool:
    """Return True if a module can be imported (without importing it)."""
    try:
        import importlib.util
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _chatterbox_deps_available() -> bool:
    return (
        _module_available("torch")
        and _module_available("torchaudio")
        and (_module_available("chatterbox.tts") or _module_available("chatterbox"))
    )

TTS_PROVIDER = _normalize_tts_provider(os.getenv("LUBECHANGE_TTS_PROVIDER", "chatterbox"))

# Required keys (X credentials for @lubechange_oilers account - using same as planetterrian for now)
required = [
    "GROK_API_KEY"
]
if ENABLE_PODCAST and not TEST_MODE:
    if TTS_PROVIDER == "elevenlabs":
        required.append("ELEVENLABS_API_KEY")
    elif TTS_PROVIDER == "chatterbox":
        if not _chatterbox_deps_available():
            raise OSError(
                "Chatterbox TTS selected but dependencies are missing. Install "
                "requirements_planetterrian.txt (torch, torchaudio, chatterbox-tts)."
            )
        pass  # local model, no API key needed
    else:
        raise OSError(
            f"Unknown LUBECHANGE_TTS_PROVIDER '{TTS_PROVIDER}'. Use 'chatterbox' or 'elevenlabs'."
        )
if ENABLE_X_POSTING:
    required.extend([
        "PLANETTERRIAN_X_CONSUMER_KEY",  # Reusing for now, can be updated later
        "PLANETTERRIAN_X_CONSUMER_SECRET",
        "PLANETTERRIAN_X_ACCESS_TOKEN",
        "PLANETTERRIAN_X_ACCESS_TOKEN_SECRET",
        "PLANETTERRIAN_X_BEARER_TOKEN"
    ])
for var in required:
    if not os.getenv(var):
        raise OSError(f"Missing {var} in .env")

# Helpers for env parsing
def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        logging.warning(f"Invalid {name}='{raw}' (expected float). Using default {default}.")
        return default

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logging.warning(f"Invalid {name}='{raw}' (expected int). Using default {default}.")
        return default

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = str(raw).strip().lower()
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default

# Chatterbox (local) TTS config
CHATTERBOX_DEVICE = (os.getenv("CHATTERBOX_DEVICE", "cpu") or "cpu").strip().lower()
CHATTERBOX_EXAGGERATION = _env_float("CHATTERBOX_EXAGGERATION", 0.5)
CHATTERBOX_MAX_CHARS = _env_int("CHATTERBOX_MAX_CHARS", 1000)
CHATTERBOX_QUIET = _env_bool("CHATTERBOX_QUIET", True)
CHATTERBOX_VOICE_PROMPT_PATH = os.getenv("CHATTERBOX_VOICE_PROMPT_PATH", "").strip()
CHATTERBOX_VOICE_PROMPT_BASE64 = os.getenv("CHATTERBOX_VOICE_PROMPT_BASE64", "").strip()
CHATTERBOX_PROMPT_OFFSET_SECONDS = _env_float("CHATTERBOX_PROMPT_OFFSET_SECONDS", 35.0)
CHATTERBOX_PROMPT_DURATION_SECONDS = _env_float("CHATTERBOX_PROMPT_DURATION_SECONDS", 10.0)

# Chatterbox voice cloning can use either an explicit prompt (path/base64) OR fall back to a prior episode audio.
if ENABLE_PODCAST and not TEST_MODE and TTS_PROVIDER == "chatterbox":
    if not os.getenv("CHATTERBOX_VOICE_PROMPT_PATH") and not os.getenv("CHATTERBOX_VOICE_PROMPT_BASE64"):
        logging.info(
            "Chatterbox voice prompt not provided via env; will attempt to derive a prompt from an existing Lube Change episode MP3."
        )

# ========================== DATE ==========================
# Get current date and time in MST (Mountain Standard Time - Alberta)
mst_tz = ZoneInfo("America/Edmonton")
now_mst = datetime.datetime.now(mst_tz)
today_str = now_mst.strftime("%B %d, %Y at %I:%M %p MST")
yesterday_iso = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
seven_days_ago_iso = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

# Folders - use absolute paths
digests_dir = project_root / "digests" / "lubechange"
digests_dir.mkdir(exist_ok=True, parents=True)

# ========================== CONTENT TRACKING (PREVENT REPETITION) ==========================
def load_used_content_tracker() -> dict:
    """Load previously used content to avoid repetition."""
    tracker_file = digests_dir / "content_tracker.json"
    if tracker_file.exists():
        try:
            with open(tracker_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load content tracker: {e}")
    return {
        "historical_facts": [],
        "drip_topics": [],
        "oil_country_moments": [],
        "foundation_activities": [],
        "last_updated": None
    }

def save_used_content_tracker(tracker: dict):
    """Save used content tracker."""
    tracker_file = digests_dir / "content_tracker.json"
    try:
        # Keep only last 7 days of content
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
        for key in ["historical_facts", "drip_topics", "oil_country_moments", "foundation_activities"]:
            tracker[key] = [
                item for item in tracker[key] 
                if item.get("date", "") >= cutoff_date
            ]
        tracker["last_updated"] = datetime.date.today().isoformat()
        with open(tracker_file, 'w', encoding='utf-8') as f:
            json.dump(tracker, f, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save content tracker: {e}")

def get_used_content_summary(tracker: dict) -> str:
    """Generate a summary of recently used content for prompts."""
    summary_parts = []
    
    if tracker.get("historical_facts"):
        recent_facts = tracker["historical_facts"][-5:]  # Last 5 facts
        facts_text = "\n".join([f"- {item.get('content', '')[:100]}..." for item in recent_facts])
        summary_parts.append(f"RECENTLY USED HISTORICAL FACTS (DO NOT REPEAT):\n{facts_text}")
    
    if tracker.get("drip_topics"):
        recent_drips = tracker["drip_topics"][-5:]  # Last 5 topics
        drips_text = "\n".join([f"- {item.get('content', '')[:100]}..." for item in recent_drips])
        summary_parts.append(f"RECENTLY USED DRIP TOPICS (DO NOT REPEAT):\n{drips_text}")
    
    if tracker.get("oil_country_moments"):
        recent_moments = tracker["oil_country_moments"][-5:]  # Last 5 moments
        moments_text = "\n".join([f"- {item.get('content', '')[:100]}..." for item in recent_moments])
        summary_parts.append(f"RECENTLY USED 80S VIBES MOMENTS (DO NOT REPEAT):\n{moments_text}")
    
    if tracker.get("foundation_activities"):
        recent_foundation = tracker["foundation_activities"][-5:]  # Last 5 activities
        foundation_text = "\n".join([f"- {item.get('content', '')[:100]}..." for item in recent_foundation])
        summary_parts.append(f"RECENTLY USED FOUNDATION ACTIVITIES (DO NOT REPEAT):\n{foundation_text}")
    
    if summary_parts:
        return "\n\n".join(summary_parts) + "\n\nCRITICAL: Generate COMPLETELY NEW and DIFFERENT content. Do not repeat any of the above.\n"
    return ""

# Folders - use absolute paths
digests_dir = project_root / "digests" / "lubechange"
digests_dir.mkdir(exist_ok=True, parents=True)

# Initialize content tracker (must be after digests_dir is defined)
content_tracker = load_used_content_tracker()
used_content_summary = get_used_content_summary(content_tracker)

# Determine episode number by finding the highest existing episode number and incrementing
def get_next_episode_number(rss_path: Path, digests_dir: Path) -> int:
    """Get the next episode number. Checks if episode for today exists in RSS feed, otherwise starts at 1 or increments."""
    today_str = datetime.date.today().strftime("%Y%m%d")
    
    # Check RSS feed for episodes published today (RSS feed is source of truth)
    # Only skip if we find an episode with today's date AND it was published in the last 2 hours
    # This prevents false positives from timezone issues or old episodes
    # NOTE: We don't check local files because they might be leftover from failed runs
    if rss_path.exists():
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find('channel')
            if channel is not None:
                today_date = datetime.date.today()
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                two_hours_ago = now_utc - datetime.timedelta(hours=2)
                
                for item in channel.findall('item'):
                    pub_date_elem = item.find('pubDate')
                    if pub_date_elem is not None and pub_date_elem.text:
                        try:
                            from email.utils import parsedate_to_datetime
                            pub_date = parsedate_to_datetime(pub_date_elem.text)
                            # Only skip if episode is from today AND was published in the last 2 hours
                            # This prevents skipping due to old episodes or timezone mismatches
                            if pub_date.date() == today_date and pub_date >= two_hours_ago:
                                itunes_episode = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')
                                if itunes_episode is not None and itunes_episode.text:
                                    existing_ep_num = int(itunes_episode.text)
                                    logging.info(f"Episode {existing_ep_num} already exists in RSS feed for today ({today_str}, published {pub_date.isoformat()}). Skipping generation.")
                                    return None  # Signal to skip generation
                        except (ValueError, Exception) as e:
                            logging.debug(f"Could not parse pubDate for RSS item: {e}")
                            pass
        except Exception as e:
            logging.warning(f"Could not parse RSS feed to check for today's episode: {e}")
    
    # No episode for today exists, so determine next episode number
    # RSS feed is the source of truth - only check local files if RSS is empty or missing
    max_episode = 0
    
    # Check RSS feed for existing episodes (this is the source of truth)
    rss_has_episodes = False
    if rss_path.exists():
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find('channel')
            if channel is not None:
                items = channel.findall('item')
                if items:
                    rss_has_episodes = True
                    for item in items:
                        itunes_episode = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')
                        if itunes_episode is not None and itunes_episode.text:
                            try:
                                ep_num = int(itunes_episode.text)
                                max_episode = max(max_episode, ep_num)
                            except ValueError:
                                pass
        except Exception as e:
            logging.warning(f"Could not parse RSS feed to find episode number: {e}")
    
    # Only check local MP3 files if RSS feed is empty (to handle edge cases during initial setup)
    # Once RSS has episodes, it becomes the sole source of truth
    if not rss_has_episodes:
        logging.info("RSS feed is empty, checking local files for episode numbering")
        pattern = r"Lube_Change_Ep(\d+)_\d{8}\.mp3"
        for mp3_file in digests_dir.glob("Lube_Change_Ep*.mp3"):
            match = re.match(pattern, mp3_file.name)
            if match:
                try:
                    ep_num = int(match.group(1))
                    max_episode = max(max_episode, ep_num)
                    logging.warning(f"Found local MP3 file {mp3_file.name} but RSS feed is empty. This file should be deleted or added to RSS.")
                except ValueError:
                    pass
    
    # Increment from highest existing episode number
    next_episode = max_episode + 1
    logging.info(f"Next episode number: {next_episode} (highest existing: {max_episode})")
    return next_episode

# Get the next episode number
rss_path = project_root / "lubechange_podcast.rss"
episode_num = get_next_episode_number(rss_path, digests_dir)

# Check if episode generation should be skipped (episode already exists for today)
skip_podcast_today = False
if episode_num is None:
    logging.info("Episode for today already exists. Skipping podcast generation.")
    skip_podcast_today = True
    # Set a placeholder episode number for credit tracking (won't be used for podcast)
    episode_num = 0
else:
    logging.info(f"Will create Episode {episode_num} for today ({datetime.date.today().strftime('%Y-%m-%d')})")

# ========================== CREDIT TRACKING ==========================
# Initialize credit usage tracking
credit_usage = {
    "date": datetime.date.today().isoformat(),
    "episode_number": episode_num,
    "services": {
        "grok_api": {
            "x_thread_generation": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0
            },
            "podcast_script_generation": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0
            },
            "total_tokens": 0,
            "total_cost_usd": 0.0
        },
        "tts_api": {
            "provider": TTS_PROVIDER,
            "characters": 0,
            "estimated_cost_usd": 0.0
        },
        "x_api": {
            "search_calls": 0,
            "post_calls": 0,
            "total_calls": 0
        }
    },
    "total_estimated_cost_usd": 0.0
}

def save_credit_usage(usage_data: dict, output_dir: Path):
    """Save credit usage to a JSON file."""
    try:
        # Calculate totals
        grok_total = (
            usage_data["services"]["grok_api"]["x_thread_generation"]["total_tokens"] +
            usage_data["services"]["grok_api"]["podcast_script_generation"]["total_tokens"]
        )
        usage_data["services"]["grok_api"]["total_tokens"] = grok_total
        usage_data["services"]["grok_api"]["total_cost_usd"] = (
            usage_data["services"]["grok_api"]["x_thread_generation"]["estimated_cost_usd"] +
            usage_data["services"]["grok_api"]["podcast_script_generation"]["estimated_cost_usd"]
        )
        
        usage_data["services"]["x_api"]["total_calls"] = (
            usage_data["services"]["x_api"]["search_calls"] +
            usage_data["services"]["x_api"]["post_calls"]
        )
        
        # Calculate TTS cost (only applies if using a paid API provider like ElevenLabs)
        tts_provider = str(usage_data["services"]["tts_api"].get("provider", "chatterbox")).strip().lower()
        if tts_provider == "elevenlabs":
            tts_cost = (usage_data["services"]["tts_api"]["characters"] / 1000) * 0.30
        else:
            tts_cost = 0.0
        usage_data["services"]["tts_api"]["estimated_cost_usd"] = tts_cost
        
        usage_data["total_estimated_cost_usd"] = (
            usage_data["services"]["grok_api"]["total_cost_usd"] +
            usage_data["services"]["tts_api"]["estimated_cost_usd"]
        )
        
        # Save to JSON file
        filename = f"credit_usage_{usage_data['date']}_ep{usage_data['episode_number']:03d}.json"
        filepath = output_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(usage_data, f, indent=2)
        
        logging.info(f"Credit usage saved to {filepath}")
        
        # Also log summary
        logging.info("="*80)
        logging.info("CREDIT USAGE SUMMARY")
        logging.info("="*80)
        logging.info(f"Grok API (X Thread): {usage_data['services']['grok_api']['x_thread_generation']['total_tokens']} tokens (${usage_data['services']['grok_api']['x_thread_generation']['estimated_cost_usd']:.4f})")
        logging.info(f"Grok API (Podcast Script): {usage_data['services']['grok_api']['podcast_script_generation']['total_tokens']} tokens (${usage_data['services']['grok_api']['podcast_script_generation']['estimated_cost_usd']:.4f})")
        logging.info(f"Grok API Total: {usage_data['services']['grok_api']['total_tokens']} tokens (${usage_data['services']['grok_api']['total_cost_usd']:.4f})")
        logging.info(f"TTS ({usage_data['services']['tts_api'].get('provider', 'chatterbox')}): {usage_data['services']['tts_api']['characters']} characters (${usage_data['services']['tts_api']['estimated_cost_usd']:.4f})")
        logging.info(f"X API: {usage_data['services']['x_api']['total_calls']} API calls (search: {usage_data['services']['x_api']['search_calls']}, post: {usage_data['services']['x_api']['post_calls']})")
        logging.info(f"TOTAL ESTIMATED COST: ${usage_data['total_estimated_cost_usd']:.4f}")
        logging.info("="*80)
        
    except Exception as e:
        logging.error(f"Failed to save credit usage: {e}", exc_info=True)

tmp_dir = Path(tempfile.gettempdir()) / "tts"
tmp_dir.mkdir(exist_ok=True, parents=True)

# ========================== CLIENTS ==========================
# Grok client with timeout settings
client = OpenAI(
    api_key=os.getenv("GROK_API_KEY"), 
    base_url="https://api.x.ai/v1",
    timeout=300.0  # 5 minute timeout for API calls
)
ELEVEN_API = "https://api.elevenlabs.io/v1"
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "dTrBzPvD2GpAqkk1MUzA").strip()

# ========================== STEP 1: FETCH OILERS NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching Edmonton Oilers news from RSS feeds for the last 24 hours...")

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity ratio between two texts (0.0 to 1.0)."""
    if not text1 or not text2:
        return 0.0
    # Normalize: lowercase, remove extra whitespace
    text1_norm = ' '.join(text1.lower().split())
    text2_norm = ' '.join(text2.lower().split())
    return SequenceMatcher(None, text1_norm, text2_norm).ratio()

def remove_similar_items(items, similarity_threshold=0.7, get_text_func=None):
    """
    Remove similar items from a list based on text similarity.
    """
    if not items:
        return items
    
    if get_text_func is None:
        def get_text_func(item):
            if isinstance(item, dict):
                return item.get('title', '') or item.get('text', '') or item.get('description', '')
            return str(item)
    
    filtered = []
    for item in items:
        item_text = get_text_func(item)
        if not item_text:
            continue
        
        is_similar = False
        for accepted_item in filtered:
            accepted_text = get_text_func(accepted_item)
            similarity = calculate_similarity(item_text, accepted_text)
            if similarity >= similarity_threshold:
                is_similar = True
                logging.debug(f"Filtered similar item (similarity: {similarity:.2f}): {item_text[:50]}...")
                break
        
        if not is_similar:
            filtered.append(item)
    
    return filtered

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
)
def fetch_oilers_news():
    """Fetch Edmonton Oilers news from RSS feeds for the last 24 hours."""
    import feedparser
    
    # Edmonton Oilers and NHL RSS feeds
    # Prioritized by reliability - working feeds first, then fallbacks
    rss_feeds = [
        # HIGH PRIORITY - Oilers-specific news sources (these are Oilers-focused and reliable)
        "https://oilersnation.com/feed",  # ✅ Working - 10 articles fetched
        "https://www.coppernblue.com/rss/index.xml",  # The Copper & Blue
        "https://www.dailyfaceoff.com/teams/edmonton-oilers/news/",  # ✅ Working - 1 article fetched
        
        # MEDIUM PRIORITY - General NHL/Oilers feeds (some may have XML issues)
        "https://www.espn.com/espn/rss/nhl/news",  # ✅ Working - 1 article fetched
        "https://www.cbssports.com/rss/headlines/nhl",  # CBS Sports
        
        # LOWER PRIORITY - These feeds often have malformed XML but kept as fallbacks
        # Official NHL feeds (often have XML parsing issues)
        "https://www.nhl.com/oilers/rss.xml",
        "https://www.nhl.com/rss/news",
        "https://www.nhl.com/news/rss",
        
        # Team-specific feeds (may have XML issues)
        "https://www.tsn.ca/nhl/team/edmonton-oilers/rss",
        "https://www.espn.com/nhl/team/_/name/edm/edmonton-oilers/rss",
        "https://www.foxsports.com/nhl/edmonton-oilers/rss",
        
        # General NHL feeds (may have XML issues)
        "https://www.tsn.ca/rss/nhl",
        "https://www.sportsnet.ca/rss/nhl",
        "https://www.thescore.com/nhl/rss",
        "https://www.nhl.com/rss/scores",
        
        # Canadian sports media (may have XML issues)
        "https://www.cbc.ca/sports/hockey/rss",
        "https://www.theglobeandmail.com/sports/hockey/rss",
        "https://www.edmontonjournal.com/sports/hockey/edmonton-oilers/rss",
        "https://www.edmontonsun.com/sports/hockey/edmonton-oilers/rss",
        
        # Hockey-specific sites (may have XML issues)
        "https://www.hockeynews.com/rss",
        "https://www.thehockeynews.com/rss",
        "https://www.dailyfaceoff.com/rss",
        "https://www.puckprose.com/rss",
        
        # Analytics and advanced stats (may have XML issues)
        "https://www.naturalstattrick.com/rss",
        "https://www.hockey-reference.com/rss",
    ]
    
    # Calculate cutoff time (last 36 hours - more flexible to catch timezone issues)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    cutoff_time = now_utc - datetime.timedelta(hours=36)
    logging.info(f"Fetching articles published after {cutoff_time.isoformat()} (last 36 hours, flexible)")
    
    all_articles = []
    raw_articles = []
    
    # Oilers-specific keywords - MUST include at least one Oilers-specific term
    # Primary keywords (required for inclusion) - expanded list
    oilers_primary_keywords = [
        # Team names and location
        "oilers", "edmonton oilers", "edmonton", "edm", "edm oilers",
        # Star players (current and recent)
        "connor mcdavid", "mcdavid", "leon draisaitl", "draisaitl", 
        "evander kane", "zach hyman", "hyman", "stuart skinner", "skinner",
        "jack campbell", "darnell nurse", "nurse", "evan bouchard", "bouchard",
        "ryan nugent-hopkins", "nugent-hopkins", "nugent hopkins", "rnh",
        "matthew barzal", "warren foegele", "foegele",
        "cody ceci", "philip broberg", "broberg", "vincent desharnais", "desharnais",
        "brett kulak", "kulak", "calvin pickard", "pickard",
        "sam gagner", "gagner", "derek ryan", "mattias janmark", "janmark",
        "connor brown", "adam henrique", "henrique", "corey perry", "perry",
        "sam carrick", "carrick",
        # Venue and location
        "rogers place", "roger place", "ice district", "rexall place",
        # Team-related terms
        "oilers news", "oilers trade", "oilers game", "oilers score", "oilers roster",
        "oilers injury", "oilers draft", "oilers lineup", "oilers coach",
        "oilers gm", "oilers management", "oilers fan", "oilers nation", "oil country",
        # Management and coaching
        "ken holland", "holland", "jay woodcroft", "woodcroft",
        "kris knoblauch", "knoblauch",
        # Historical players (for context)
        "wayne gretzky", "gretzky", "mark messier", "messier", "paul coffey", "coffey",
        "grant fuhr", "fuhr", "jari kurri", "kurri",
        # Common Oilers-related phrases
        "oilers win", "oilers lose", "oilers beat", "oilers vs", "oilers game",
        "oilers update", "oilers report", "oilers news", "oilers analysis"
    ]
    
    # Secondary keywords (only valid if combined with primary)
    # These alone are NOT sufficient - article must mention Oilers specifically
    oilers_secondary_keywords = [
        "pacific division", "western conference"  # Only if Oilers are mentioned
    ]
    
    logging.info(f"Fetching Oilers news from {len(rss_feeds)} RSS feeds...")
    
    # Known problematic feeds that often fail - track them separately
    problematic_feeds = set()
    
    # HTTP settings for RSS fetching
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    HTTP_TIMEOUT_SECONDS = 10
    
    for feed_url in rss_feeds:
        source_name = "Unknown"
        try:
            # Fetch RSS feed with timeout and custom headers (like tesla_shorts_time.py)
            response = requests.get(
                feed_url,
                headers=DEFAULT_HEADERS,
                timeout=HTTP_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            
            # Parse RSS feed content
            feed = feedparser.parse(response.content)
            
            if feed.bozo and feed.bozo_exception:
                # Only log warning once per feed, then suppress
                if feed_url not in problematic_feeds:
                    problematic_feeds.add(feed_url)
                    # Use debug level for known problematic feeds to reduce noise
                    error_msg = str(feed.bozo_exception)
                    if "not well-formed" in error_msg or "syntax error" in error_msg:
                        logging.debug(f"RSS feed has malformed XML (will skip): {feed_url}")
                    else:
                        logging.debug(f"RSS feed parsing issue (will skip): {feed_url} - {error_msg[:100]}")
                continue
            
            source_name = feed.feed.get("title", "Unknown")
            # Map common feed sources
            if "nhl.com" in feed_url.lower():
                if "oilers" in feed_url.lower():
                    source_name = "NHL.com - Edmonton Oilers"
                else:
                    source_name = "NHL.com"
            elif "tsn.ca" in feed_url.lower():
                source_name = "TSN"
            elif "sportsnet.ca" in feed_url.lower():
                source_name = "Sportsnet"
            elif "espn.com" in feed_url.lower():
                source_name = "ESPN"
            elif "cbssports.com" in feed_url.lower():
                source_name = "CBS Sports"
            elif "thescore.com" in feed_url.lower():
                source_name = "The Score"
            elif "cbc.ca" in feed_url.lower():
                source_name = "CBC Sports"
            elif "edmontonjournal.com" in feed_url.lower():
                source_name = "Edmonton Journal"
            elif "edmontonsun.com" in feed_url.lower():
                source_name = "Edmonton Sun"
            elif "thehockeynews.com" in feed_url.lower():
                source_name = "The Hockey News"
            elif "dailyfaceoff.com" in feed_url.lower():
                source_name = "Daily Faceoff"
            elif "naturalstattrick.com" in feed_url.lower():
                source_name = "Natural Stat Trick"
            elif "oilersnation.com" in feed_url.lower():
                source_name = "OilersNation"
            elif "coppernblue.com" in feed_url.lower():
                source_name = "The Copper & Blue"
            elif "foxsports.com" in feed_url.lower() and "oilers" in feed_url.lower():
                source_name = "FOX Sports - Edmonton Oilers"
            elif "espn.com" in feed_url.lower() and "edmonton-oilers" in feed_url.lower():
                source_name = "ESPN - Edmonton Oilers"
            elif "tsn.ca" in feed_url.lower() and "edmonton-oilers" in feed_url.lower():
                source_name = "TSN - Edmonton Oilers"
            elif "dailyfaceoff.com" in feed_url.lower() and "edmonton-oilers" in feed_url.lower():
                source_name = "Daily Faceoff - Edmonton Oilers"
            
            feed_articles = []
            for entry in feed.entries:
                published_time = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published_time = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
                    except (ValueError, TypeError):
                        pass
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    try:
                        published_time = datetime.datetime(*entry.updated_parsed[:6], tzinfo=datetime.timezone.utc)
                    except (ValueError, TypeError):
                        pass
                
                # Date filtering: include articles from the last 36 hours (more flexible)
                # cutoff_time is already set to 36 hours ago, so use it directly
                if published_time:
                    if published_time < cutoff_time:
                        logging.debug(f"Filtered out article (too old, {published_time.isoformat()}): {title[:60]}...")
                        continue  # Skip articles older than 36 hours
                    # Also skip articles from the future (likely timezone issues)
                    if published_time > now_utc + datetime.timedelta(hours=1):
                        logging.debug(f"Filtered out article (future date): {title[:60]}...")
                        continue
                else:
                    # If no published time, include it but log a warning (might be recent)
                    logging.debug(f"Article '{title[:50]}...' has no published time, including it")
                    published_time = now_utc
                
                title = entry.get("title", "").strip()
                description = entry.get("description", "").strip() or entry.get("summary", "").strip()
                link = entry.get("link", "").strip()
                
                if not title or not link:
                    continue
                
                # FOCUSED FILTERING: Article should be Oilers-related
                # Check if article mentions Oilers or Oilers players/coaches/location
                title_desc_lower = (title + " " + description).lower()
                
                # Check if this is an Oilers-specific feed - if so, include ALL articles
                # These feeds are dedicated to Oilers content, so everything is relevant
                is_oilers_feed = any(oilers_term in feed_url.lower() for oilers_term in [
                    "oilers", "edmonton", "oilersnation", "coppernblue"
                ])
                is_oilers_source = any(oilers_term in source_name.lower() for oilers_term in [
                    "oilers", "edmonton", "oilersnation", "copper", "blue"
                ])
                
                # For Oilers-specific feeds (like nhl.com/oilers, edmontonjournal.com/oilers), include ALL articles
                # These feeds are curated for Oilers content, so everything is relevant
                if is_oilers_feed or is_oilers_source:
                    # This is an Oilers-specific feed - include all articles from last 24 hours
                    logging.debug(f"Including article from Oilers-specific feed: {title[:60]}...")
                    pass  # Don't filter, include all
                else:
                    # For general NHL feeds, require explicit Oilers keywords
                    has_oilers_primary = any(keyword in title_desc_lower for keyword in oilers_primary_keywords)
                    if not has_oilers_primary:
                        logging.debug(f"Filtered out article (no Oilers keywords from general feed): {title[:60]}...")
                        continue  # Skip articles that don't mention Oilers from general feeds
                
                # Only exclude articles that are CLEARLY about another team
                # Allow matchups, trades, comparisons, and any article that mentions Oilers
                title_lower = title.lower()
                
                # Only exclude if title clearly starts with another team name AND Oilers not in title
                # This catches cases like "Maple Leafs beat..." where Oilers aren't the focus
                other_team_mentions = [
                    "maple leafs", "canadiens", "canucks", "flames", "jets", "senators",
                    "bruins", "rangers", "islanders", "devils", "flyers", "penguins",
                    "capitals", "hurricanes", "panthers", "lightning", "predators",
                    "stars", "avalanche", "coyotes", "blackhawks", "red wings", "blue jackets",
                    "wild", "sharks", "kings", "ducks", "golden knights", "kraken"
                ]
                
                # Check if title starts with another team (very strict - only exclude obvious cases)
                title_starts_with_other_team = False
                for team in other_team_mentions:
                    team_words = team.split()
                    # Check if title starts with team name
                    if len(team_words) == 1:
                        if title_lower.startswith(team + " ") or title_lower.startswith(team + "'") or title_lower.startswith(team + ":"):
                            title_starts_with_other_team = True
                            break
                    elif len(team_words) == 2:
                        title_first_words = title_lower.split()[:2]
                        if title_first_words == team_words or title_lower.startswith(team + " "):
                            title_starts_with_other_team = True
                            break
                
                # Only exclude if title starts with another team AND Oilers not mentioned in title at all
                if title_starts_with_other_team:
                    title_has_oilers = any(keyword in title_lower for keyword in ["oilers", "edmonton oilers", "connor mcdavid", "leon draisaitl", "edmonton"])
                    if not title_has_oilers:
                        continue  # Title is about another team, Oilers not in title - likely not Oilers-focused
                
                article = {
                    "title": title,
                    "description": description,
                    "url": link,
                    "source": source_name,
                    "publishedAt": published_time.isoformat() if published_time else datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "author": entry.get("author", "")
                }
                
                feed_articles.append(article)
                raw_articles.append(article)
            
            logging.info(f"Fetched {len(feed_articles)} articles from {source_name}")
            all_articles.extend(feed_articles)
            
        except requests.RequestException as e:
            # Network errors - log at debug level to reduce noise
            if feed_url not in problematic_feeds:
                problematic_feeds.add(feed_url)
                logging.debug(f"Network error fetching RSS feed (will skip): {feed_url} - {type(e).__name__}")
            continue
        except Exception as e:
            # Other errors - log at debug level for known issues
            error_str = str(e)
            if any(keyword in error_str.lower() for keyword in ["not well-formed", "syntax error", "mismatched tag", "invalid token", "404", "not found", "closed connection"]):
                if feed_url not in problematic_feeds:
                    problematic_feeds.add(feed_url)
                    logging.debug(f"RSS feed error (will skip): {feed_url} - {type(e).__name__}")
            else:
                # Unknown errors - log at warning level
                logging.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            continue
    
    logging.info(f"Fetched {len(all_articles)} total articles from RSS feeds")
    if problematic_feeds:
        logging.debug(f"Skipped {len(problematic_feeds)} problematic RSS feed(s) (check debug logs for details)")
    
    if not all_articles:
        logging.warning("⚠️  No articles found from RSS feeds - check feed availability and date filtering")
        return [], []
    
    # Remove similar/duplicate articles (less aggressive threshold)
    before_dedup = len(all_articles)
    formatted_articles = remove_similar_items(
        all_articles,
        similarity_threshold=0.90,  # Increased from 0.85 to be less aggressive
        get_text_func=lambda x: f"{x.get('title', '')} {x.get('description', '')}"
    )
    after_dedup = len(formatted_articles)
    if before_dedup != after_dedup:
        logging.info(f"Removed {before_dedup - after_dedup} similar/duplicate news articles")
    
    # Sort by published date (newest first)
    formatted_articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    
    logging.info(f"✅ Filtered to {len(formatted_articles)} unique Oilers news articles")
    
    if len(formatted_articles) == 0:
        logging.warning("⚠️  No Oilers articles found in the last 24 hours - this may result in empty Top Stories section")
        logging.warning("   Consider: 1) Expanding keyword list, 2) Checking feed availability, 3) Relaxing date filter")
    else:
        logging.info(f"   Top 3 article titles: {[a.get('title', '')[:60] for a in formatted_articles[:3]]}")
    filtered_result = formatted_articles[:15]  # Return top 15 for selection
    return filtered_result, raw_articles

oilers_news, raw_news_articles = fetch_oilers_news()

# ========================== SAVE RAW DATA ==========================
def save_raw_data_and_generate_html(raw_news, output_dir: Path):
    """Save raw data to JSON and generate HTML archive."""
    date_str = datetime.date.today().isoformat()
    formatted_date = datetime.date.today().strftime("%B %d, %Y")
    
    raw_data = {
        "date": date_str,
        "rss_feeds": {
            "total_articles": len(raw_news),
            "articles": raw_news
        }
    }
    
    # Save JSON
    json_path = output_dir / f"raw_data_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    
    logging.info(f"Raw data saved to {json_path}")
    
    # Generate simple HTML
    html_path = output_dir / f"raw_data_{date_str}.html"
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lube Change Raw Data - {formatted_date}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #0a0f1a; color: #fff; }}
        h1 {{ color: #FF4C00; }}
        .article {{ margin: 20px 0; padding: 15px; background: #1a2332; border-radius: 8px; }}
        .article h3 {{ color: #FF4C00; margin-top: 0; }}
        .article a {{ color: #1C4A8C; }}
    </style>
</head>
<body>
    <h1>Lube Change Raw Data - {formatted_date}</h1>
    <p>Total Articles: {len(raw_news)}</p>
"""
    for article in raw_news:
        html_content += f"""
    <div class="article">
        <h3>{html.escape(article.get('title', 'No title'))}</h3>
        <p><strong>Source:</strong> {html.escape(article.get('source', 'Unknown'))}</p>
        <p><strong>Published:</strong> {html.escape(article.get('publishedAt', 'Unknown'))}</p>
        <p>{html.escape(article.get('description', '')[:200])}...</p>
        <p><a href="{html.escape(article.get('url', ''))}" target="_blank">Read more</a></p>
    </div>
"""
    html_content += """
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    logging.info(f"Raw data HTML saved to {html_path}")
    
    return json_path, html_path

# Save raw data
raw_json_path, raw_html_path = save_raw_data_and_generate_html(
    raw_news_articles, 
    digests_dir
)

# ========================== STEP 2: GENERATE X THREAD WITH GROK ==========================
logging.info("Step 2: Generating Lube Change - Oilers Daily News digest with Grok...")

# Format news articles for the prompt
news_section = ""
if oilers_news:
    news_section = "## PRE-FETCHED OILERS NEWS ARTICLES (from RSS feeds - last 24 hours):\n\n"
    for i, article in enumerate(oilers_news[:20], 1):
        news_section += f"{i}. **{article['title']}**\n"
        news_section += f"   Source: {article['source']}\n"
        news_section += f"   Published: {article['publishedAt']}\n"
        if article.get('description'):
            news_section += f"   Description: {article['description'][:200]}...\n"
        news_section += f"   URL: {article['url']}\n\n"
else:
    news_section = "## PRE-FETCHED OILERS NEWS ARTICLES: None available\n\n"

X_PROMPT = f"""
{news_section}

=== INSTRUCTIONS (DO NOT INCLUDE IN OUTPUT) ===

You are an elite Edmonton Oilers news curator producing the daily "Lube Change - Oilers Daily News" newsletter. Use ONLY the pre-fetched news articles above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links.

FOCUS REQUIREMENTS:
- ONLY include news that DIRECTLY relates to the Edmonton Oilers
- Focus on: Oilers games, Oilers players, Oilers trades, Oilers roster moves, Oilers coaching, Oilers management, Oilers injuries, Oilers draft picks, Oilers prospects, Oilers team news
- EXCLUDE: General NHL news that doesn't specifically impact the Oilers, news about other teams unless it directly affects the Oilers (trades, matchups, etc.), league-wide news that doesn't mention the Oilers
- If an article is primarily about another team and only mentions Oilers in passing, DO NOT include it
- Prioritize breaking Oilers news, game recaps, player updates, and team developments

SELECTION REQUIREMENTS:
- **CRITICAL: You MUST include a "Top Oilers Stories" section with 3–15 stories. If articles are provided, use as many as available (up to 15).**
- If you have fewer than 3 articles, include all available and clearly note the shortfall (e.g., "Only 2 verified Oilers stories available today").
- If you have more than 15, select the BEST 15 (unique angles, no duplicates).
- Each article must cover a DIFFERENT story/angle - no duplicates or similar content
- Prioritize high-quality sources
- **If no articles are provided, still create a Top Stories section with a note explaining why (e.g., "No new Oilers news in the last 24 hours")**

CONTENT REQUIREMENTS:
- Vintage Oil: Must be a COMPLETELY NEW and DIFFERENT historical fact. Do not repeat any fact used in recent episodes. Vary the topic (player stories, game moments, records, team history, etc.).
- The Drip: Must be based on TODAY'S news and be COMPLETELY DIFFERENT from recent episodes. Focus on what's happening NOW, not general topics.
- 80s Vibes: Must be a COMPLETELY NEW and DIFFERENT moment. Vary between historical moments, current team achievements, and fan culture stories.
- Edmonton Oilers Community Foundation: Must be based on RECENT foundation activities (within the last few weeks/months). Focus on NEW initiatives, recent donations, or current programs. Do not repeat content from recent episodes.

{used_content_summary if used_content_summary else ''}

BRAND PERSONALITY:
- Host: Patrick in Vancouver, Canada - Oilers lifer bringing the news with west coast clarity
- Passionate, knowledgeable Oilers fan with deep love for the team
- Authentic Alberta roots, proud of Oil Country
- Tone: Enthusiastic, knowledgeable, passionate about the Oilers, authentic and conversational
- Audience: Die-hard Oilers fans who want the latest Oilers-specific news and analysis

=== OUTPUT FORMAT (INCLUDE ONLY THIS IN YOUR RESPONSE) ===

# Lube Change - Oilers Daily News
**Date:** {today_str}
🏒 **Lube Change** - Your Daily Dose of Oilers News from Oil Country

━━━━━━━━━━━━━━━━━━━━
### Top 15 Oilers Stories

1. **Title (One Line): DD Month, YYYY, HH:MM AM/PM MST, Source Name**  
   2–4 sentences: Start with what happened with the Oilers, explain why it matters for Oilers fans. Focus on the Oilers-specific impact. End with: Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for 3-15; if <15 items, stop at available count, add a blank line after each item]

━━━━━━━━━━━━━━━━━━━━
### Oil Leaks
One major story or development that Oilers fans need to know about. Explain why this matters for the team and fans.

━━━━━━━━━━━━━━━━━━━━
### Vintage Oil
Share one interesting, lesser-known historical fact about the Edmonton Oilers. This could be about a player, a game, a season, a record, or team history. Make it engaging and something that even die-hard fans might not know. Keep it to 2-3 sentences.

━━━━━━━━━━━━━━━━━━━━
### The Drip
What are Oilers fans and analysts talking about RIGHT NOW based on TODAY'S news? What do they think the team needs to do or change? This MUST reflect the CURRENT conversation, buzz, or hot topic in Oil Country based on the news articles from the last 24 hours. It could be about roster moves, coaching, strategy, player performance, or team needs. Keep it to 3-4 sentences and make it feel like you're capturing the pulse of Oil Country TODAY.

━━━━━━━━━━━━━━━━━━━━
### 80s Vibes
One inspiring or memorable moment from Oilers history, current team, or fan culture. End with: "Let's go Oilers!"

━━━━━━━━━━━━━━━━━━━━
### Edmonton Oilers Community Foundation
Highlight NEW and RECENT support, initiatives, or activities that the Edmonton Oilers Community Foundation has done. This section shows Oilers fans where their charity dollars go and celebrates the positive impact the foundation makes in the community. Focus on recent events, donations, programs, partnerships, or community initiatives from the last few weeks or months. Keep it to 3-4 sentences and make it feel inspiring and community-focused.

[2-3 sentence uplifting sign-off about the Oilers and Oil Country pride.]

=== END OF OUTPUT FORMAT ===

IMPORTANT: Output ONLY the formatted content above. Do NOT include any instructions, notes, or explanations. Do NOT include "CRITICAL:" or "MUST" statements in the output. Just produce the clean formatted digest.
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    response = client.chat.completions.create(
        model="grok-4",
        messages=[{"role": "user", "content": X_PROMPT}],
        temperature=0.85,  # Increased for more variation and creativity
        max_tokens=4000,
        extra_body={"search_parameters": {"mode": "off"}}
    )
    return response

try:
    response = generate_digest_with_grok()
    x_thread = response.choices[0].message.content.strip()
    
    # Log token usage and cost
    if hasattr(response, 'usage') and response.usage:
        usage = response.usage
        logging.info(f"Grok API - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
        estimated_cost = (usage.total_tokens / 1000000) * 0.01
        logging.info(f"Estimated cost: ${estimated_cost:.4f}")
        
        # Track credit usage
        credit_usage["services"]["grok_api"]["x_thread_generation"]["prompt_tokens"] = usage.prompt_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["completion_tokens"] = usage.completion_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["total_tokens"] = usage.total_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["estimated_cost_usd"] = estimated_cost
except Exception as e:
    logging.error(f"Grok API call failed: {e}")
    raise

# Clean Grok output - remove any instructions, footers, or metadata that leaked through
lines = []
skip_remaining = False
for line in x_thread.splitlines():
    # Stop at common footer patterns
    if line.strip().startswith(("**Sources", "Grok", "I used", "[", "===", "INSTRUCTIONS", "OUTPUT FORMAT")):
        break
    # Remove lines that contain instruction keywords
    line_lower = line.lower()
    if any(keyword in line_lower for keyword in [
        "critical:", "must", "do not include", "exclude:", "include only",
        "output only", "do not", "important:", "note:", "remember:",
        "follow exactly", "mandatory", "requirements"
    ]):
        # Skip instruction lines, but allow through if it's part of actual content
        # (e.g., "This is critical for the team" would be fine)
        if not any(phrase in line_lower for phrase in [
            "critical for", "must win", "must be", "do not want", "important game",
            "important for", "note that", "remember when"
        ]):
            continue
    lines.append(line)
x_thread = "\n".join(lines).strip()

# Additional cleanup: Remove any remaining instruction blocks
x_thread = re.sub(r'\*\*CRITICAL:.*?\*\*', '', x_thread, flags=re.DOTALL | re.IGNORECASE)
x_thread = re.sub(r'\*\*MUST.*?\*\*', '', x_thread, flags=re.DOTALL | re.IGNORECASE)
x_thread = re.sub(r'===.*?===', '', x_thread, flags=re.DOTALL)
x_thread = re.sub(r'\n{3,}', '\n\n', x_thread)  # Clean up multiple newlines

# Extract and track used content to prevent repetition
def extract_section_content(text: str, section_name: str) -> str:
    """Extract content from a specific section of the digest."""
    # Try multiple patterns to find the section
    patterns = [
        rf'###\s+{section_name}.*?\n(.*?)(?=\n###|\n━━|$)',
        rf'##\s+{section_name}.*?\n(.*?)(?=\n##|\n###|\n━━|$)',
        rf'{section_name}.*?\n(.*?)(?=\n###|\n##|\n━━|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(1).strip()
            # Remove markdown formatting
            content = re.sub(r'\*\*', '', content)
            content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
            # Limit to first 500 chars to avoid storing too much
            return content[:500]
    return ""

# Extract sections and add to tracker
today_date = datetime.date.today().isoformat()

historical_fact = extract_section_content(x_thread, "Vintage Oil")
if historical_fact:
    content_tracker["historical_facts"].append({
        "date": today_date,
        "content": historical_fact
    })
    logging.info("Tracked new historical fact")

drip_topic = extract_section_content(x_thread, "The Drip")
if drip_topic:
    content_tracker["drip_topics"].append({
        "date": today_date,
        "content": drip_topic
    })
    logging.info("Tracked new drip topic")

oil_country_moment = extract_section_content(x_thread, "80s Vibes")
if oil_country_moment:
    content_tracker["oil_country_moments"].append({
        "date": today_date,
        "content": oil_country_moment
    })
    logging.info("Tracked new 80s Vibes moment")

foundation_activity = extract_section_content(x_thread, "Edmonton Oilers Community Foundation")
if foundation_activity:
    content_tracker["foundation_activities"].append({
        "date": today_date,
        "content": foundation_activity
    })
    logging.info("Tracked new foundation activity")

# Save updated tracker
save_used_content_tracker(content_tracker)

# Save X thread
x_path = digests_dir / f"Lube_Change_{datetime.date.today():%Y%m%d}.md"
with open(x_path, "w", encoding="utf-8") as f:
    f.write(x_thread)
logging.info(f"X thread saved to {x_path}")

# Format for X posting (remove markdown, clean up)
def format_digest_for_x(digest: str) -> str:
    """Format digest for X posting."""
    formatted = digest
    
    # Remove markdown headers but keep text
    formatted = re.sub(r'^#+\s+', '', formatted, flags=re.MULTILINE)
    
    # Convert Imarkdown bold to plain text
    formatted = re.sub(r'\*\*(.*?)\*\*', r'\1', formatted)
    
    # Clean up URLs
    formatted = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\2', formatted)
    
    # Remove excessive blank lines
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)
    
    return formatted.strip()

formatted_thread = format_digest_for_x(x_thread)

# ========================== TWEEPY X CLIENT FOR AUTO-POSTING ==========================
tweet_id = None
if ENABLE_X_POSTING:
    import tweepy

    x_client = tweepy.Client(
        consumer_key=os.getenv("PLANETTERRIAN_X_CONSUMER_KEY"),
        consumer_secret=os.getenv("PLANETTERRIAN_X_CONSUMER_SECRET"),
        access_token=os.getenv("PLANETTERRIAN_X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("PLANETTERRIAN_X_ACCESS_TOKEN_SECRET"),
        bearer_token=os.getenv("PLANETTERRIAN_X_BEARER_TOKEN"),
        wait_on_rate_limit=True
    )
    logging.info("@lubechange_oilers X posting client ready")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== RSS FEED FUNCTIONS (DEFINED BEFORE PODCAST GENERATION) ==========================
def get_audio_duration(path: Path) -> float:
    """Return duration in seconds for an audio file."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
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
                # Parse date from filename
                episode_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                
                # Get file size
                file_size = mp3_file.stat().st_size if mp3_file.exists() else 0
                
                # Get duration
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
    fg.description("Daily Edmonton Oilers news from Oil Country. Hosted by Patrick in Vancouver, Canada.")
    fg.language('en-us')
    fg.copyright(f"Copyright {datetime.date.today().year}")
    fg.podcast.itunes_author("Patrick")
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

# ========================== GENERATE PODCAST SCRIPT ==========================
if not ENABLE_PODCAST or skip_podcast_today:
    if skip_podcast_today:
        logging.info("Episode for today already exists. Skipping podcast script generation and audio processing.")
        logging.info("Note: RSS feed repair will still run to ensure all episodes are included.")
    else:
        logging.info("Podcast generation is disabled (ENABLE_PODCAST = False). Skipping podcast script generation, audio processing, and RSS feed updates.")
    final_mp3 = None
else:
    POD_PROMPT = f"""=== INSTRUCTIONS (DO NOT INCLUDE IN OUTPUT) ===

You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Lube Change - Oilers Daily News" Episode {episode_num}.

HOST: Patrick in Vancouver, Canada. Authentic Oilers fan with Alberta roots, knowledgeable about hockey and the Oilers. Voice like a sports radio host breaking Oilers news, not robotic.

BRAND PERSONALITY: Lube Change - Oilers Daily News. Daily Edmonton Oilers news from Oil Country. Passionate, knowledgeable, authentic voice.

FOCUS REQUIREMENTS:
- ONLY discuss news that DIRECTLY relates to the Edmonton Oilers
- Focus on: Oilers games, Oilers players, Oilers trades, Oilers roster moves, Oilers coaching, Oilers management, Oilers injuries, Oilers draft picks, Oilers prospects, Oilers team news
- DO NOT discuss: General NHL news that doesn't specifically impact the Oilers, news about other teams unless it directly affects the Oilers, league-wide news that doesn't mention the Oilers
- Every story must be about the Oilers or how something impacts the Oilers specifically

SPEECH REQUIREMENTS:
- Start every line with "Patrick:"
- Write in COMPLETE, GRAMMATICALLY CORRECT SENTENCES with proper punctuation
- Use proper punctuation: periods, commas, question marks, exclamation points
- Add natural pauses with commas and periods - don't create run-on sentences
- Each sentence should be clear, complete, and well-structured
- Use varied sentence lengths for natural rhythm (mix short and longer sentences)
- Don't read URLs aloud - mention source names naturally
- Be enthusiastic and excited about the Oilers and Oil Country - show genuine passion
- Use natural dates ("today", "this morning") not exact timestamps
- For numbers: Write them as words when it sounds natural (e.g., "twenty-five goals" not "25 goals" in speech)
- For player numbers: Say "number ninety-seven" not "#97"
- For scores: Say "five to two" not "5-2"
- For statistics: Write out fully (e.g., "three point five goals against average" not "3.5 GAA")
- Use ONLY information from the digest below - nothing else
- Emphasize Oilers pride and Oil Country spirit through enthusiasm, not extra words
- Make it sound like natural, professional conversation - clear, articulate, and engaging
- Use proper grammar and complete thoughts - no fragments or incomplete sentences

DELIVERY STYLE:
- Focus on DELIVERING THE NEWS with enthusiasm - don't add unnecessary hockey terminology
- Be enthusiastic about the stories themselves, not about using hockey words
- Tell the news stories clearly and with excitement - let the content speak for itself
- Don't add extra hockey context or explanations unless the story requires it
- Keep it conversational and natural - like a friend excitedly sharing Oilers news
- Avoid technical hockey jargon, abbreviations, or terminology unless the story specifically requires it
- WORD CHOICE RESTRICTIONS: DO NOT use these hockey-specific terms that don't belong in natural speech:
  * DO NOT say "assists" - instead use: "helpers", "setups", "passes that led to goals", "playmaking"
  * DO NOT say "shootout" - instead use: "penalty shots", "deciding round", "tiebreaker"
  * DO NOT add unnecessary hockey terminology just to sound "hockey-like"
  * Focus on the story, not on using hockey words - enthusiasm comes from delivery, not terminology

=== OUTPUT FORMAT (INCLUDE ONLY THIS IN YOUR RESPONSE) ===

[Intro music - 10 seconds]
Patrick: Welcome to Lube Change - Oilers Daily News, episode {episode_num}. It is {today_str}. I'm Patrick coming to you from Vancouver, sharing the latest from Oil Country. Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps. Now let's dive into today's Oilers news.

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title with enthusiasm, then explain the story and why it matters for Oilers fans
- Oil Leaks: Explain why this story is important for the team and fans
- Vintage Oil: Share the historical fact with enthusiasm and context
- The Drip: Present what fans are talking about with energy, like you're breaking the latest buzz
- 80s Vibes: Share the moment with passion and Oilers pride
- Edmonton Oilers Community Foundation: Highlight the recent foundation activities with pride and enthusiasm, emphasizing the positive impact on the community and showing fans where their charity dollars go

[FIRST AD - Planetterrian]
Patrick: [Write an enthusiastic, natural ad for Planetterrian Daily. Must include: This podcast is made possible by Planetterrian Daily. It's a daily science, longevity, and health podcast hosted by Patrick in Vancouver. It covers groundbreaking scientific discoveries, health breakthroughs, and cutting-edge research. Mention that listeners can find it wherever they get podcasts or visit planetterrian.com. Include the tagline about technology meeting compassion. Make it sound natural and enthusiastic, like Patrick is genuinely excited about the podcast. Keep it to 4-5 sentences.]

[SECOND AD - Tesla Shorts Time]
Patrick: [Write an enthusiastic, natural ad for Tesla Shorts Time Daily. Must include: Lube Change is also made possible by Tesla Shorts Time Daily. It's a daily podcast about Tesla news, stock updates, and electric vehicles hosted by Patrick. It covers new vehicle releases, stock movements, and all the latest Tesla developments. Perfect for Tesla fans and investors. Mention listeners can subscribe wherever they get podcasts. Thank Tesla Shorts Time for making Lube Change possible. Make it sound natural and enthusiastic, like Patrick is genuinely excited about the podcast. Keep it to 4-5 sentences.]

[Closing]
Patrick: That's Lube Change - Oilers Daily News for today. Thanks for tuning in from Oil Country. Let's go Oilers! We'll catch you tomorrow on Lube Change!

=== END OF OUTPUT FORMAT ===

Here is today's complete formatted digest. Use ONLY this content:

{x_thread}

IMPORTANT: Output ONLY the podcast script. Do NOT include any instructions, notes, explanations, or "CRITICAL:" statements. Just produce the clean script with Patrick's lines.
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        response = client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": POD_PROMPT}],
            temperature=0.7,
            max_tokens=4000
        )
        return response
    
    logging.info("Generating podcast script with Grok (this may take 1-2 minutes)...")
    try:
        podcast_response = generate_podcast_script_with_grok()
        podcast_script = podcast_response.choices[0].message.content.strip()
        
        # Log token usage if available
        if hasattr(podcast_response, 'usage') and podcast_response.usage:
            usage = podcast_response.usage
            logging.info(f"Podcast script generation - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
            estimated_cost = (usage.total_tokens / 1000000) * 0.01
            logging.info(f"Estimated cost: ${estimated_cost:.4f}")
            
            # Track credit usage
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["prompt_tokens"] = usage.prompt_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["completion_tokens"] = usage.completion_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["total_tokens"] = usage.total_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["estimated_cost_usd"] = estimated_cost
    except Exception as e:
        logging.error(f"Grok API call for podcast script failed: {e}")
        raise

    # Clean podcast script - remove any instructions that leaked through
    # Remove instruction blocks and keywords
    podcast_script = re.sub(r'===.*?===', '', podcast_script, flags=re.DOTALL)
    podcast_script = re.sub(r'\*\*CRITICAL:.*?\*\*', '', podcast_script, flags=re.DOTALL | re.IGNORECASE)
    podcast_script = re.sub(r'\*\*MUST.*?\*\*', '', podcast_script, flags=re.DOTALL | re.IGNORECASE)
    podcast_script = re.sub(r'\n{3,}', '\n\n', podcast_script)  # Clean up multiple newlines
    
    # Remove unwanted hockey terms and replace with natural alternatives
    # Replace "assists" with natural alternatives
    podcast_script = re.sub(r'\bassists\b', 'helpers', podcast_script, flags=re.IGNORECASE)
    podcast_script = re.sub(r'\bassist\b', 'helper', podcast_script, flags=re.IGNORECASE)
    # Replace "shootout" with natural alternatives
    podcast_script = re.sub(r'\bshootout\b', 'penalty shots', podcast_script, flags=re.IGNORECASE)
    podcast_script = re.sub(r'\bshoot-out\b', 'penalty shots', podcast_script, flags=re.IGNORECASE)
    podcast_script = re.sub(r'\bshoot out\b', 'penalty shots', podcast_script, flags=re.IGNORECASE)
    
    # Remove lines that contain instruction keywords (but allow natural speech)
    lines = []
    for line in podcast_script.splitlines():
        line_lower = line.lower()
        # Skip instruction lines
        if any(keyword in line_lower for keyword in [
            "instructions", "output format", "end of", "important:", "do not include",
            "critical:", "must:", "requirements:", "focus requirements"
        ]):
            if not any(phrase in line_lower for phrase in [
                "jason:", "[", "intro music", "closing", "first ad", "second ad"
            ]):
                continue
        lines.append(line)
    podcast_script = "\n".join(lines).strip()
    
    # Save transcript
    transcript_path = digests_dir / f"podcast_transcript_{datetime.date.today():%Y%m%d}.txt"
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# Lube Change - Oilers Daily News | Ep {episode_num} | {today_str}\n\n{podcast_script}")
    logging.info("Natural podcast script generated")

    # ========================== TTS (VOICE) ==========================
    logging.info(f"TTS provider selected: {TTS_PROVIDER}")

    def _chunk_text(text: str, max_chars: int) -> List[str]:
        """Split long text into chunks for local TTS models."""
        cleaned = re.sub(r"\s+", " ", (text or "")).strip()
        if not cleaned:
            return []
        if max_chars <= 0 or len(cleaned) <= max_chars:
            return [cleaned]

        chunks: List[str] = []
        start = 0
        n = len(cleaned)
        while start < n:
            end = min(start + max_chars, n)
            window = cleaned[start:end]

            # Prefer cutting at sentence boundaries; fall back to commas; then hard cut.
            candidates = [window.rfind("."), window.rfind("!"), window.rfind("?"), window.rfind(";"), window.rfind(":")]
            cut = max(candidates)
            if cut < int(max_chars * 0.5):
                cut = window.rfind(",")
            if cut < int(max_chars * 0.5):
                cut = len(window) - 1

            piece = window[: cut + 1].strip()
            if piece:
                chunks.append(piece)
            start += cut + 1

        return chunks

    def _prepare_chatterbox_voice_prompt(tmp_dir: Path) -> Path:
        """
        Return a local WAV file suitable for Chatterbox's audio_prompt_path.
        
        Priority order:
        1. CHATTERBOX_VOICE_PROMPT_PATH (env var or direct path)
        2. CHATTERBOX_VOICE_PROMPT_BASE64 (base64 encoded audio)
        3. Permanent voice prompt in assets/voice_prompts/ (if exists)
        4. Derive from Planetterrian episodes only (same host voice)
        """
        created_src = False
        episode_mode = False

        if CHATTERBOX_VOICE_PROMPT_PATH:
            src = Path(CHATTERBOX_VOICE_PROMPT_PATH).expanduser()
        elif CHATTERBOX_VOICE_PROMPT_BASE64:
            raw = base64.b64decode(CHATTERBOX_VOICE_PROMPT_BASE64)
            src = tmp_dir / "chatterbox_voice_prompt_input.mp3"
            src.write_bytes(raw)
            created_src = True
        else:
            # Check for permanent voice prompt in assets directory (highest priority fallback)
            assets_voice_prompts = project_root / "assets" / "voice_prompts"
            if assets_voice_prompts.exists():
                # Look for common voice prompt filenames (in priority order)
                prompt_candidates = [
                    assets_voice_prompts / "patrick_voice_prompt.wav",
                    assets_voice_prompts / "voice_prompt.wav",
                    assets_voice_prompts / "chatterbox_voice_prompt.wav",
                ]
                # Also check for any .wav files
                existing_wavs = list(assets_voice_prompts.glob("*.wav"))
                if existing_wavs:
                    prompt_candidates.extend(existing_wavs)
                
                for prompt_file in prompt_candidates:
                    if prompt_file.exists():
                        logging.info(f"✅ Using permanent voice prompt: {prompt_file.name}")
                        # Return the prompt file directly (no processing needed - already in correct format)
                        return prompt_file
            
            # Fallback: derive voice prompt from Planetterrian episodes only (same host voice)
            planetterrian_dir = project_root / "digests" / "planetterrian"
            if planetterrian_dir.exists():
                candidates = sorted(
                    list(planetterrian_dir.glob("Planetterrian_Daily_Ep*.mp3")),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if candidates:
                    src = candidates[0]
                    episode_mode = True
                    logging.info(f"Chatterbox voice prompt: deriving from Planetterrian episode: {src.name}")
                else:
                    raise RuntimeError(
                        "No Planetterrian episode MP3s found to derive a Chatterbox voice prompt. "
                        "Either commit at least one Planetterrian episode MP3 to digests/planetterrian/, "
                        "add a permanent voice prompt to assets/voice_prompts/, or set "
                        "CHATTERBOX_VOICE_PROMPT_PATH / CHATTERBOX_VOICE_PROMPT_BASE64."
                    )
            else:
                raise RuntimeError(
                    "Planetterrian directory not found and no permanent voice prompt available. "
                    "Either create digests/planetterrian/ with at least one episode MP3, "
                    "add a permanent voice prompt to assets/voice_prompts/, or set "
                    "CHATTERBOX_VOICE_PROMPT_PATH / CHATTERBOX_VOICE_PROMPT_BASE64."
                )

        if not src.exists():
            raise FileNotFoundError(f"Chatterbox voice prompt source not found: {src}")

        # If src is already a WAV file (permanent prompt), return it directly
        if src.suffix.lower() == '.wav' and not episode_mode and not created_src:
            logging.info(f"Using permanent voice prompt file: {src}")
            return src

        prompt_wav = tmp_dir / "chatterbox_voice_prompt.wav"

        if episode_mode:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{CHATTERBOX_PROMPT_OFFSET_SECONDS:.2f}",
                    "-t",
                    f"{CHATTERBOX_PROMPT_DURATION_SECONDS:.2f}",
                    "-i",
                    str(src),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(prompt_wav),
                ],
                check=True,
                capture_output=True,
            )
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(prompt_wav)],
                check=True,
                capture_output=True,
            )

        if created_src:
            try:
                src.unlink()
            except Exception:
                pass

        return prompt_wav

    def _synthesize_with_chatterbox(text: str, out_wav: Path):
        """Generate a single WAV voice track using the local Chatterbox model + a voice prompt."""
        import inspect
        import contextlib

        try:
            import torch  # noqa: F401
            import torchaudio as ta
            from chatterbox.tts import ChatterboxTTS
        except Exception as exc:
            raise RuntimeError(
                "Chatterbox dependencies missing. Install requirements (torch, torchaudio, chatterbox-tts)."
            ) from exc

        prompt_wav = _prepare_chatterbox_voice_prompt(tmp_dir)
        chunks = _chunk_text(text, CHATTERBOX_MAX_CHARS)
        if not chunks:
            raise RuntimeError("No text provided for TTS.")

        logging.info(f"Chatterbox: generating {len(chunks)} chunks (max {CHATTERBOX_MAX_CHARS} chars each) on device={CHATTERBOX_DEVICE}")

        model = ChatterboxTTS.from_pretrained(device=CHATTERBOX_DEVICE)
        sr = getattr(model, "sr", 16000)

        gen_sig = inspect.signature(model.generate)
        base_kwargs = {}
        if "audio_prompt_path" in gen_sig.parameters:
            base_kwargs["audio_prompt_path"] = str(prompt_wav)
        if "exaggeration" in gen_sig.parameters:
            base_kwargs["exaggeration"] = CHATTERBOX_EXAGGERATION

        chunk_paths: List[Path] = []
        for i, chunk in enumerate(chunks, 1):
            logging.info(f"Chatterbox: chunk {i}/{len(chunks)} ({len(chunk)} chars)")
            with open(os.devnull, "w") as devnull:
                redir = (
                    contextlib.redirect_stdout(devnull),
                    contextlib.redirect_stderr(devnull),
                ) if CHATTERBOX_QUIET else ()
                with contextlib.ExitStack() as stack:
                    for ctx in redir:
                        stack.enter_context(ctx)
                    wav = model.generate(chunk, **base_kwargs)
            if hasattr(wav, "detach"):
                wav = wav.detach().cpu()
            if getattr(wav, "ndim", 0) == 1:
                wav = wav.unsqueeze(0)
            chunk_path = tmp_dir / f"chatterbox_chunk_{i:03d}.wav"
            ta.save(str(chunk_path), wav, sr)
            chunk_paths.append(chunk_path)

        concat_list = tmp_dir / "chatterbox_concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in chunk_paths:
                f.write(f"file '{p}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)],
            check=True,
            capture_output=True,
        )

        # Cleanup intermediate chunk files
        try:
            for p in chunk_paths:
                if p.exists():
                    p.unlink()
            if concat_list.exists():
                concat_list.unlink()
            if prompt_wav.exists():
                prompt_wav.unlink()
        except Exception:
            pass

    # ElevenLabs helper (only used when TTS_PROVIDER == "elevenlabs")
    VOICE_ID = ELEVEN_VOICE_ID

    def validate_elevenlabs_auth():
        """Fail fast with a clear message when the ElevenLabs key is rejected."""
        resp = requests.get(f"{ELEVEN_API}/user", headers={"xi-api-key": ELEVEN_KEY}, timeout=10)
        if resp.status_code == 401:
            raise RuntimeError("ElevenLabs rejected the API key (401). Update ELEVENLABS_API_KEY in .env/GitHub secrets.")
        resp.raise_for_status()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
    )
    def speak(text: str, voice_id: str, filename: str):
        url = f"{ELEVEN_API}/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": ELEVEN_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        }
        payload = {
            "text": text + "!",
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.9,
                "style": 0.85,
                "use_speaker_boost": True
            }
        }
        try:
            r = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
            if r.status_code == 401:
                raise requests.HTTPError(
                    "ElevenLabs returned 401 Unauthorized. Verify ELEVENLABS_API_KEY and that the voice ID is accessible to this account.",
                    response=r,
                )
            r.raise_for_status()
        except requests.HTTPError as exc:
            logging.error("ElevenLabs TTS call failed: %s; response: %s", exc, getattr(exc.response, "text", ""))
            raise
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    # Process podcast script - preserve natural sentence structure and pauses for professional TTS
    full_text_parts = []
    for line in podcast_script.splitlines():
        line = line.strip()
        if line.startswith("[") or not line:
            continue
        if line.startswith("Patrick:"):
            text = line[9:].strip()
            if text:
                full_text_parts.append(text)

    full_text = " ".join(full_text_parts)

    # Professional text preparation for TTS:
    full_text = re.sub(r'([,.!?;:])([^\s])', r'\1 \2', full_text)
    full_text = re.sub(r'([^\s])([,.!?;:])', r'\1\2', full_text)
    full_text = re.sub(r'([.!?])([A-Z])', r'\1 \2', full_text)
    full_text = re.sub(r' +', ' ', full_text)
    full_text = fix_pronunciation(full_text)
    full_text = re.sub(r'\bassists\b', 'helpers', full_text, flags=re.IGNORECASE)
    full_text = re.sub(r'\bassist\b', 'helper', full_text, flags=re.IGNORECASE)
    full_text = re.sub(r'\bshootout\b', 'penalty shots', full_text, flags=re.IGNORECASE)
    full_text = re.sub(r'\bshoot-out\b', 'penalty shots', full_text, flags=re.IGNORECASE)
    full_text = re.sub(r'\bshoot out\b', 'penalty shots', full_text, flags=re.IGNORECASE)
    full_text = re.sub(r' +', ' ', full_text).strip()

    # Track character count for TTS
    credit_usage["services"]["tts_api"]["characters"] = len(full_text)
    credit_usage["services"]["tts_api"]["provider"] = TTS_PROVIDER
    logging.info(f"TTS: {len(full_text)} characters to synthesize (provider={TTS_PROVIDER})")

    # Generate voice file
    try:
        if TTS_PROVIDER == "chatterbox":
            logging.info("Generating voice track with Chatterbox (local model)...")
            voice_file = tmp_dir / "jason_full.wav"
            _synthesize_with_chatterbox(full_text, voice_file)
            if not voice_file.exists():
                raise FileNotFoundError(f"TTS generation failed: voice file not created at {voice_file}")
        elif TTS_PROVIDER == "elevenlabs":
            logging.info("Generating single voice segment with ElevenLabs...")
            validate_elevenlabs_auth()
            voice_file = tmp_dir / "jason_full.mp3"
            speak(full_text, VOICE_ID, str(voice_file))
            if not voice_file.exists():
                raise FileNotFoundError(f"TTS generation failed: voice file not created at {voice_file}")
        else:
            raise RuntimeError(f"Unsupported TTS provider: {TTS_PROVIDER}")
        audio_files = [str(voice_file)]
        logging.info(f"✅ Generated complete voice track: {voice_file}")
    except Exception as e:
        logging.error(f"❌ TTS generation failed: {e}", exc_info=True)
        raise  # Re-raise to ensure workflow fails visibly

    # ========================== FINAL MIX ==========================
    final_mp3 = digests_dir / f"Lube_Change_Ep{episode_num:03d}_{datetime.date.today():%Y%m%d}.mp3"
    
    MAIN_MUSIC = project_root / "LubechangeOilers.mp3"
    
    # Process and normalize voice in one step
    voice_mix = tmp_dir / "voice_normalized_mix.mp3"
    file_duration = get_audio_duration(voice_file)
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")
    # Professional audio processing: slow slightly, normalize, gently compress, limit
    # Chain: speed ↓10% -> HP/LP -> EBU loudnorm -> gentle compression -> limiter
    subprocess.run([
        "ffmpeg", "-y", "-i", str(voice_file),
        "-af", "atempo=0.9,highpass=f=80,lowpass=f=15000,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-18dB:ratio=2.5:attack=10:release=80:makeup=1.5,alimiter=level_in=1:level_out=0.98:limit=0.98",
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "256k",  # Higher bitrate for better quality
        str(voice_mix)
    ], check=True, capture_output=True, timeout=timeout_seconds)
    
    if not MAIN_MUSIC.exists():
        subprocess.run(["ffmpeg", "-y", "-i", str(voice_mix), str(final_mp3)], check=True, capture_output=True)
        logging.info("Podcast ready (voice-only, no music file found)")
    else:
        # Get voice duration to calculate music timing
        voice_duration = max(get_audio_duration(voice_mix), 0.0)
        logging.info(f"Voice duration: {voice_duration:.2f} seconds")
        
        # Music timing - Professional intro with perfect overlap (same as planetterrian)
        music_fade_in_start = max(voice_duration - 25.0, 0.0)
        music_fade_in_duration = min(35.0, voice_duration - music_fade_in_start)
        
        # Create music segments
        # Intro music: doubled from 5 to 10 seconds
        music_intro = tmp_dir / "music_intro.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-t", "10",
            "-af", "volume=0.6",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_intro)
        ], check=True, capture_output=True)
        
        music_overlap = tmp_dir / "music_overlap.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "10", "-t", "3",
            "-af", "volume=0.5",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_overlap)
        ], check=True, capture_output=True)
        
        # Lead out fadeout: doubled from 18 to 36 seconds
        music_fadeout = tmp_dir / "music_fadeout.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "13", "-t", "36",
            "-af", "volume=0.4,afade=t=out:curve=log:st=0:d=36",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_fadeout)
        ], check=True, capture_output=True)
        
        # Adjust silence duration calculation for longer intro (10s instead of 5s)
        middle_silence_duration = max(music_fade_in_start - 31.0, 0.0)
        music_silence = tmp_dir / "music_silence.mp3"
        if middle_silence_duration > 0.1:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{middle_silence_duration:.2f}", "-c:a", "libmp3lame", "-b:a", "192k",
                str(music_silence)
            ], check=True, capture_output=True)
        
        music_fadein = tmp_dir / "music_fadein.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "30", "-t", f"{music_fade_in_duration:.2f}",
            "-af", f"volume=0.4,afade=t=in:st=0:d={music_fade_in_duration:.2f}",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_fadein)
        ], check=True, capture_output=True)
        
        # Lead out tail full: doubled from 30 to 60 seconds
        music_tail_full = tmp_dir / "music_tail_full.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "49", "-t", "60",
            "-af", "volume=0.4",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_tail_full)
        ], check=True, capture_output=True)
        
        # Lead out tail fadeout: doubled from 20 to 40 seconds
        music_tail_fadeout = tmp_dir / "music_tail_fadeout.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "109", "-t", "40",
            "-af", "volume=0.4,afade=t=out:st=0:d=40",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_tail_fadeout)
        ], check=True, capture_output=True)
        
        # Concatenate music
        music_concat_list = tmp_dir / "music_timeline.txt"
        with open(music_concat_list, "w", encoding="utf-8") as f:
            f.write(f"file '{music_intro}'\n")
            f.write(f"file '{music_overlap}'\n")
            f.write(f"file '{music_fadeout}'\n")
            if middle_silence_duration > 0.1:
                f.write(f"file '{music_silence}'\n")
            f.write(f"file '{music_fadein}'\n")
            f.write(f"file '{music_tail_full}'\n")
            f.write(f"file '{music_tail_fadeout}'\n")
        
        background_track = tmp_dir / "background_track.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(music_concat_list),
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(background_track)
        ], check=True, capture_output=True)
        
        # Delay voice to start at 10 seconds (matching doubled intro length)
        voice_delayed = tmp_dir / "voice_delayed.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(voice_mix),
            "-af", "adelay=10000|10000",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(voice_delayed)
        ], check=True, capture_output=True)
        
        # Final mix: voice + music
        logging.info("Mixing voice and music...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(voice_delayed),
            "-i", str(background_track),
            "-filter_complex",
            "[0:a]volume=1.0[a_voice];"
            "[1:a]volume=0.3[a_music];"
            "[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2:weights=3 1[mixed];"
            "[mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
            "-map", "[outfinal]",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(final_mp3)
        ], check=True, capture_output=True)
        
        logging.info("Podcast created successfully with background music")
        
        # Cleanup music temp files
        for tmp_file in [music_intro, music_overlap, music_fadeout, music_fadein, music_tail_full, music_tail_fadeout, music_silence, background_track, voice_delayed, music_concat_list]:
            if tmp_file.exists():
                try:
                    os.remove(str(tmp_file))
                except Exception:
                    pass

    # Update RSS feed
    if final_mp3 and final_mp3.exists():
        try:
            logging.info(f"Updating RSS feed with Episode {episode_num}...")
            audio_duration = get_audio_duration(final_mp3)
            episode_title = f"Lube Change - Oilers Daily News - Episode {episode_num} - {today_str}"
            episode_description = f"Daily Edmonton Oilers news for {today_str}."
            lines = x_thread.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('**') and len(line) > 50:
                    episode_description += line[:400] + "..."
                    break
            
            update_rss_feed(
                rss_path=rss_path,
                episode_num=episode_num,
                episode_title=episode_title,
                episode_description=episode_description,
                episode_date=datetime.date.today(),
                mp3_filename=final_mp3.name,
                mp3_duration=audio_duration,
                mp3_path=final_mp3,
                base_url="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
            )
            logging.info(f"✅ RSS feed successfully updated with Episode {episode_num}")
            logging.info(f"   Episode file: {final_mp3.name}")
            logging.info(f"   RSS feed path: {rss_path}")
            logging.info(f"   RSS feed exists: {rss_path.exists()}")
        except Exception as e:
            logging.error(f"❌ Failed to update RSS feed: {e}", exc_info=True)
            raise  # Re-raise to ensure workflow knows about the failure
    else:
        error_msg = f"❌ Podcast audio file not created - cannot update RSS feed. final_mp3={final_mp3}"
        if final_mp3:
            error_msg += f", exists={final_mp3.exists()}"
        error_msg += ". This means the episode will NOT appear in the RSS feed or GitHub page."
        logging.error(error_msg)
        raise RuntimeError(error_msg)  # Fail the workflow so it's visible
        
    # Check if any episodes are missing from RSS feed (only if podcast was generated)
    # Skip this check if no podcast was generated to avoid re-adding old episodes
    if final_mp3 and final_mp3.exists():
        try:
            existing_episodes = scan_existing_episodes_from_files(
                digests_dir, 
                "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
            )
            
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
                    logging.warning(f"Could not parse RSS feed to check for missing episodes: {e}")
            
            # Find episodes that exist as files but not in RSS feed
            missing_episodes = [ep for ep in existing_episodes if ep['episode_num'] not in rss_episodes]
            
            if missing_episodes:
                logging.warning(f"Found {len(missing_episodes)} episode(s) missing from RSS feed: {[ep['episode_num'] for ep in missing_episodes]}")
                # Add missing episodes to RSS feed
                for ep_data in missing_episodes:
                    try:
                        episode_title = f"Lube Change - Oilers Daily News - Episode {ep_data['episode_num']}"
                        episode_description = f"Daily Edmonton Oilers news for {ep_data['date'].strftime('%B %d, %Y')}."
                        
                        update_rss_feed(
                            rss_path=rss_path,
                            episode_num=ep_data['episode_num'],
                            episode_title=episode_title,
                            episode_description=episode_description,
                            episode_date=ep_data['date'],
                            mp3_filename=ep_data['filename'],
                            mp3_duration=ep_data['duration'],
                            mp3_path=ep_data['path'],
                            base_url="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
                        )
                        logging.info(f"Added missing Episode {ep_data['episode_num']} to RSS feed")
                    except Exception as e:
                        logging.error(f"Failed to add missing episode {ep_data['episode_num']} to RSS feed: {e}", exc_info=True)
        except Exception as e:
            logging.warning(f"Could not scan for missing episodes: {e}", exc_info=True)

# Always check for missing episodes, even if podcast generation was disabled or failed
logging.info("Checking for any episodes missing from RSS feed...")
try:
    existing_episodes = scan_existing_episodes_from_files(
        digests_dir, 
        "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
    )
    
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
            logging.warning(f"Could not parse RSS feed to check for missing episodes: {e}")
    
    # Find episodes that exist as files but not in RSS feed
    missing_episodes = [ep for ep in existing_episodes if ep['episode_num'] not in rss_episodes]
    
    if missing_episodes:
        logging.warning(f"Found {len(missing_episodes)} episode(s) missing from RSS feed: {[ep['episode_num'] for ep in missing_episodes]}")
        # Add missing episodes to RSS feed
        for ep_data in missing_episodes:
            try:
                episode_title = f"Lube Change - Oilers Daily News - Episode {ep_data['episode_num']}"
                episode_description = f"Daily Edmonton Oilers news for {ep_data['date'].strftime('%B %d, %Y')}."
                
                update_rss_feed(
                    rss_path=rss_path,
                    episode_num=ep_data['episode_num'],
                    episode_title=episode_title,
                    episode_description=episode_description,
                    episode_date=ep_data['date'],
                    mp3_filename=ep_data['filename'],
                    mp3_duration=ep_data['duration'],
                    mp3_path=ep_data['path'],
                    base_url="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
                )
                logging.info(f"Added missing Episode {ep_data['episode_num']} to RSS feed")
            except Exception as e:
                logging.error(f"Failed to add missing episode {ep_data['episode_num']} to RSS feed: {e}", exc_info=True)
    else:
        logging.info("All existing episodes are in the RSS feed")
except Exception as e:
    logging.warning(f"Could not scan for missing episodes: {e}", exc_info=True)

# Post to X
if ENABLE_X_POSTING:
    try:
        thread_text = formatted_thread.strip()
        
        # Track X API post call
        credit_usage["services"]["x_api"]["post_calls"] += 1
        
        tweet = x_client.create_tweet(text=thread_text)
        tweet_id = tweet.data['id']
        thread_url = f"https://x.com/lubechange_oilers/status/{tweet_id}"
        logging.info(f"DIGEST POSTED → {thread_url}")
    except Exception as e:
        logging.error(f"X post failed: {e}")

# Cleanup
try:
    for file_path in audio_files:
        if os.path.exists(file_path):
            os.remove(file_path)
    logging.info("Temporary files cleaned up")
except Exception as e:
    logging.warning(f"Cleanup warning: {e}")

# Save credit usage tracking
save_credit_usage(credit_usage, digests_dir)

print("\n" + "="*80)
print("LUBE CHANGE - OILERS DAILY NEWS — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)