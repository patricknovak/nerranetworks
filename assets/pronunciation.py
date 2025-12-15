"""
Shared pronunciation dictionary for all podcasts.
This module provides pronunciation fixes for acronyms, names, and terms
that TTS engines commonly mispronounce.
"""

import re
from typing import Dict


# ========================== SHARED PRONUNCIATION DICTIONARIES ==========================

# Common acronyms that should be spelled letter-by-letter
COMMON_ACRONYMS: Dict[str, str] = {
    "AI": "A I",
    "ML": "M L",
    "NASA": "N A S A",
    "ESA": "E S A",
    "JAXA": "J A X A",
    "ISS": "I S S",
    "JWST": "J W S T",
    "HST": "H S T",
    "SLS": "S L S",
    "FAA": "F A A",
    "ULA": "U L A",
    "SpaceX": "Space X",
    "LRO": "L R O",
    "OSIRIS-REx": "O S I R I S R E X",
    "DART": "D A R T",
    "PSYCHE": "P S Y C H E",
    "DNA": "D N A",
    "RNA": "R N A",
    "CRISPR": "C R I S P R",
    "mRNA": "m R N A",
    "FDA": "F D A",
    "NIH": "N I H",
    "WHO": "W H O",
    "NHL": "N H L",
    "NHLPA": "N H L P A",
    "AHL": "A H L",
    "TSLA": "T S L A",
    "FSD": "F S D",
    "HW3": "H W 3",
    "HW4": "H W 4",
    "AI5": "A I 5",
    "EV": "E V",
    "EVs": "E Vs",
    "BEV": "B E V",
    "PHEV": "P H E V",
    "ICE": "I C E",
    "NHTSA": "N H T S A",
    "OTA": "O T A",
    "LFP": "L F P",
}

# Hockey-specific terms (for Lube Change)
HOCKEY_TERMS: Dict[str, str] = {
    "PP": "power play",
    "PK": "penalty kill",
    "SHG": "short-handed goal",
    "PPG": "power play goal",
    "ENG": "empty net goal",
    "OT": "overtime",
    "3v3": "three on three",
    "5v5": "five on five",
    "4v4": "four on four",
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
    "LW": "left wing",
    "RW": "right wing",
    "OTL": "overtime loss",
    "PTS": "points",
}

# Common player names and pronunciations
PLAYER_NAMES: Dict[str, str] = {
    # Add common player names here if needed
    # Format: "Last Name": "Pronunciation",
}

# Common word pronunciations
WORD_PRONUNCIATIONS: Dict[str, str] = {
    "Planetterrian": "Planet terry an",
    "planetterrian": "planet terry an",
    "shootout": "shoot out",
    "shoot-out": "shoot out",
    "shoot out": "shoot out",
}


def apply_pronunciation_fixes(
    text: str,
    acronyms: Dict[str, str] = None,
    hockey_terms: Dict[str, str] = None,
    player_names: Dict[str, str] = None,
    word_pronunciations: Dict[str, str] = None,
    use_zwj: bool = False,
) -> str:
    """
    Apply pronunciation fixes to text.
    
    Args:
        text: Input text to fix
        acronyms: Dictionary of acronyms to spell out (defaults to COMMON_ACRONYMS)
        hockey_terms: Dictionary of hockey terms (defaults to HOCKEY_TERMS)
        player_names: Dictionary of player name pronunciations (defaults to PLAYER_NAMES)
        word_pronunciations: Dictionary of word pronunciations (defaults to WORD_PRONUNCIATIONS)
        use_zwj: If True, use zero-width joiner; if False, use spaces (better for most TTS)
    
    Returns:
        Text with pronunciation fixes applied
    """
    if acronyms is None:
        acronyms = COMMON_ACRONYMS
    if hockey_terms is None:
        hockey_terms = HOCKEY_TERMS
    if player_names is None:
        player_names = PLAYER_NAMES
    if word_pronunciations is None:
        word_pronunciations = WORD_PRONUNCIATIONS
    
    # Zero-width joiner (only used if use_zwj=True)
    ZWJ = "\u2060" if use_zwj else " "
    
    # Fix acronyms (must be whole words)
    for acronym, spelled in acronyms.items():
        pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
        if ' ' in spelled:
            replacement = spelled
        elif use_zwj:
            replacement = ZWJ.join(list(spelled))
        else:
            replacement = " ".join(list(spelled))
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    # Fix hockey terms (phrases)
    for term, phrase in hockey_terms.items():
        pattern = rf'(?<!\w){re.escape(term)}(?!\w)'
        text = re.sub(pattern, phrase, text, flags=re.IGNORECASE)
    
    # Fix player names
    for name, pronunciation in player_names.items():
        pattern = rf'(?<!\w){re.escape(name)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)
    
    # Fix word pronunciations
    for word, pronunciation in word_pronunciations.items():
        pattern = rf'(?<!\w){re.escape(word)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)
    
    return text

