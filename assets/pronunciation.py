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
    # AI and ML
    "AI": "A I",
    "ML": "M L",
    "OpenAI": "Open A.I.",
    "GenAI": "Gen A.I.",
    # Space agencies and missions
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
    # Biology and health
    "DNA": "D N A",
    "RNA": "R N A",
    "CRISPR": "C R I S P R",
    "CRISPR-Cas9": "C R I S P R Cas 9",
    "mRNA": "m R N A",
    "FDA": "F D A",
    "NIH": "N I H",
    "WHO": "W H O",
    # Tesla and EVs
    "TSLA": "T S L A",
    "FSD": "F S D",
    "HW3": "H W 3",
    "HW4": "H W 4",
    "AI5": "A I 5",
    "4680": "4 6 8 0",
    "EV": "E V",
    "EVs": "E V s",  # Fixed: spell out "s" separately to prevent "E.V.S" pronunciation
    "BEV": "B E V",
    "PHEV": "P H E V",
    "ICE": "I C E",
    "NHTSA": "N H T S A",
    "OTA": "O T A",
    "LFP": "L F P",
}

# Optional domain-specific terms. Keep these empty by default to avoid
# baking a specific show's vocabulary into all podcasts.
HOCKEY_TERMS: Dict[str, str] = {}

# Optional domain-specific proper nouns (left empty by default).
OILERS_PLAYER_NAMES: Dict[str, str] = {}

# Common player names and pronunciations (generic - can be extended)
PLAYER_NAMES: Dict[str, str] = {
    # Can be extended with other player names as needed
}

# Common word pronunciations
WORD_PRONUNCIATIONS: Dict[str, str] = {
    "Planetterrian": "Planet terry an",
    "planetterrian": "planet terry an",
    "Robotaxis": "Robotaxi s",
    "Robotaxi": "Robotaxi",
    # Protect common words from being misread as acronyms
    # TTS engines sometimes read "who" as "W.H.O." - protect it
    "who": "who",
    "Who": "Who",
}


def apply_pronunciation_fixes(
    text: str,
    acronyms: Dict[str, str] = None,
    hockey_terms: Dict[str, str] = None,
    player_names: Dict[str, str] = None,
    oilers_player_names: Dict[str, str] = None,
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
    if oilers_player_names is None:
        oilers_player_names = OILERS_PLAYER_NAMES
    if word_pronunciations is None:
        word_pronunciations = WORD_PRONUNCIATIONS
    
    # Merge Oilers player names with generic player names (Oilers take precedence)
    all_player_names = {**player_names, **oilers_player_names}
    
    # Zero-width joiner (only used if use_zwj=True)
    ZWJ = "\u2060" if use_zwj else " "
    
    # Fix acronyms (must be whole words)
    for acronym, spelled in acronyms.items():
        # Special handling for "WHO" - only match uppercase to avoid matching "who" (the word)
        if acronym == "WHO":
            pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'  # Case-sensitive for WHO
            flags = 0  # No case-insensitive flag
        else:
            pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
            flags = re.IGNORECASE
        
        if ' ' in spelled:
            replacement = spelled
        elif use_zwj:
            replacement = ZWJ.join(list(spelled))
        else:
            replacement = " ".join(list(spelled))
        text = re.sub(pattern, replacement, text, flags=flags)
    
    # Fix hockey terms (phrases)
    for term, phrase in hockey_terms.items():
        pattern = rf'(?<!\w){re.escape(term)}(?!\w)'
        text = re.sub(pattern, phrase, text, flags=re.IGNORECASE)
    
    # Fix player names (Oilers + generic)
    for name, pronunciation in all_player_names.items():
        pattern = rf'(?<!\w){re.escape(name)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)
    
    # Fix word pronunciations
    for word, pronunciation in word_pronunciations.items():
        pattern = rf'(?<!\w){re.escape(word)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)
    
    return text

