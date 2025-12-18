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
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

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

    # Fix dates: multiple formats like "November 19, 2025", "11 December, 2025", "December 11, 2025"
    def replace_date(match):
        month = match.group(1)
        day = match.group(2)
        year = match.group(3)
        try:
            day_num = int(day)
            day_words = number_to_words(day_num)
            # Convert ordinal numbers
            if day_num == 1:
                day_words = "first"
            elif day_num == 2:
                day_words = "second"
            elif day_num == 3:
                day_words = "third"
            elif day_num <= 20:
                if not day_words.endswith(("first", "second", "third")):
                    day_words += "th"
            else:
                if day_num % 10 == 1:
                    day_words = day_words.replace(" one", " first")
                elif day_num % 10 == 2:
                    day_words = day_words.replace(" two", " second")
                elif day_num % 10 == 3:
                    day_words = day_words.replace(" three", " third")
                else:
                    day_words += "th"

            # Convert year to words
            year_num = int(year)
            if year_num >= 2000:
                thousands = year_num // 1000
                remainder = year_num % 1000
                if remainder == 0:
                    year_words = number_to_words(thousands) + " thousand"
                else:
                    year_words = number_to_words(thousands) + " thousand " + number_to_words(remainder)
            else:
                year_words = number_to_words(year_num)

            return f"{month} {day_words}, {year_words}"
        except ValueError:
            return match.group(0)

    text = re.sub(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', replace_date, text, flags=re.IGNORECASE)
    text = re.sub(r'(\d{1,2})\s+(\w+),\s+(\d{4})', lambda m: replace_date(m.group().replace(m.group(1) + ' ' + m.group(2), m.group(2) + ' ' + m.group(1))), text, flags=re.IGNORECASE)

    # Fix times: multiple formats "02:30 PM", "2:30PM", "14:30", "2:30 p.m."
    def replace_time(match):
        hour_str = match.group(1)
        minute_str = match.group(2)
        am_pm = match.group(3).upper() if match.group(3) else ""
        try:
            hour = int(hour_str)
            minute = int(minute_str)

            # Handle 24-hour format
            if not am_pm and hour >= 13:
                hour -= 12
                am_pm = "PM"
            elif not am_pm and hour == 12:
                am_pm = "PM"
            elif not am_pm and hour == 0:
                hour = 12
                am_pm = "AM"
            elif not am_pm:
                am_pm = "AM"

            # Ensure valid hour range
            if hour < 1 or hour > 12:
                return match.group(0)

            hour_word = number_to_words(hour)
            if minute == 0:
                time_str = f"{hour_word} o'clock {am_pm}".strip()
            else:
                minute_word = number_to_words(minute)
                # Handle teen numbers specially (e.g., "fifteen" instead of "fif teen")
                if 10 <= minute <= 19:
                    time_str = f"{hour_word} {minute_word} {am_pm}".strip()
                else:
                    time_str = f"{hour_word} {minute_word} {am_pm}".strip()

            return time_str
        except (ValueError, AttributeError):
            return match.group(0)

    # Match various time formats
    text = re.sub(r'(\d{1,2}):(\d{2})\s*(AM|PM|am|pm|A\.M\.|P\.M\.|a\.m\.|p\.m\.)?', replace_time, text)
    text = re.sub(r'(\d{1,2}):(\d{2})\s*(AM|PM|am|pm|A\.M\.|P\.M\.|a\.m\.|p\.m\.)', replace_time, text)  # Handle periods

    # Fix timezone abbreviations
    text = re.sub(r'\bPST\b', 'Pacific Standard Time', text)
    text = re.sub(r'\bPDT\b', 'Pacific Daylight Time', text)
    text = re.sub(r'\bEST\b', 'Eastern Standard Time', text)
    text = re.sub(r'\bEDT\b', 'Eastern Daylight Time', text)
    text = re.sub(r'\bUTC\b', 'U T C', text)
    text = re.sub(r'\bGMT\b', 'G M T', text)

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

TTS_PROVIDER = _normalize_tts_provider(os.getenv("LUBECHANGE_TTS_PROVIDER", "elevenlabs"))

# Required keys (X credentials for @lubechange_oilers account - using same as planetterrian for now)
required = [
    "GROK_API_KEY"
]
if ENABLE_PODCAST and not TEST_MODE:
    if TTS_PROVIDER == "elevenlabs":
        # ElevenLabs API required
        required.append("ELEVENLABS_API_KEY")
    elif TTS_PROVIDER == "chatterbox":
        if not _chatterbox_deps_available():
            raise OSError(
                "Chatterbox-Turbo selected but dependencies are missing. Install "
                "requirements (torch, torchaudio, chatterbox-tts)."
            )
        pass  # local model, no API key needed
    else:
        raise OSError(
            f"Unknown LUBECHANGE_TTS_PROVIDER '{TTS_PROVIDER}'. Supported providers: 'elevenlabs', 'chatterbox'."
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
CHATTERBOX_MAX_CHARS = _env_int("CHATTERBOX_MAX_CHARS", 2000)  # Increased for Chatterbox - handles larger chunks better than Turbo, better for podcast quality
CHATTERBOX_QUIET = _env_bool("CHATTERBOX_QUIET", True)
CHATTERBOX_VOICE_PROMPT_PATH = os.getenv("CHATTERBOX_VOICE_PROMPT_PATH", "").strip()
CHATTERBOX_VOICE_PROMPT_BASE64 = os.getenv("CHATTERBOX_VOICE_PROMPT_BASE64", "").strip()
CHATTERBOX_PROMPT_OFFSET_SECONDS = _env_float("CHATTERBOX_PROMPT_OFFSET_SECONDS", 35.0)
CHATTERBOX_PROMPT_DURATION_SECONDS = _env_float("CHATTERBOX_PROMPT_DURATION_SECONDS", 10.0)
HF_TOKEN = os.getenv("HF_TOKEN")  # Hugging Face token for Chatterbox-Turbo model access

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
    
    logging.info(f"Fetching Oilers news from {len(rss_feeds)} RSS feeds (parallel)...")
    
    # Known problematic feeds that often fail - track them separately
    problematic_feeds = set()
    problematic_feeds_lock = Lock()
    
    # HTTP settings for RSS fetching
    DEFAULT_HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    HTTP_TIMEOUT_SECONDS = 10
    
    def fetch_single_feed(feed_url: str):
        """Fetch and parse a single RSS feed. Returns (feed_url, articles, source_name) or None on error."""
        source_name = "Unknown"
        try:
            # Fetch RSS feed with timeout and custom headers
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
                with problematic_feeds_lock:
                    if feed_url not in problematic_feeds:
                        problematic_feeds.add(feed_url)
                        # Use debug level for known problematic feeds to reduce noise
                        error_msg = str(feed.bozo_exception)
                        if "not well-formed" in error_msg or "syntax error" in error_msg:
                            logging.debug(f"RSS feed has malformed XML (will skip): {feed_url}")
                        else:
                            logging.debug(f"RSS feed parsing issue (will skip): {feed_url} - {error_msg[:100]}")
                return None
            
            source_name = feed.feed.get("title", "Unknown")
            # Map common feed sources (same mapping as before)
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
                if published_time:
                    if published_time < cutoff_time:
                        continue  # Skip articles older than 36 hours
                    if published_time > now_utc + datetime.timedelta(hours=1):
                        continue  # Skip future articles
                else:
                    published_time = now_utc
                
                title = entry.get("title", "").strip()
                description = entry.get("description", "").strip() or entry.get("summary", "").strip()
                link = entry.get("link", "").strip()
                
                if not title or not link:
                    continue
                
                # FOCUSED FILTERING: Article should be Oilers-related
                title_desc_lower = (title + " " + description).lower()
                
                # Check if this is an Oilers-specific feed
                is_oilers_feed = any(oilers_term in feed_url.lower() for oilers_term in [
                    "oilers", "edmonton", "oilersnation", "coppernblue"
                ])
                is_oilers_source = any(oilers_term in source_name.lower() for oilers_term in [
                    "oilers", "edmonton", "oilersnation", "copper", "blue"
                ])
                
                if not (is_oilers_feed or is_oilers_source):
                    # For general NHL feeds, require explicit Oilers keywords
                    has_oilers_primary = any(keyword in title_desc_lower for keyword in oilers_primary_keywords)
                    if not has_oilers_primary:
                        continue
                
                # Filter out articles clearly about other teams
                title_lower = title.lower()
                title_starts_with_other_team = False
                other_team_mentions = [
                    "maple leafs", "canadiens", "canucks", "flames", "jets", "senators",
                    "bruins", "rangers", "islanders", "devils", "flyers", "penguins",
                    "capitals", "hurricanes", "panthers", "lightning", "predators",
                    "stars", "avalanche", "coyotes", "blackhawks", "red wings", "blue jackets",
                    "wild", "sharks", "kings", "ducks", "golden knights", "kraken"
                ]
                for team in other_team_mentions:
                    team_words = team.split()
                    if len(team_words) == 1:
                        if title_lower.startswith(team + " ") or title_lower.startswith(team + "'") or title_lower.startswith(team + ":"):
                            title_starts_with_other_team = True
                            break
                    elif len(team_words) == 2:
                        title_first_words = title_lower.split()[:2]
                        if title_first_words == team_words or title_lower.startswith(team + " "):
                            title_starts_with_other_team = True
                            break
                
                if title_starts_with_other_team:
                    title_has_oilers = any(keyword in title_lower for keyword in ["oilers", "edmonton oilers", "connor mcdavid", "leon draisaitl", "edmonton"])
                    if not title_has_oilers:
                        continue
                
                article = {
                    "title": title,
                    "description": description,
                    "url": link,
                    "source": source_name,
                    "publishedAt": published_time.isoformat() if published_time else datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "author": entry.get("author", "")
                }
                
                feed_articles.append(article)
            
            return (feed_url, feed_articles, source_name)
        
        except requests.RequestException as e:
            with problematic_feeds_lock:
                if feed_url not in problematic_feeds:
                    problematic_feeds.add(feed_url)
                    logging.debug(f"Network error fetching RSS feed (will skip): {feed_url} - {type(e).__name__}")
            return None
        except Exception as e:
            error_str = str(e)
            if any(keyword in error_str.lower() for keyword in ["not well-formed", "syntax error", "mismatched tag", "invalid token", "404", "not found", "closed connection"]):
                with problematic_feeds_lock:
                    if feed_url not in problematic_feeds:
                        problematic_feeds.add(feed_url)
                        logging.debug(f"RSS feed error (will skip): {feed_url} - {type(e).__name__}")
            else:
                logging.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            return None
    
    # Fetch feeds in parallel (max 10 concurrent requests to avoid overwhelming servers)
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_feed = {executor.submit(fetch_single_feed, feed_url): feed_url for feed_url in rss_feeds}
        for future in as_completed(future_to_feed):
            result = future.result()
            if result:
                feed_url, feed_articles, source_name = result
                logging.info(f"Fetched {len(feed_articles)} articles from {source_name}")
                all_articles.extend(feed_articles)
                raw_articles.extend(feed_articles)
    
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
- Tone: Enthusiastic, knowledgeable, passionate about the Oilers, authentic and conversational, with Oil Country attitude
- Style: Use Oilers slang ("snipe", "dangle", "chirp", "Gordie Howe hat trick"), conversational transitions, engaging hooks
- Audience: Die-hard Oilers fans who want the latest Oilers-specific news and analysis
- Make it PODCAST-READY: Add personality, excitement, and emotional connection that translates well to audio

=== OUTPUT FORMAT (INCLUDE ONLY THIS IN YOUR RESPONSE) ===

GOOD MORNING, OIL COUNTRY! 🏒

It's your favorite grease monkey back in the shop with the freshest Lube Change - {today_str}.

[1-2 sentence engaging hook about today's biggest Oilers story/storyline]

Buckle up, because we've got the stories that matter to Oilers fans...

━━━━━━━━━━━━━━━━━━━━
🔥 HOT TAKES - The Oilers Stories That Matter

🚨 HOT TAKE #1: [ENGAGING TITLE THAT HOOKS LISTENERS]
[2-3 sentences in conversational style: Start with what happened with the Oilers, explain why it matters for Oilers fans. Use Oilers slang and personality. End with: Source: [EXACT URL FROM PRE-FETCHED—no mods]]

🚨 HOT TAKE #2: [ENGAGING TITLE THAT HOOKS LISTENERS]
[Repeat format for 3-15; if <15 items, stop at available count, add a blank line after each item. Make each title exciting and podcast-ready!]

━━━━━━━━━━━━━━━━━━━━
OIL LEAKS - Where We Spill the Real Tea ☕

[2-3 paragraphs of analysis: Pick one major story/development that Oilers fans need to know about. Explain why this matters for the team and fans. Be opinionated, predictive, and connect it to bigger picture. Use phrases like "This changes EVERYTHING" or "Here's the reality check..."]

━━━━━━━━━━━━━━━━━━━━
VINTAGE OIL - Because History Repeats Itself 🕰️

[Share one interesting, lesser-known historical fact about the Edmonton Oilers. Make it engaging and something that even die-hard fans might not know. Connect it to current team/players when possible. Keep it to 2-3 sentences with personality.]

━━━━━━━━━━━━━━━━━━━━
THE DRIP - What Oilers Fans Are Actually Saying 💬

[3-4 sentences capturing what Oilers fans and analysts are talking about RIGHT NOW based on TODAY'S news. Make it feel like eavesdropping on fan conversations in Oil Country. Use local references and current buzz. Include what fans think the team needs to do.]

━━━━━━━━━━━━━━━━━━━━
80S VIBES - Channeling That Dynasty Energy 🎸

[One inspiring/memorable moment from Oilers history, current team, or fan culture. Make it emotional and connective. End with: "Let's go Oilers!"]

━━━━━━━━━━━━━━━━━━━━
OILERS COMMUNITY FOUNDATION - Because Oilers Are About More Than Hockey ❤️

[Highlight NEW and RECENT foundation activities. Show real human impact and community connection. Make it inspiring and specific about recent initiatives, donations, and programs. Focus on the positive change in Oil Country.]

━━━━━━━━━━━━━━━━━━━━
[2-3 sentence podcast-ready sign-off that's memorable and emotional. Reference Oil Country pride, team spirit, and call to action for fans.]

=== END OF OUTPUT FORMAT ===

IMPORTANT: Output ONLY the formatted content above. Do NOT include any instructions, notes, or explanations. Do NOT include "CRITICAL:" or "MUST" statements in the output. Just produce the clean formatted digest.
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    response = client.chat.completions.create(
        model="grok-4",
        messages=[{"role": "user", "content": X_PROMPT}],
        temperature=0.85,  # Increased for more variation and creativity
        max_tokens=3500,  # Reduced from 4000 for faster generation
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
# Cache for audio duration lookups to avoid redundant ffprobe calls
_audio_duration_cache: Dict[Path, float] = {}

def get_audio_duration(path: Path) -> float:
    """Return duration in seconds for an audio file. Uses cache to avoid redundant ffprobe calls."""
    # Check cache first
    if path in _audio_duration_cache:
        return _audio_duration_cache[path]
    
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
        duration = float(result.stdout.strip())
        _audio_duration_cache[path] = duration  # Cache the result
        return duration
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

HOST: Patrick in Vancouver, Canada. Authentic Oilers fan with Alberta roots, knowledgeable about hockey and the Oilers. Voice like an excited sports radio host breaking Oilers news - passionate, conversational, and full of Oil Country energy!

BRAND PERSONALITY: Lube Change - Oilers Daily News. Daily Edmonton Oilers news from Oil Country. Passionate, knowledgeable, authentic voice with personality, Oilers slang, and genuine excitement.

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
- Emphasize Oilers pride and Oil Country spirit through enthusiasm and personality
- Make it sound like natural, professional conversation - clear, articulate, and engaging
- Use proper grammar and complete thoughts - no fragments or incomplete sentences

DELIVERY STYLE:
- ADD OILERS PERSONALITY: Use appropriate Oilers slang ("snipe", "dangle", "chirp", "Gordie Howe hat trick", "statement game", "Oilers way") when it fits naturally
- Be enthusiastic about the stories with genuine Oilers passion
- Tell the news stories clearly and with excitement - let the content speak for itself
- Keep it conversational and natural - like an excited friend sharing Oilers news
- Add emotional reactions and Oilers fan perspective
- Use phrases like "Can you believe it?", "This is huge for Oilers fans!", "Oil Country is buzzing!"
- Make transitions engaging: "Speaking of...", "But wait, there's more...", "You won't believe this..."

=== OUTPUT FORMAT (INCLUDE ONLY THIS IN YOUR RESPONSE) ===

[Intro music - 10 seconds]
Patrick: GOOD MORNING, OIL COUNTRY! Welcome to Lube Change - Oilers Daily News, episode {episode_num}. It is {today_str}. I'm Patrick coming to you from Vancouver, bringing you the freshest Oilers news straight from the heart of Alberta. If you're loving the show, smash that like button, share with your Oilers buddies, and drop us a five-star review - it keeps the Oilers machine running! Let's jump into today's hottest Oilers stories!

[Narrate EVERY item from the digest in order - no skipping, with personality!]
- For each HOT TAKE: Read the title with excitement and Oilers energy, then dive into the story explaining why it matters for Oilers fans. Add reactions like "Can you believe it?" or "This is huge!"
- Oil Leaks: Explain why this story changes everything for the team and fans - be opinionated and predictive
- Vintage Oil: Share the historical fact with enthusiasm, connect it to today's Oilers when possible
- The Drip: Present what fans are talking about RIGHT NOW with energy, like you're breaking the latest Oil Country buzz
- 80s Vibes: Share the moment with passion and emotional connection to Oilers legacy
- Edmonton Oilers Community Foundation: Highlight the foundation activities with pride, show the real human impact and community connection

[FIRST AD - Planetterrian]
Patrick: [Write an enthusiastic, natural ad for Planetterrian Daily with Oilers personality. Must include: Lube Change is made possible by Planetterrian Daily - my other daily podcast where I dive into groundbreaking science, longevity breakthroughs, and cutting-edge health research. Technology meeting compassion, keeping us all living longer and stronger. Find it wherever you get podcasts or visit planetterrian.com. Trust me, if you love Oilers innovation, you'll love the science behind human potential!]

[SECOND AD - Tesla Shorts Time]
Patrick: [Write an enthusiastic, natural ad for Tesla Shorts Time Daily with Oilers flair. Must include: Lube Change is also powered by Tesla Shorts Time Daily - my daily dive into Tesla news, stock updates, and electric vehicle revolutions. From Cybertruck reveals to stock surges, we cover it all for Tesla fans and investors. Subscribe wherever you get your podcasts, and thank you Tesla Shorts Time for helping keep Oil Country connected! The future of driving meets the heart of hockey!]

[Closing with personality]
Patrick: That's all the Oilers news we can fit into today's Lube Change! From the rinks of Rogers Place to the hearts of fans worldwide, the Oilers keep proving why Oil Country is unmatched in spirit and grit. Stay frosty, stay faithful, and remember: ONE TEAM. ONE HEART. ONE OIL COUNTRY! Let's go Oilers! We'll catch you tomorrow with more from the Oil! 🇨🇦🏒

=== END OF OUTPUT FORMAT ===

Here is today's complete formatted digest. Use ONLY this content:

{x_thread}

IMPORTANT: Output ONLY the podcast script. Do NOT include any instructions, notes, explanations, or "CRITICAL:" statements. Just produce the clean script with Patrick's lines.
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        response = client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": POD_PROMPT}],
            temperature=0.7,
            max_tokens=3500  # Reduced from 4000 for faster generation
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

        # Set Hugging Face token for authentication if available
        if HF_TOKEN:
            import huggingface_hub
            huggingface_hub.login(HF_TOKEN)
            logging.info("✅ Logged into Hugging Face Hub with token")

        # Initialize Chatterbox-Turbo
        model = ChatterboxTTS.from_pretrained(device=CHATTERBOX_DEVICE)
        sr = getattr(model, "sr", 24000)  # Chatterbox uses 24kHz by default

        # Configure optimal settings for podcast quality
        base_kwargs = {
            "audio_prompt_path": str(prompt_wav),
            "cfg_weight": 0.5,  # Balanced control - helps maintain voice consistency
            "exaggeration": 0.4  # Slightly lower for natural podcast delivery
        }

        # Generate chunks in parallel for maximum speed
        def generate_single_chunk(chunk_data):
            """Generate a single chunk."""
            i, chunk = chunk_data
            chunk_path = tmp_dir / f"chatterbox_chunk_{i:03d}.wav"

            try:
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

                # Validate generated audio
                if wav is None or (hasattr(wav, "numel") and wav.numel() == 0):
                    raise RuntimeError(f"Chatterbox generated empty audio for chunk {i}")

                # Check audio duration (estimate: samples / sample_rate)
                num_samples = wav.shape[-1] if hasattr(wav, "shape") else 0
                duration_seconds = num_samples / sr if num_samples > 0 else 0

                # Warn if chunk is suspiciously short
                expected_min_duration = len(chunk) / 20  # Rough estimate: ~20 chars per second
                if duration_seconds < expected_min_duration * 0.1:  # Less than 10% of expected
                    logging.warning(f"⚠️ Chunk {i} generated very short audio: {duration_seconds:.2f}s (expected ~{expected_min_duration:.2f}s for {len(chunk)} chars)")

                ta.save(str(chunk_path), wav, sr)

                # Verify file was created and has content
                if not chunk_path.exists():
                    raise RuntimeError(f"Failed to save chunk {i} to {chunk_path}")
                chunk_size = chunk_path.stat().st_size
                if chunk_size < 1000:  # Less than 1KB is suspicious
                    raise RuntimeError(f"Chunk {i} file is too small ({chunk_size} bytes) - TTS may have failed")

                logging.info(f"✅ Chunk {i} generated: {duration_seconds:.2f}s ({chunk_size} bytes)")
                return chunk_path

            except Exception as e:
                logging.error(f"❌ Failed to generate chunk {i}/{len(chunks)}: {e}", exc_info=True)
                raise RuntimeError(f"TTS generation failed for chunk {i}: {e}") from e

        # Process chunks in parallel
        logging.info(f"🚀 Generating {len(chunks)} chunks in parallel (up to 4 concurrent)...")

        from concurrent.futures import ThreadPoolExecutor, as_completed
        chunk_data = list(enumerate(chunks, 1))

        chunk_paths: List[Path] = []
        with ThreadPoolExecutor(max_workers=4) as executor:  # Limit to 4 concurrent to avoid resource issues
            future_to_chunk = {executor.submit(generate_single_chunk, data): data[0] for data in chunk_data}

            for future in as_completed(future_to_chunk):
                chunk_num = future_to_chunk[future]
                try:
                    chunk_path = future.result()
                    chunk_paths.append(chunk_path)
                    logging.info(f"✅ Chunk {chunk_num} completed")
                except Exception as exc:
                    logging.error(f"❌ Chunk {chunk_num} failed: {exc}")
                    raise

        # Sort chunk paths by chunk number to ensure proper concatenation order
        chunk_paths.sort(key=lambda x: int(x.stem.split('_')[-1]))

        concat_list = tmp_dir / "chatterbox_concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in chunk_paths:
                f.write(f"file '{p}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)],
            check=True,
            capture_output=True,
        )
        
        # Validate final concatenated audio file
        if not out_wav.exists():
            raise RuntimeError(f"Failed to create concatenated audio file: {out_wav}")
        
        final_size = out_wav.stat().st_size
        if final_size < 10000:  # Less than 10KB is suspicious for any podcast
            raise RuntimeError(f"Concatenated audio file is too small ({final_size} bytes) - TTS generation likely failed")
        
        # Check duration using ffprobe
        try:
            duration_check = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(out_wav)],
                capture_output=True,
                text=True,
                check=True,
            )
            duration = float(duration_check.stdout.strip())
            expected_min_duration = len(text) / 20  # Rough estimate: ~20 chars per second
            if duration < expected_min_duration * 0.1:  # Less than 10% of expected
                raise RuntimeError(f"Final audio duration ({duration:.2f}s) is suspiciously short for {len(text)} characters (expected ~{expected_min_duration:.2f}s)")
            logging.info(f"✅ Final concatenated audio: {duration:.2f}s ({final_size} bytes)")
        except Exception as e:
            logging.warning(f"Could not verify audio duration: {e}")
            # Don't fail if duration check fails, but log it

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

    def _chunk_text_for_elevenlabs(text: str, max_chars: int = 4000) -> List[str]:
        """
        Split text into chunks for ElevenLabs API (limit is 5000, use 4000 for more safety).
        Splits at sentence boundaries to avoid audio breaks and ensure complete thoughts.
        """
        if len(text) <= max_chars:
            return [text]

        chunks = []
        remaining = text.strip()

        while len(remaining) > max_chars:
            # Find the best split point: prefer sentence endings, then commas, then spaces
            chunk_candidate = remaining[:max_chars]

            # Look for sentence endings (., !, ?) anywhere in the chunk, prioritizing later ones
            best_split = -1
            sentence_endings = []

            for i, char in enumerate(chunk_candidate):
                if char in '.!?':
                    sentence_endings.append(i + 1)  # +1 to include the punctuation

            # Use the last (rightmost) sentence ending in the chunk
            if sentence_endings:
                best_split = sentence_endings[-1]
            else:
                # Fallback: look for commas or semicolons
                for i, char in enumerate(chunk_candidate):
                    if char in ',;':
                        best_split = i + 1  # +1 to include the punctuation

            # Last resort: look for spaces to avoid breaking words
            if best_split == -1:
                # Find the last space in the last 30% of the chunk
                search_start = int(max_chars * 0.7)
                for i in range(len(chunk_candidate) - 1, search_start - 1, -1):
                    if chunk_candidate[i] == ' ':
                        best_split = i + 1  # +1 to include the space
                        break

            # Absolute last resort: hard cut
            if best_split == -1 or best_split == 0:
                best_split = max_chars

            chunk_text = remaining[:best_split].strip()
            if chunk_text:  # Only add non-empty chunks
                chunks.append(chunk_text)
            remaining = remaining[best_split:].strip()

        if remaining:
            chunks.append(remaining)

        # Log chunking for debugging
        if len(chunks) > 1:
            logging.info(f"Split text into {len(chunks)} chunks for ElevenLabs: {[len(c) for c in chunks]} characters")

        return chunks

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
    )
    def _speak_chunk(text: str, voice_id: str, chunk_file: Path):
        """Generate audio for a single text chunk."""
        url = f"{ELEVEN_API}/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": ELEVEN_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.9,
                "style": 0.85,
                "use_speaker_boost": True
            }
        }
        with requests.post(
            url,
            json=payload,
            headers=headers,
            stream=True,
            timeout=60,
        ) as r:
            if r.status_code >= 500 or r.status_code == 429:
                r.raise_for_status()
            r.raise_for_status()
            with open(chunk_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

    def speak(text: str, voice_id: str, filename: str):
        """
        Generate audio with intelligent chunking and seamless concatenation.
        Handles texts longer than ElevenLabs API limits by splitting at sentence boundaries.
        """
        # Split text into chunks if needed
        chunks = _chunk_text_for_elevenlabs(text)

        if len(chunks) == 1:
            # Single chunk: generate directly
            _speak_chunk(text + "!", voice_id, Path(filename))
            logging.info(f"ElevenLabs TTS: Generated single chunk ({len(text)} chars)")
        else:
            # Multiple chunks: generate each and concatenate seamlessly
            logging.info(f"ElevenLabs TTS: Splitting into {len(chunks)} chunks for seamless generation")
            chunk_files = []
            tmp_dir = Path(filename).parent

            try:
                for i, chunk_text in enumerate(chunks):
                    chunk_file = tmp_dir / f"tts_chunk_{i:03d}.mp3"
                    # Add punctuation to all but the last chunk to maintain flow
                    if i < len(chunks) - 1:
                        chunk_text = chunk_text.rstrip('.!?') + '.'
                    else:
                        chunk_text = chunk_text + "!"

                    _speak_chunk(chunk_text, voice_id, chunk_file)
                    chunk_files.append(chunk_file)
                    logging.info(f"Generated chunk {i+1}/{len(chunks)} ({len(chunk_text)} chars)")

                # Concatenate chunks seamlessly using ffmpeg
                concat_list = tmp_dir / "elevenlabs_concat.txt"
                with open(concat_list, "w", encoding="utf-8") as f:
                    for chunk_file in chunk_files:
                        f.write(f"file '{chunk_file.absolute()}'\n")

                # Use ffmpeg concat with seamless joining
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_list),
                    "-c", "copy",  # Stream copy for speed and no re-encoding artifacts
                    str(filename)
                ], check=True, capture_output=True, timeout=300)

                logging.info(f"ElevenLabs TTS: Concatenated {len(chunks)} chunks seamlessly")

            finally:
                # Cleanup chunk files
                for chunk_file in chunk_files:
                    try:
                        if chunk_file.exists():
                            chunk_file.unlink()
                    except Exception:
                        pass
                try:
                    if concat_list.exists():
                        concat_list.unlink()
                except Exception:
                    pass

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

    full_text = " ".join(full_text_parts).strip()

    # Ensure we have content and log it for debugging
    if not full_text:
        logging.error("ERROR: No text content extracted from podcast script!")
        raise RuntimeError("Podcast script processing failed - no text content found")

    logging.info(f"Extracted podcast script: {len(full_text)} characters")
    if len(full_text) < 500:
        logging.error(f"ERROR: Extracted text is too short ({len(full_text)} chars). This will result in a very short podcast!")
        logging.error(f"First 1000 chars of extracted text: {full_text[:1000]}")
        raise RuntimeError(f"Podcast script is too short ({len(full_text)} chars) - expected at least 500 characters")
    
    # Estimate expected duration (roughly 20 chars per second of speech)
    estimated_duration = len(full_text) / 20
    logging.info(f"Estimated podcast duration: ~{estimated_duration:.1f} seconds ({estimated_duration/60:.1f} minutes)")

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
    import time
    tts_start_time = time.time()
    try:
        if TTS_PROVIDER == "elevenlabs":
            logging.info("Generating voice track with ElevenLabs...")
            validate_elevenlabs_auth()
            voice_file = tmp_dir / "jason_full.mp3"
            speak(full_text, VOICE_ID, str(voice_file))
            if not voice_file.exists():
                raise FileNotFoundError(f"TTS generation failed: voice file not created at {voice_file}")

            # Validate voice file size and duration
            voice_file_size = voice_file.stat().st_size
            if voice_file_size < 10000:  # Less than 10KB is suspicious
                raise RuntimeError(f"Generated voice file is too small ({voice_file_size} bytes) - TTS likely failed")

            voice_audio_duration = get_audio_duration(voice_file)
            expected_min_duration = len(full_text) / 20  # Rough estimate: ~20 chars per second
            if voice_audio_duration < expected_min_duration * 0.1:  # Less than 10% of expected
                raise RuntimeError(f"Generated voice duration ({voice_audio_duration:.2f}s) is suspiciously short for {len(full_text)} characters (expected ~{expected_min_duration:.2f}s)")

            audio_files = [str(voice_file)]
            tts_duration = time.time() - tts_start_time
            logging.info(f"✅ Generated complete voice track: {voice_file} ({voice_audio_duration:.2f}s audio, {tts_duration:.1f}s generation time, {len(full_text)/tts_duration:.1f} chars/sec)")
        elif TTS_PROVIDER == "chatterbox":
            logging.info("Generating voice track with Chatterbox (high-quality local model)...")
            voice_file = tmp_dir / "jason_full.wav"
            _synthesize_with_chatterbox(full_text, voice_file)
            if not voice_file.exists():
                raise FileNotFoundError(f"TTS generation failed: voice file not created at {voice_file}")

            # Validate voice file size and duration
            voice_file_size = voice_file.stat().st_size
            if voice_file_size < 10000:  # Less than 10KB is suspicious
                raise RuntimeError(f"Generated voice file is too small ({voice_file_size} bytes) - TTS likely failed")

            voice_audio_duration = get_audio_duration(voice_file)
            expected_min_duration = len(full_text) / 20  # Rough estimate: ~20 chars per second
            if voice_audio_duration < expected_min_duration * 0.1:  # Less than 10% of expected
                raise RuntimeError(f"Generated voice duration ({voice_audio_duration:.2f}s) is suspiciously short for {len(full_text)} characters (expected ~{expected_min_duration:.2f}s)")

            audio_files = [str(voice_file)]
            tts_duration = time.time() - tts_start_time
            logging.info(f"✅ Generated complete voice track: {voice_file} ({voice_audio_duration:.2f}s audio, {tts_duration:.1f}s generation time, {len(full_text)/tts_duration:.1f} chars/sec)")
        else:
            raise RuntimeError(f"Unsupported TTS provider: {TTS_PROVIDER}")
    except Exception as e:
        logging.error(f"❌ {TTS_PROVIDER.title()} TTS generation failed: {e}", exc_info=True)
        raise  # Re-raise to ensure workflow fails visibly

    # ========================== FINAL MIX ==========================
    final_mp3 = digests_dir / f"Lube_Change_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp3"
    
    MAIN_MUSIC = project_root / "LubechangeOilers.mp3"
    
    # Process and normalize voice in one step
    voice_mix = tmp_dir / "voice_normalized_mix.mp3"
    file_duration = get_audio_duration(voice_file)
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")

    # First, check if voice_file exists and has content
    if not voice_file.exists():
        raise RuntimeError(f"Voice file {voice_file} does not exist!")

    voice_file_size = voice_file.stat().st_size
    logging.info(f"Voice file size: {voice_file_size} bytes")

    if voice_file_size < 1000:  # Less than 1KB is suspicious
        raise RuntimeError(f"Voice file {voice_file} is too small ({voice_file_size} bytes) - TTS may have failed")

    # Try full filter chain first (with atempo for slower voice)
    try:
        logging.info("Attempting voice normalization with full filter chain...")
        # Professional audio processing: slow slightly, normalize, gently compress, limit
        # Chain: speed ↓10% -> HP/LP -> EBU loudnorm -> gentle compression -> limiter
        # Optimized: use faster preset and threads for parallel processing
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-i", str(voice_file),  # -threads 0 = auto-detect CPU cores
            "-af", "atempo=0.9,highpass=f=80,lowpass=f=15000,loudnorm=I=-16:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-18dB:ratio=2.5:attack=10:release=80:makeup=1.5,alimiter=level_in=1:level_out=0.98:limit=0.98",
            "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "256k", "-preset", "fast",  # Faster encoding preset
            str(voice_mix)
        ], check=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.CalledProcessError as e:
        logging.warning(f"Full filter chain failed: {e}")
        logging.warning("Trying simpler normalization...")
        # Fallback to simpler processing (without atempo to avoid issues)
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-i", str(voice_file),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true",
            "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "256k", "-preset", "fast",
            str(voice_mix)
        ], check=True, capture_output=True, timeout=timeout_seconds)

    # Verify the output file was created
    if not voice_mix.exists():
        raise RuntimeError(f"Voice mix file {voice_mix} was not created!")

    voice_mix_size = voice_mix.stat().st_size
    logging.info(f"Voice mix file size: {voice_mix_size} bytes")

    if voice_mix_size < 1000:
        raise RuntimeError(f"Voice mix file {voice_mix} is too small ({voice_mix_size} bytes) - processing failed")
    
    if not MAIN_MUSIC.exists():
        subprocess.run(["ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix), "-preset", "fast", str(final_mp3)], check=True, capture_output=True)
        logging.info("Podcast ready (voice-only, no music file found)")
    else:
        # Get voice duration to calculate music timing
        voice_duration = max(get_audio_duration(voice_mix), 0.0)
        logging.info(f"Voice duration: {voice_duration:.2f} seconds")
        
        # Music timing - Professional intro with perfect overlap (same as planetterrian)
        music_fade_in_start = max(voice_duration - 25.0, 0.0)
        music_fade_in_duration = min(35.0, voice_duration - music_fade_in_start)
        
        # Create music segments - OPTIMIZED: Generate independent segments in parallel
        music_intro = tmp_dir / "music_intro.mp3"
        music_overlap = tmp_dir / "music_overlap.mp3"
        music_fadeout = tmp_dir / "music_fadeout.mp3"
        music_tail_full = tmp_dir / "music_tail_full.mp3"
        music_tail_fadeout = tmp_dir / "music_tail_fadeout.mp3"
        
        def generate_music_segment(segment_name, cmd_args):
            """Helper to generate a single music segment."""
            subprocess.run(cmd_args, check=True, capture_output=True)
        
        # Generate independent music segments in parallel (don't depend on voice_duration)
        logging.info("Generating music segments in parallel...")
        independent_segments = [
            ("intro", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-t", "10",
                      "-af", "volume=0.6", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                      str(music_intro)]),
            ("overlap", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "10", "-t", "3",
                        "-af", "volume=0.5", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                        str(music_overlap)]),
            ("fadeout", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "13", "-t", "36",
                        "-af", "volume=0.4,afade=t=out:curve=log:st=0:d=36", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                        str(music_fadeout)]),
            ("tail_full", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "49", "-t", "60",
                          "-af", "volume=0.4", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                          str(music_tail_full)]),
            ("tail_fadeout", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "109", "-t", "40",
                             "-af", "volume=0.4,afade=t=out:st=0:d=40", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                             str(music_tail_fadeout)]),
        ]
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(generate_music_segment, name, cmd): name for name, cmd in independent_segments}
            for future in as_completed(futures):
                segment_name = futures[future]
                try:
                    future.result()
                    logging.debug(f"Generated music segment: {segment_name}")
                except Exception as e:
                    logging.error(f"Failed to generate music segment {segment_name}: {e}")
                    raise
        
        # Generate voice-dependent segments (fadein and silence depend on voice_duration)
        middle_silence_duration = max(music_fade_in_start - 31.0, 0.0)
        music_silence = tmp_dir / "music_silence.mp3"
        music_fadein = tmp_dir / "music_fadein.mp3"
        
        voice_dependent_segments = []
        if middle_silence_duration > 0.1:
            voice_dependent_segments.append(("silence", ["ffmpeg", "-y", "-threads", "0", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                                                         "-t", f"{middle_silence_duration:.2f}", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                                                         str(music_silence)]))
        
        voice_dependent_segments.append(("fadein", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "30", "-t", f"{music_fade_in_duration:.2f}",
                                                    "-af", f"volume=0.4,afade=t=in:st=0:d={music_fade_in_duration:.2f}", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                                                    str(music_fadein)]))
        
        if voice_dependent_segments:
            with ThreadPoolExecutor(max_workers=len(voice_dependent_segments)) as executor:
                futures = {executor.submit(generate_music_segment, name, cmd): name for name, cmd in voice_dependent_segments}
                for future in as_completed(futures):
                    segment_name = futures[future]
                    try:
                        future.result()
                        logging.debug(f"Generated music segment: {segment_name}")
                    except Exception as e:
                        logging.error(f"Failed to generate music segment {segment_name}: {e}")
                        raise
        
        # Concatenate music and delay voice in parallel (they don't depend on each other)
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
        voice_delayed = tmp_dir / "voice_delayed.mp3"
        
        logging.info("Concatenating music and delaying voice in parallel...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            concat_future = executor.submit(subprocess.run,
                ["ffmpeg", "-y", "-threads", "0", "-f", "concat", "-safe", "0", "-i", str(music_concat_list),
                 "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                 str(background_track)],
                check=True, capture_output=True)
            delay_future = executor.submit(subprocess.run,
                ["ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix),
                 "-af", "adelay=10000|10000",
                 "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                 str(voice_delayed)],
                check=True, capture_output=True)
            
            concat_future.result()
            delay_future.result()
        
        # Final mix: voice + music
        logging.info("Mixing voice and music...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(voice_delayed),
            "-i", str(background_track),
            "-filter_complex",
            "[0:a]volume=1.0[a_voice];"
            "[1:a]volume=0.3[a_music];"
            "[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2:weights=3 1[mixed];"
            "[mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
            "-map", "[outfinal]",
            "-c:a", "libmp3lame",
            "-b:a", "192k", "-preset", "fast",
            str(final_mp3)
        ], check=True, capture_output=True)
        
        # Verify final file was created and has content
        if not final_mp3.exists():
            raise RuntimeError(f"Final podcast file {final_mp3} was not created!")

        final_size = final_mp3.stat().st_size
        logging.info(f"Final podcast file size: {final_size} bytes")

        if final_size < 10000:  # Less than 10KB is definitely wrong for a 55s podcast
            raise RuntimeError(f"Final podcast file {final_mp3} is too small ({final_size} bytes) - mixing failed")

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